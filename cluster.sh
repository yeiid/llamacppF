#!/usr/bin/env bash
# ============================================================
#  LLAMA.CPP RPC CLUSTER — CONTROL PRINCIPAL (Linux & Termux)
#
#  Uso:
#    ./cluster.sh setup              Clonar y compilar llama.cpp
#    ./cluster.sh download [ID|URL]  Descargar modelo GGUF del catálogo o URL
#    ./cluster.sh server [-f]        Iniciar servidor maestro (local o cluster RPC)
#    ./cluster.sh chat               Chatear con el modelo activo en terminal
#    ./cluster.sh run [PROMPT]       Ejecutar un modelo directamente con llama-cli
#    ./cluster.sh worker [-d]        Iniciar como nodo worker RPC
#    ./cluster.sh status             Ver estado del cluster y nodos
#    ./cluster.sh scan               Escanear nodos RPC en la red
#    ./cluster.sh stop               Detener todos los servicios
#    ./cluster.sh fix-ip [IP]        Asignar IP estática (Linux con sudo)
#    ./cluster.sh diag               Diagnóstico completo del sistema y red
#    ./cluster.sh test               Prueba rápida de inferencia
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
MODEL_DIR="$SCRIPT_DIR/models"
STATE_DIR="$SCRIPT_DIR/.state"
CONF_FILE="$SCRIPT_DIR/cluster.conf"

# Detectar Termux / Android
IS_TERMUX="false"
if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]] || [ -d "/data/data/com.termux" ]; then
    IS_TERMUX="true"
fi

# --- Defaults inteligentes según plataforma (núcleos físicos reales / performance cores) ---
RPC_PORT=50052
LLAMA_PORT=8080
CLUSTER_SUBNET=""
detect_optimal_threads() {
    if command -v python3 &>/dev/null && [ -f "$SCRIPT_DIR/cluster_core.py" ]; then
        local t
        t=$(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); import cluster_core; print(cluster_core.get_optimal_threads())" 2>/dev/null) || true
        if [[ "$t" =~ ^[0-9]+$ ]] && [ "$t" -ge 1 ]; then
            echo "$t"
            return 0
        fi
    fi
    local phys
    phys=$(awk '/^physical id/{p=$4} /^core id/{print p":"$4}' /proc/cpuinfo 2>/dev/null | sort -u | wc -l)
    if [ "${phys:-0}" -ge 1 ]; then
        echo "$phys"
        return 0
    fi
    local total
    total=$(nproc 2>/dev/null || echo 4)
    if [ "$total" -ge 4 ]; then
        echo $(( total / 2 ))
    else
        echo "$total"
    fi
}
THREADS=${THREADS:-$(detect_optimal_threads)}
CTX_SIZE=${CTX_SIZE:-4096}
if [ "$IS_TERMUX" = "true" ]; then
    CTX_SIZE=${CTX_SIZE:-2048}
fi
BATCH_SIZE=${BATCH_SIZE:-512}
NGL=${NGL:-auto}
KV_CACHE_TYPE=${KV_CACHE_TYPE:-f16}
RPC_CACHE=${RPC_CACHE:-true}
CUSTOM_NODES=${CUSTOM_NODES:-""}
EXCLUDED_NODES=${EXCLUDED_NODES:-""}

# --- Cargar configuración si existe ---
[ -f "$CONF_FILE" ] && source "$CONF_FILE"

# --- Estado ---
mkdir -p "$STATE_DIR" "$MODEL_DIR"
PID_RPC="$STATE_DIR/rpc.pid"
PID_LLAMA="$STATE_DIR/llama.pid"
LOG_RPC="$STATE_DIR/rpc.log"
LOG_LLAMA="$STATE_DIR/llama.log"
ARGS_FILE="$STATE_DIR/llama.args"
MODEL_FILE="$STATE_DIR/llama.model"

# --- Colores ---
RED='\033[0;31m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

info()   { echo -e "${CYAN}ℹ${NC} $1"; }
ok()     { echo -e "${GREEN}✓${NC} $1"; }
warn()   { echo -e "${YELLOW}!${NC} $1"; }
err()    { echo -e "${RED}✗${NC} $1"; }
header() { echo -e "\n${CYAN}${BOLD}─── $1 ───${NC}\n"; }

# --- Librerías (incluyendo soporte para $PREFIX/lib en Termux) ---
export LD_LIBRARY_PATH="${BIN_DIR}:${PREFIX:+$PREFIX/lib:}${LD_LIBRARY_PATH:-}"

# ====================== UTILIDADES ======================

acquire_wakelock() {
    if [ "$IS_TERMUX" = "true" ] && command -v termux-wake-lock &>/dev/null; then
        termux-wake-lock 2>/dev/null || true
    fi
}

release_wakelock() {
    if [ "$IS_TERMUX" = "true" ] && command -v termux-wake-unlock &>/dev/null; then
        termux-wake-unlock 2>/dev/null || true
    fi
}

is_alive() {
    local pid
    pid=$(cat "$1" 2>/dev/null) || return 1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

adopt_orphan() {
    local name="$1" pidfile="$2" pattern="$3"
    if ! is_alive "$pidfile"; then
        if command -v pgrep &>/dev/null; then
            local pid
            pid=$(pgrep -f "$pattern" 2>/dev/null | grep -v "^$$\$" | head -1) || true
            if [ -n "$pid" ]; then
                echo "$pid" > "$pidfile"
                ok "$name adoptado (PID $pid, sesión anterior)"
                return 0
            fi
        fi
        return 1
    fi
    return 0
}

detect_network() {
    ETH_IFACE="?"
    MY_IP=""
    SUBNET=""

    # 1. Interfaces Ethernet / USB Tethering (eth*, enp*, ens*, eno*, usb*, rndis*)
    local iface ip
    if [ -d /sys/class/net ] && command -v ip &>/dev/null; then
        for iface in $(ls /sys/class/net/ 2>/dev/null); do
            case "$iface" in lo|wl*|wlan*|ap*|swlan*|veth*|br*|docker*|virbr*|tun*|tap*|dummy*|rmnet*|ccmni*) continue ;; esac
            ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oE 'inet [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | awk '{print $2}' | head -1) || true
            if [ -n "$ip" ]; then
                ETH_IFACE="$iface"
                MY_IP="$ip"
                break
            fi
        done

        # 2. Interfaces Wi-Fi (wlan*, wlp*, wl*, ap*, swlan* — esencial en Termux y laptops)
        if [ -z "$MY_IP" ]; then
            for iface in $(ls /sys/class/net/ 2>/dev/null); do
                case "$iface" in wl*|wlan*|ap*|swlan*)
                    ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oE 'inet [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | awk '{print $2}' | head -1) || true
                    if [ -n "$ip" ]; then
                        ETH_IFACE="$iface"
                        MY_IP="$ip"
                        break
                    fi
                    ;;
                esac
            done
        fi
    fi

    # 3. Fallback con ifconfig (común en Termux)
    if [ -z "$MY_IP" ] && command -v ifconfig &>/dev/null; then
        MY_IP=$(ifconfig 2>/dev/null | grep -oE 'inet (addr:)?[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | grep -v '^127\.' | head -1) || true
        [ -n "$MY_IP" ] && ETH_IFACE="wlan/net"
    fi

    # 4. Fallback con Python UDP socket (100% compatible con Android 10-15 / Termux sin permisos netlink)
    if [ -z "$MY_IP" ] && command -v python3 &>/dev/null; then
        read -r MY_IP SUBNET < <(python3 -c "import cluster_core; ip, sub = cluster_core.get_local_ip_and_subnet(); print(ip, sub)" 2>/dev/null || echo "")
        [ -n "$MY_IP" ] && [ "$ETH_IFACE" = "?" ] && ETH_IFACE="auto"
    fi

    # 5. Fallback con hostname -I
    if [ -z "$MY_IP" ] && command -v hostname &>/dev/null; then
        MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}') || true
    fi

    # 6. Fallback local offline (permite correr modelos en un solo nodo sin red)
    if [ -z "$MY_IP" ]; then
        MY_IP="127.0.0.1"
        ETH_IFACE="loopback"
    fi

    if [ -z "$SUBNET" ]; then
        if [ "$MY_IP" != "127.0.0.1" ]; then
            SUBNET=$(echo "$MY_IP" | cut -d. -f1-3)
        else
            SUBNET="192.168.1"
        fi
    fi
    [ -n "$CLUSTER_SUBNET" ] && SUBNET="$CLUSTER_SUBNET"
    [ -z "$CLUSTER_SUBNET" ] && CLUSTER_SUBNET="$SUBNET"
    return 0
}

check_bins() {
    if [ ! -x "$BIN_DIR/rpc-server" ] || [ ! -x "$BIN_DIR/llama-server" ]; then
        err "Binarios no encontrados en $BIN_DIR/. Ejecuta primero:"
        echo -e "  ${GREEN}./cluster.sh setup${NC}"
        exit 1
    fi
}

file_size_bytes() {
    stat -c%s "$1" 2>/dev/null || wc -c < "$1" 2>/dev/null || echo 0
}

select_model() {
    local models=()
    while IFS= read -r m; do
        [ -n "$m" ] && models+=("$m")
    done < <(find "$MODEL_DIR" -name "*.gguf" -type f 2>/dev/null | sort)

    if [ ${#models[@]} -eq 0 ]; then
        warn "No hay modelos .gguf descargados en $MODEL_DIR/"
        if command -v python3 &>/dev/null; then
            echo ""
            read -rp "  ¿Deseas descargar un modelo del catálogo ahora? [S/n]: " dl_ans
            if [[ "${dl_ans:-S}" =~ ^[SsYy]$ ]]; then
                python3 -c "import cluster_core; cluster_core.download_model_cli()"
                while IFS= read -r m; do
                    [ -n "$m" ] && models+=("$m")
                done < <(find "$MODEL_DIR" -name "*.gguf" -type f 2>/dev/null | sort)
            fi
        fi
        if [ ${#models[@]} -eq 0 ]; then
            err "No hay modelos disponibles. Descarga uno con:"
            echo -e "  ${GREEN}./cluster.sh download${NC}"
            exit 1
        fi
    fi

    # Si la variable MODEL ya está seteada, verificar si coincide con algún modelo
    if [ -n "${MODEL:-}" ]; then
        if [ -f "$MODEL" ]; then
            SELECTED_MODEL="$MODEL"
            ok "Modelo (var MODEL): $(basename "$SELECTED_MODEL")"
            return 0
        elif [ -f "$MODEL_DIR/$MODEL" ]; then
            SELECTED_MODEL="$MODEL_DIR/$MODEL"
            ok "Modelo (var MODEL): $(basename "$SELECTED_MODEL")"
            return 0
        else
            for m in "${models[@]}"; do
                if [[ "$(basename "$m")" == *"$MODEL"* ]]; then
                    SELECTED_MODEL="$m"
                    ok "Modelo (coincidencia): $(basename "$SELECTED_MODEL")"
                    return 0
                fi
            done
        fi
        warn "Modelo '$MODEL' no encontrado. Procediendo a selección manual."
    fi

    # Solo auto-seleccionar sin preguntar si NO hay terminal interactiva (ej. llamado desde API/cron)
    if [ ! -t 0 ]; then
        SELECTED_MODEL="${models[0]}"
        ok "Modelo (no-interactivo): $(basename "$SELECTED_MODEL")"
        return 0
    fi

    header "MODELOS DESCARGADOS ($MODEL_DIR)"
    local i=1
    for m in "${models[@]}"; do
        local size
        size=$(du -h "$m" 2>/dev/null | cut -f1 || echo "?")
        echo -e "  ${BOLD}[$i]${NC} $(basename "$m") ${DIM}($size)${NC}"
        i=$((i+1))
    done
    echo -e "  ${BOLD}[a]${NC} Auto (más pequeño / rápido)"
    echo -e "  ${BOLD}[d]${NC} Descargar otro modelo del catálogo"
    echo ""
    read -rp "  Modelo [1-${#models[@]}/a/d] (Enter=1): " opt
    [ -z "$opt" ] && opt="1"

    if [ "$opt" = "d" ] || [ "$opt" = "D" ]; then
        python3 -c "import cluster_core; cluster_core.download_model_cli()"
        select_model
        return 0
    elif [ "$opt" = "a" ] || [ "$opt" = "A" ]; then
        SELECTED_MODEL="${models[0]}"
        for m in "${models[@]}"; do
            [ "$(file_size_bytes "$m")" -lt "$(file_size_bytes "$SELECTED_MODEL")" ] && SELECTED_MODEL="$m"
        done
    elif [[ "$opt" =~ ^[0-9]+$ ]] && [ "$opt" -ge 1 ] && [ "$opt" -le "${#models[@]}" ]; then
        SELECTED_MODEL="${models[$((opt-1))]}"
    else
        err "Opción inválida"; exit 1
    fi
    ok "Modelo seleccionado: $(basename "$SELECTED_MODEL")"
}

# ====================== DOWNLOAD / MODELS ======================

cmd_download() {
    local target="${1:-}"
    if command -v python3 &>/dev/null; then
        python3 -c "import sys, cluster_core; cluster_core.download_model_cli(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None)" "$target"
    else
        err "Se requiere python3 para usar el gestor interactivo de modelos."
        exit 1
    fi
}

# ====================== WORKER ======================

cmd_worker() {
    check_bins
    detect_network
    acquire_wakelock

    if adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT"; then
        if is_alive "$PID_RPC"; then
            info "rpc-server ya activo (PID $(cat "$PID_RPC"))"
            echo -e "  Worker en: ${BOLD}$MY_IP:$RPC_PORT${NC}"
            echo "  Usa './cluster.sh stop' para detener"
            return 0
        fi
    fi

    local cache_flag=()
    [ "${RPC_CACHE:-true}" = "true" ] && cache_flag=("-c")

    header "WORKER RPC"
    echo -e "  IP:      ${BOLD}$MY_IP${NC}"
    echo -e "  Iface:   $ETH_IFACE"
    echo -e "  Puerto:  $RPC_PORT"
    echo -e "  Hilos:   $THREADS"
    echo -e "  Caché:   ${RPC_CACHE:-true}"
    echo ""

    if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--daemon" ]; then
        nohup "$BIN_DIR/rpc-server" -H 0.0.0.0 -p "$RPC_PORT" -t "$THREADS" "${cache_flag[@]}" \
            </dev/null >"$LOG_RPC" 2>&1 &
        echo $! > "$PID_RPC"
        disown 2>/dev/null || true
        sleep 2
        if is_alive "$PID_RPC"; then
            ok "Worker iniciado en background (PID $(cat "$PID_RPC"))"
            echo -e "  Log: ${DIM}$LOG_RPC${NC}"
        else
            err "Falló. Ver: tail $LOG_RPC"
        fi
    else
        info "Ctrl+C para detener"
        echo ""
        exec "$BIN_DIR/rpc-server" -H 0.0.0.0 -p "$RPC_PORT" -t "$THREADS" "${cache_flag[@]}"
    fi
}

# ====================== SCAN ======================

scan_nodes() {
    detect_network
    RPC_NODES=()

    if command -v python3 &>/dev/null; then
        while IFS= read -r ip; do
            [ -n "$ip" ] && RPC_NODES+=("$ip")
        done < <(python3 -c "
import cluster_core
cfg = cluster_core.load_config()
ips = cluster_core.scan_network_rpc('$SUBNET', $RPC_PORT, cfg)
for ip in ips:
    print(ip)
" 2>/dev/null)
        return 0
    fi

    local tmp
    tmp=$(mktemp)
    export SUBNET MY_IP RPC_PORT

    seq 1 254 | xargs -P 60 -I {} bash -c '
        ip="$SUBNET.{}"
        timeout 0.3 bash -c "echo > /dev/tcp/$ip/$RPC_PORT" 2>/dev/null && echo "$ip"
        exit 0
    ' 2>/dev/null > "$tmp" || true

    if [ -n "${CUSTOM_NODES:-}" ]; then
        IFS=',' read -ra cnodes <<< "$CUSTOM_NODES"
        for cnode in "${cnodes[@]}"; do
            cnode=$(echo "$cnode" | xargs)
            [ -z "$cnode" ] && continue
            local cip="${cnode%%:*}"
            local cport="${cnode#*:}"
            [ "$cport" = "$cip" ] && cport="$RPC_PORT"
            if timeout 0.4 bash -c "echo > /dev/tcp/$cip/$cport" 2>/dev/null; then
                echo "$cip" >> "$tmp"
            fi
        done
    fi

    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        if [[ ",${EXCLUDED_NODES:-}," == *",$ip,"* ]]; then
            continue
        fi
        RPC_NODES+=("$ip")
    done < <(sort -u -t. -k1,1n -k2,2n -k3,3n -k4,4n "$tmp")
    rm -f "$tmp"
}

cmd_scan() {
    detect_network
    header "ESCANEO DE RED ($SUBNET.0/24)"
    info "Buscando servidores RPC en puerto $RPC_PORT..."
    echo ""

    scan_nodes

    if [ ${#RPC_NODES[@]} -eq 0 ]; then
        warn "Ningún nodo RPC encontrado"
    else
        for node in "${RPC_NODES[@]}"; do
            local label=""
            [ "$node" = "$MY_IP" ] || [ "$node" = "127.0.0.1" ] && label=" ${DIM}(este dispositivo)${NC}"
            echo -e "  ${GREEN}●${NC} $node:$RPC_PORT$label"
        done
        echo ""
        echo -e "  Total: ${BOLD}${#RPC_NODES[@]}${NC} nodos"

        local rpc_str=""
        for node in "${RPC_NODES[@]}"; do
            [ "$node" = "$MY_IP" ] || [ "$node" = "127.0.0.1" ] && continue
            [ -n "$rpc_str" ] && rpc_str="$rpc_str,"
            rpc_str="$rpc_str$node:$RPC_PORT"
        done
        if [ -n "$rpc_str" ]; then
            echo ""
            echo -e "  Workers remotos (--rpc): ${CYAN}$rpc_str${NC}"
        fi
    fi
    echo ""
}

# ====================== SERVER ======================

cmd_server() {
    check_bins
    detect_network
    select_model
    acquire_wakelock

    # Escanear red para detectar workers RPC remotos
    info "Escaneando nodos RPC remotos en la red..."
    scan_nodes

    local remote_nodes=()
    for n in "${RPC_NODES[@]}"; do
        if [ "$n" != "$MY_IP" ] && [ "$n" != "127.0.0.1" ]; then
            remote_nodes+=("$n")
        fi
    done

    local rpc_str=""
    local rpc_args=()
    echo ""
    if [ ${#remote_nodes[@]} -gt 0 ]; then
        echo -e "  Modo: ${BOLD}${GREEN}Cluster Distribuido RPC${NC} (${#remote_nodes[@]} workers remotos + nodo local)"
        for n in "${remote_nodes[@]}"; do
            echo -e "    ${GREEN}●${NC} $n:$RPC_PORT (worker remoto)"
            [ -n "$rpc_str" ] && rpc_str="$rpc_str,"
            rpc_str="$rpc_str$n:$RPC_PORT"
        done
        rpc_args=("--rpc" "$rpc_str")
    else
        echo -e "  Modo: ${BOLD}${CYAN} inferencia Local Directa${NC} (Sin overhead RPC local — uso óptimo de RAM y CPU)"
    fi

    local model_basename
    model_basename="$(basename "$SELECTED_MODEL")"
    local current_sig="${model_basename}|${rpc_str}|${CTX_SIZE}|${BATCH_SIZE}|${THREADS}|${NGL:-auto}|${KV_CACHE_TYPE:-f16}"

    # Verificar si ya corre con misma config
    local prev
    prev=$(cat "$ARGS_FILE" 2>/dev/null) || true
    if [ "$prev" = "$current_sig" ] && is_alive "$PID_LLAMA"; then
        ok "llama-server ya corre con esta configuración"
        echo -e "  API: ${BOLD}http://$MY_IP:$LLAMA_PORT${NC}"
        return 0
    fi

    # Detener anterior
    if is_alive "$PID_LLAMA"; then
        kill "$(cat "$PID_LLAMA")" 2>/dev/null || true
        sleep 1
    fi

    header "INICIANDO LLAMA-SERVER"
    echo -e "  Modelo: ${BOLD}$model_basename${NC}"
    echo -e "  RPC:    ${rpc_str:-ninguno (local directo)}"
    echo -e "  Hilos:  $THREADS | Contexto: $CTX_SIZE | Batch: $BATCH_SIZE"
    echo -e "  Capas:  ${NGL:-auto} | KV Cache: ${KV_CACHE_TYPE:-f16}"
    echo -e "  API:    ${BOLD}http://$MY_IP:$LLAMA_PORT${NC}"
    echo ""

    echo "$model_basename" > "$MODEL_FILE"
    echo "$current_sig" > "$ARGS_FILE"

    # Sincronizar opencode.json si python3 está disponible
    if command -v python3 &>/dev/null; then
        python3 -c "import cluster_core; cluster_core.sync_opencode_json('$model_basename', $LLAMA_PORT, $CTX_SIZE)" 2>/dev/null || true
    fi

    if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--foreground" ]; then
        exec "$BIN_DIR/llama-server" \
            -m "$SELECTED_MODEL" \
            "${rpc_args[@]}" \
            --host 0.0.0.0 --port "$LLAMA_PORT" \
            --ctx-size "$CTX_SIZE" --batch-size "$BATCH_SIZE" \
            --threads "$THREADS" -ngl "${NGL:-auto}" \
            -ctk "${KV_CACHE_TYPE:-f16}" -ctv "${KV_CACHE_TYPE:-f16}" \
            -fa auto --cont-batching
    else
        nohup "$BIN_DIR/llama-server" \
            -m "$SELECTED_MODEL" \
            "${rpc_args[@]}" \
            --host 0.0.0.0 --port "$LLAMA_PORT" \
            --ctx-size "$CTX_SIZE" --batch-size "$BATCH_SIZE" \
            --threads "$THREADS" -ngl "${NGL:-auto}" \
            -ctk "${KV_CACHE_TYPE:-f16}" -ctv "${KV_CACHE_TYPE:-f16}" \
            -fa auto --cont-batching \
            </dev/null >"$LOG_LLAMA" 2>&1 &
        echo $! > "$PID_LLAMA"
        disown 2>/dev/null || true

        info "Esperando que cargue el modelo..."
        local tries=0
        while [ $tries -lt 90 ]; do
            if curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then
                echo ""
                ok "llama-server listo para inferencia!"
                echo -e "  API OpenAI: ${GREEN}http://$MY_IP:$LLAMA_PORT/v1${NC}"
                echo -e "  Web UI:     ${GREEN}http://127.0.0.1:$LLAMA_PORT${NC}"
                echo -e "  Chat CLI:   ${CYAN}./cluster.sh chat${NC}"
                echo -e "  Log:        ${DIM}$LOG_LLAMA${NC}"
                return 0
            fi
            if ! is_alive "$PID_LLAMA"; then
                echo ""
                err "llama-server se detuvo durante la carga:"
                tail -15 "$LOG_LLAMA" 2>/dev/null | sed 's/^/  /'
                return 1
            fi
            sleep 2
            tries=$((tries+1))
            echo -ne "\r  Cargando modelo en memoria... $((tries*2))s"
        done
        echo ""
        warn "Sigue cargando en segundo plano. Revisa: tail -f $LOG_LLAMA"
    fi
}

# ====================== CHAT & RUN DIRECTO ======================

cmd_chat() {
    detect_network
    if curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then
        local cur_model="actual"
        [ -f "$MODEL_FILE" ] && cur_model="$(cat "$MODEL_FILE")"
        if [ -t 0 ]; then
            echo ""
            info "Servidor activo con el modelo: ${BOLD}$cur_model${NC}"
            read -rp "  Presiona Enter para chatear con este modelo o escribe 'm' para elegir otro descargado: " ch_opt
            if [ "${ch_opt:-}" = "m" ] || [ "${ch_opt:-}" = "M" ]; then
                cmd_server || exit 1
            fi
        fi
    else
        info "El servidor maestro no está activo. Selecciona el modelo a iniciar:"
        cmd_server || exit 1
    fi
    python3 "$SCRIPT_DIR/cluster-cli.py" chat
}

cmd_run() {
    check_bins
    select_model
    acquire_wakelock
    local prompt="${*:-}"

    header "EJECUCIÓN DIRECTA (LLAMA-CLI)"
    echo -e "  Modelo: ${BOLD}$(basename "$SELECTED_MODEL")${NC}"
    echo -e "  Hilos:  $THREADS | Contexto: $CTX_SIZE"
    echo ""

    if [ -n "$prompt" ]; then
        "$BIN_DIR/llama-cli" \
            -m "$SELECTED_MODEL" \
            -t "$THREADS" -c "$CTX_SIZE" -ngl "${NGL:-auto}" \
            -p "$prompt" -n 512 -no-cnv --no-display-prompt
        echo ""
    else
        info "Modo conversación interactiva (Ctrl+C para salir)"
        "$BIN_DIR/llama-cli" \
            -m "$SELECTED_MODEL" \
            -t "$THREADS" -c "$CTX_SIZE" -ngl "${NGL:-auto}" \
            -cnv
    fi
}

# ====================== STATUS ======================

cmd_status() {
    detect_network

    adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT" 2>/dev/null || true
    adopt_orphan "llama-server" "$PID_LLAMA" "llama-server.*--port $LLAMA_PORT" 2>/dev/null || true

    header "ESTADO DEL SISTEMA"
    echo -e "  Nodo: $(hostname 2>/dev/null || echo 'local') — ${BOLD}$MY_IP${NC} ($ETH_IFACE) [Termux: $IS_TERMUX]"
    echo ""

    echo -n "  rpc-server:   "
    if is_alive "$PID_RPC"; then
        echo -e "${GREEN}ACTIVO${NC} (PID $(cat "$PID_RPC"), Puerto $RPC_PORT)"
    else
        echo -e "${DIM}DETENIDO${NC}"
    fi

    echo -n "  llama-server: "
    if is_alive "$PID_LLAMA"; then
        echo -e "${GREEN}ACTIVO${NC} (PID $(cat "$PID_LLAMA"))"
        echo -e "  API:          http://$MY_IP:$LLAMA_PORT"
        [ -f "$MODEL_FILE" ] && echo -e "  Modelo:       $(cat "$MODEL_FILE")"
        echo -n "  Health:       "
        curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1 && \
            echo -e "${GREEN}LISTO${NC}" || echo -e "${YELLOW}cargando...${NC}"
    else
        echo -e "${DIM}DETENIDO${NC}"
    fi

    echo ""
    info "Escaneando red ($SUBNET.0/24)..."
    scan_nodes
    echo -e "  Nodos RPC activos: ${BOLD}${#RPC_NODES[@]}${NC}"
    for n in "${RPC_NODES[@]}"; do
        local label=""
        [ "$n" = "$MY_IP" ] || [ "$n" = "127.0.0.1" ] && label=" (este dispositivo)"
        echo -e "    ${GREEN}●${NC} $n:$RPC_PORT$label"
    done
    echo ""
}

# ====================== STOP ======================

cmd_stop() {
    header "DETENIENDO SERVICIOS"
    adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT" 2>/dev/null || true
    adopt_orphan "llama-server" "$PID_LLAMA" "llama-server.*--port $LLAMA_PORT" 2>/dev/null || true

    if is_alive "$PID_LLAMA"; then
        kill "$(cat "$PID_LLAMA")" 2>/dev/null || true
        ok "llama-server detenido"
    fi
    if is_alive "$PID_RPC"; then
        kill "$(cat "$PID_RPC")" 2>/dev/null || true
        ok "rpc-server detenido"
    fi
    rm -f "$PID_RPC" "$PID_LLAMA" "$ARGS_FILE" "$MODEL_FILE"
    release_wakelock
    ok "Limpio"
}

# ====================== FIX-IP ======================

cmd_fix_ip() {
    if [ "$IS_TERMUX" = "true" ]; then
        warn "En Android/Termux la IP se asigna desde los Ajustes de Wi-Fi/Hotspot de Android."
        return 0
    fi
    detect_network
    local target_ip="${1:-}"

    header "CONFIGURAR IP ESTÁTICA"

    local iface=""
    for i in $(ls /sys/class/net/ 2>/dev/null); do
        case "$i" in lo|wl*|veth*|br*|docker*|virbr*) continue ;; esac
        iface="$i"
        break
    done

    if [ -z "$iface" ]; then
        err "No se detectó interfaz ethernet física"
        exit 1
    fi

    echo "  Interfaz: $iface"
    echo "  IP actual: $(ip -4 addr show "$iface" 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' || echo 'ninguna')"

    if [ -z "$target_ip" ]; then
        echo ""
        read -rp "  IP a asignar (ej: 192.168.194.101): " target_ip
    fi

    if [[ ! "$target_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        err "IP inválida: $target_ip"
        exit 1
    fi

    local subnet
    subnet=$(echo "$target_ip" | cut -d. -f1-3)

    echo ""
    info "Asignando $target_ip/24 a $iface..."
    sudo ip addr flush dev "$iface" 2>/dev/null
    sudo ip addr add "$target_ip/24" dev "$iface"
    sudo ip link set "$iface" up
    sudo ip route add "$subnet.0/24" dev "$iface" 2>/dev/null || true
    sleep 1

    local new_ip
    new_ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}')
    if [ "$new_ip" = "$target_ip" ]; then
        ok "IP configurada: $new_ip"

        if [ -f "$CONF_FILE" ] && grep -q "^CLUSTER_SUBNET=" "$CONF_FILE"; then
            sed -i "s|^CLUSTER_SUBNET=.*|CLUSTER_SUBNET=\"$subnet\"|" "$CONF_FILE"
        else
            echo "CLUSTER_SUBNET=\"$subnet\"" >> "$CONF_FILE"
        fi
        ok "Subred guardada en cluster.conf"
    else
        err "No se pudo asignar la IP"
    fi
}

# ====================== DIAG ======================

cmd_diag() {
    detect_network
    header "DIAGNÓSTICO"

    echo "  Hostname:  $(hostname 2>/dev/null || echo 'android-termux')"
    echo "  Entorno:   $(uname -sr) (Termux: $IS_TERMUX)"
    echo "  Arch:      $(uname -m)"
    echo "  IP Local:  $MY_IP ($ETH_IFACE)"
    echo "  Subred:    $SUBNET.0/24"
    echo "  CPU:       $(grep -m1 -E 'model name|Hardware|Processor' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || uname -p)"
    echo "  RAM:       $(awk '/MemTotal/{t=$2/1024/1024} /MemAvailable/{a=$2/1024/1024} END{printf "%.1f GB total, %.1f GB disponible", t, a}' /proc/meminfo 2>/dev/null || echo '?')"
    echo "  Cores:     $(nproc 2>/dev/null || echo '?') (Usando THREADS=$THREADS)"
    echo ""

    echo -n "  rpc-server:   "
    [ -x "$BIN_DIR/rpc-server" ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALTA${NC} (ejecuta ./cluster.sh setup)"

    echo -n "  llama-server: "
    [ -x "$BIN_DIR/llama-server" ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALTA${NC}"

    echo -n "  llama-cli:    "
    [ -x "$BIN_DIR/llama-cli" ] && echo -e "${GREEN}OK${NC}" || echo -e "${YELLOW}FALTA${NC}"

    # Puerto RPC local
    echo -n "  Puerto $RPC_PORT: "
    if command -v python3 &>/dev/null; then
        python3 -c "import cluster_core; exit(0 if cluster_core.scan_ip_port_with_latency('127.0.0.1', $RPC_PORT, 0.3) else 1)" 2>/dev/null && \
            echo -e "${GREEN}ABIERTO${NC}" || echo -e "${DIM}cerrado${NC}"
    else
        timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/$RPC_PORT" 2>/dev/null && \
            echo -e "${GREEN}ABIERTO${NC}" || echo -e "${DIM}cerrado${NC}"
    fi

    echo ""
    info "Servidores RPC activos en $SUBNET.0/24..."
    scan_nodes
    for n in "${RPC_NODES[@]}"; do
        echo -e "  ${GREEN}●${NC} $n:$RPC_PORT"
    done
    [ ${#RPC_NODES[@]} -eq 0 ] && echo "  (ninguno)"
    echo ""
}

# ====================== TEST ======================

cmd_test() {
    detect_network
    header "TEST DE INFERENCIA"

    echo -n "  Health check: "
    if ! curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then
        err "llama-server no responde en puerto $LLAMA_PORT"
        echo "  Inícialo primero con: ./cluster.sh server"
        return 1
    fi
    echo -e "${GREEN}OK${NC}"

    info "Enviando prompt de prueba..."
    local resp
    resp=$(timeout 45 curl -sf "http://127.0.0.1:$LLAMA_PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{"messages":[{"role":"user","content":"Responde únicamente con la palabra: FUNCIONA"}],"max_tokens":16,"temperature":0.1}' 2>/dev/null) || true

    if [ -n "$resp" ]; then
        local content
        content=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'].strip())" 2>/dev/null) || true
        if [ -n "$content" ]; then
            ok "Respuesta del modelo: ${BOLD}$content${NC}"
        else
            warn "Respuesta recibida pero no parseable"
            echo "  $resp" | head -c 200
        fi
    else
        err "Sin respuesta (timeout o error)"
    fi
}

# ====================== TOOLS & BENCH ======================

cmd_tools() {
    local sub="${1:-}"
    if [ -z "$sub" ] || [ "$sub" = "list" ]; then
        header "SUITE DE HERRAMIENTAS LLAMA.CPP EN BIN/"
        local count=0
        for f in "$BIN_DIR"/llama-* "$BIN_DIR"/rpc-server; do
            if [ -f "$f" ] && [ -x "$f" ] && [[ "$(basename "$f")" != *.so* ]]; then
                printf "  ${GREEN}●${NC} %-32s\n" "$(basename "$f")"
                count=$((count + 1))
            fi
        done
        echo ""
        ok "Total: $count herramientas disponibles."
        echo -e "  Ejecuta cualquiera con: ${CYAN}./cluster.sh tools <nombre-herramienta> [argumentos]${NC}"
        echo -e "  Ejemplo: ${CYAN}./cluster.sh tools llama-tokenize -m models/Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf -p 'Hola mundo'${NC}"
        echo ""
        return 0
    fi

    shift
    local bin_path="$BIN_DIR/$sub"
    if [ ! -x "$bin_path" ] && [ -x "$BIN_DIR/llama-$sub" ]; then
        bin_path="$BIN_DIR/llama-$sub"
    fi
    if [ ! -x "$bin_path" ]; then
        err "Herramienta '$sub' no encontrada en $BIN_DIR"
        return 1
    fi
    exec "$bin_path" "$@"
}

cmd_bench() {
    select_model
    header "BENCHMARK NATIVO C++ (llama-bench)"
    info "Comparando rendimiento en hilos (-t 1,2,$THREADS) con $(basename "$SELECTED_MODEL")..."
    "$BIN_DIR/llama-bench" -m "$SELECTED_MODEL" -t "1,2,$THREADS" -p 128 -n 64
}

# ====================== HELP ======================

cmd_help() {
    echo ""
    echo -e "${BOLD}LLAMA.CPP RPC CLUSTER (Linux & Termux)${NC}"
    echo ""
    echo "  Uso: ./cluster.sh <comando> [opciones]"
    echo ""
    echo -e "  ${BOLD}Comandos de Modelos, Inferencia y Herramientas:${NC}"
    echo "    download [ID|URL]  Catálogo interactivo para descargar modelos .gguf"
    echo "    server [-f]        Iniciar servidor maestro (usa RPC si hay workers, o local directo)"
    echo "    chat               Abrir chat interactivo en consola (muestra t/s y guarda código)"
    echo "    run [prompt]       Correr un modelo directamente con llama-cli sin servidor"
    echo "    bench              Ejecutar benchmark C++ nativo multi-hilo (llama-bench)"
    echo "    tools [bin] [args] Listar o ejecutar cualquiera de las 47 herramientas de llama.cpp"
    echo "    test               Probar inferencia contra el servidor activo"
    echo ""
    echo -e "  ${BOLD}Comandos de Cluster y Red:${NC}"
    echo "    setup              Clonar y compilar llama.cpp automáticamente"
    echo "    worker [-d]        Iniciar este dispositivo como worker RPC (-d = background)"
    echo "    status             Ver estado del servidor, worker y nodos en la red"
    echo "    scan               Escanear nodos RPC en la red LAN / Wi-Fi"
    echo "    stop               Detener todos los servicios locales"
    echo "    diag               Diagnóstico completo de hardware, red y binarios"
    echo "    fix-ip [IP]        Asignar IP estática a ethernet (solo Linux con sudo)"
    echo ""
}

# ====================== MAIN ======================

case "${1:-help}" in
    setup)              source "$SCRIPT_DIR/setup.sh" ;;
    download|models|dl) cmd_download "${2:-}" ;;
    worker|w)           cmd_worker "${2:-}" ;;
    server|s)           cmd_server "${2:-}" ;;
    chat|c)             cmd_chat ;;
    run|r)              shift; cmd_run "$@" ;;
    bench|b)            cmd_bench ;;
    tools|tool)         shift; cmd_tools "$@" ;;
    status|st)          cmd_status ;;
    scan)               cmd_scan ;;
    stop)               cmd_stop ;;
    test|t)             cmd_test ;;
    fix-ip)             cmd_fix_ip "${2:-}" ;;
    diag|d)             cmd_diag ;;
    help|--help|-h|*)   cmd_help ;;
esac
