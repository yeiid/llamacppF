#!/bin/bash
# ============================================================
#  LLAMA.CPP RPC CLUSTER — CONTROL PRINCIPAL
#
#  Uso:
#    ./cluster.sh setup          Clonar y compilar llama.cpp
#    ./cluster.sh worker         Iniciar como worker RPC
#    ./cluster.sh server         Iniciar como servidor (maestro)
#    ./cluster.sh status         Ver estado del cluster
#    ./cluster.sh scan           Escanear nodos en la red
#    ./cluster.sh stop           Detener todo
#    ./cluster.sh fix-ip [IP]    Asignar IP estática
#    ./cluster.sh diag           Diagnóstico de red
#
#  Funciona en cualquier PC Linux. Solo necesita:
#    git, cmake, gcc, make
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
MODEL_DIR="$SCRIPT_DIR/models"
STATE_DIR="$SCRIPT_DIR/.state"
CONF_FILE="$SCRIPT_DIR/cluster.conf"

# --- Defaults (pueden sobreescribirse en cluster.conf) ---
RPC_PORT=50052
LLAMA_PORT=8080
CLUSTER_SUBNET=""
THREADS=$(nproc 2>/dev/null || echo 2)
CTX_SIZE=4096
BATCH_SIZE=512

# --- Cargar configuración si existe ---
[ -f "$CONF_FILE" ] && source "$CONF_FILE"

# --- Estado ---
mkdir -p "$STATE_DIR" "$MODEL_DIR"
PID_RPC="$STATE_DIR/rpc.pid"
PID_LLAMA="$STATE_DIR/llama.pid"
LOG_RPC="$STATE_DIR/rpc.log"
LOG_LLAMA="$STATE_DIR/llama.log"
ARGS_FILE="$STATE_DIR/llama.args"

# --- Colores ---
RED='\033[0;31m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

info()   { echo -e "${CYAN}ℹ${NC} $1"; }
ok()     { echo -e "${GREEN}✓${NC} $1"; }
warn()   { echo -e "${YELLOW}!${NC} $1"; }
err()    { echo -e "${RED}✗${NC} $1"; }
header() { echo -e "\n${CYAN}${BOLD}─── $1 ───${NC}\n"; }

# --- Librerías ---
export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"

# ====================== UTILIDADES ======================

is_alive() {
    local pid
    pid=$(cat "$1" 2>/dev/null) || return 1
    kill -0 "$pid" 2>/dev/null
}

adopt_orphan() {
    local name="$1" pidfile="$2" pattern="$3"
    if ! is_alive "$pidfile"; then
        local pid
        pid=$(pgrep -f "$pattern" 2>/dev/null | head -1) || true
        if [ -n "$pid" ]; then
            echo "$pid" > "$pidfile"
            ok "$name adoptado (PID $pid, sesión anterior)"
            return 0
        fi
        return 1
    fi
    return 0
}

detect_network() {
    # Encontrar interfaz ethernet con IP
    local iface ip
    for iface in $(ls /sys/class/net/ 2>/dev/null); do
        case "$iface" in lo|wl*|veth*|br*|docker*|virbr*) continue ;; esac
        ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1) || true
        if [ -n "$ip" ]; then
            ETH_IFACE="$iface"
            MY_IP="$ip"
            SUBNET=$(echo "$ip" | cut -d. -f1-3)
            [ -z "$CLUSTER_SUBNET" ] && CLUSTER_SUBNET="$SUBNET"
            return 0
        fi
    done

    # Fallback: cualquier IP no-loopback
    MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    ETH_IFACE="?"
    if [ -n "$MY_IP" ]; then
        SUBNET=$(echo "$MY_IP" | cut -d. -f1-3)
        [ -z "$CLUSTER_SUBNET" ] && CLUSTER_SUBNET="$SUBNET"
        return 0
    fi

    err "No se detectó ninguna IP de red"
    exit 1
}

check_bins() {
    if [ ! -x "$BIN_DIR/rpc-server" ] || [ ! -x "$BIN_DIR/llama-server" ]; then
        err "Binarios no encontrados. Ejecuta primero:"
        echo -e "  ${GREEN}./cluster.sh setup${NC}"
        exit 1
    fi
}

select_model() {
    local models=()
    while IFS= read -r m; do models+=("$m"); done < <(find "$MODEL_DIR" -name "*.gguf" -type f 2>/dev/null | sort)

    if [ ${#models[@]} -eq 0 ]; then
        err "No hay modelos .gguf en $MODEL_DIR/"
        echo "  Descarga un modelo y ponlo en:"
        echo "  $MODEL_DIR/"
        exit 1
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
            # Búsqueda por coincidencia parcial en nombre
            for m in "${models[@]}"; do
                if [[ "$(basename "$m")" == *"$MODEL"* ]]; then
                    SELECTED_MODEL="$m"
                    ok "Modelo (var MODEL coincidencia): $(basename "$SELECTED_MODEL")"
                    return 0
                fi
            done
        fi
        warn "Modelo '$MODEL' no encontrado. Procediendo a selección manual."
    fi

    header "MODELOS"
    local i=1
    for m in "${models[@]}"; do
        local size
        size=$(du -h "$m" | cut -f1)
        echo -e "  ${BOLD}[$i]${NC} $(basename "$m") ${DIM}($size)${NC}"
        i=$((i+1))
    done
    echo -e "  ${BOLD}[a]${NC} Auto (más pequeño)"
    echo ""
    read -rp "  Modelo: " opt

    if [ "$opt" = "a" ]; then
        SELECTED_MODEL="${models[0]}"
        for m in "${models[@]}"; do
            [ "$(stat -c%s "$m")" -lt "$(stat -c%s "$SELECTED_MODEL")" ] && SELECTED_MODEL="$m"
        done
    elif [[ "$opt" =~ ^[0-9]+$ ]] && [ "$opt" -ge 1 ] && [ "$opt" -le "${#models[@]}" ]; then
        SELECTED_MODEL="${models[$((opt-1))]}"
    else
        err "Opción inválida"; exit 1
    fi
    ok "Modelo: $(basename "$SELECTED_MODEL")"
}

# ====================== WORKER ======================

cmd_worker() {
    check_bins
    detect_network

    # Verificar si ya corre
    if adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT"; then
        if is_alive "$PID_RPC"; then
            info "rpc-server ya activo (PID $(cat "$PID_RPC"))"
            echo -e "  Worker en: ${BOLD}$MY_IP:$RPC_PORT${NC}"
            echo "  Usa './cluster.sh stop' para detener"
            return 0
        fi
    fi

    header "WORKER RPC"
    echo -e "  IP:      ${BOLD}$MY_IP${NC}"
    echo -e "  Iface:   $ETH_IFACE"
    echo -e "  Puerto:  $RPC_PORT"
    echo -e "  Hilos:   $THREADS"
    echo ""

    if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--daemon" ]; then
        # Modo daemon
        nohup "$BIN_DIR/rpc-server" -H 0.0.0.0 -p "$RPC_PORT" -t "$THREADS" \
            </dev/null >"$LOG_RPC" 2>&1 &
        echo $! > "$PID_RPC"
        sleep 2
        if is_alive "$PID_RPC"; then
            ok "Worker iniciado en background (PID $(cat "$PID_RPC"))"
            echo -e "  Log: ${DIM}$LOG_RPC${NC}"
        else
            err "Falló. Ver: tail $LOG_RPC"
        fi
    else
        # Modo foreground (Ctrl+C para salir)
        info "Ctrl+C para detener"
        echo ""
        exec "$BIN_DIR/rpc-server" -H 0.0.0.0 -p "$RPC_PORT" -t "$THREADS"
    fi
}

# ====================== SCAN ======================

scan_nodes() {
    detect_network
    local tmp
    tmp=$(mktemp)
    export SUBNET MY_IP RPC_PORT

    seq 1 254 | xargs -P 80 -I {} bash -c '
        ip="$SUBNET.{}"
        timeout 0.3 bash -c "echo > /dev/tcp/$ip/$RPC_PORT" 2>/dev/null && echo "$ip"
        exit 0
    ' 2>/dev/null > "$tmp" || true

    RPC_NODES=()
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        RPC_NODES+=("$ip")
    done < "$tmp"
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
            [ "$node" = "$MY_IP" ] && label=" ${DIM}(este PC)${NC}"
            echo -e "  ${GREEN}●${NC} $node:$RPC_PORT$label"
        done
        echo ""
        echo -e "  Total: ${BOLD}${#RPC_NODES[@]}${NC} nodos"

        # Generar argumento --rpc
        local rpc_str=""
        for node in "${RPC_NODES[@]}"; do
            [ -n "$rpc_str" ] && rpc_str="$rpc_str,"
            rpc_str="$rpc_str$node:$RPC_PORT"
        done
        echo ""
        echo -e "  Usa: ${CYAN}--rpc $rpc_str${NC}"
    fi
    echo ""
}

# ====================== SERVER ======================

cmd_server() {
    check_bins
    detect_network
    select_model

    # Arrancar worker local primero
    if ! adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT"; then
        info "Iniciando worker local..."
        nohup "$BIN_DIR/rpc-server" -H 0.0.0.0 -p "$RPC_PORT" -t "$THREADS" \
            </dev/null >"$LOG_RPC" 2>&1 &
        echo $! > "$PID_RPC"
        sleep 2
        is_alive "$PID_RPC" && ok "Worker local OK" || warn "Worker local falló"
    fi

    # Escanear red
    info "Escaneando nodos..."
    scan_nodes

    if [ ${#RPC_NODES[@]} -eq 0 ]; then
        warn "No se encontraron nodos RPC. Usando solo CPU local."
        RPC_NODES=("$MY_IP")
    fi

    echo ""
    echo -e "  Nodos: ${BOLD}${#RPC_NODES[@]}${NC}"
    for n in "${RPC_NODES[@]}"; do
        local label=""
        [ "$n" = "$MY_IP" ] && label=" (local)"
        echo -e "    ${GREEN}●${NC} $n:$RPC_PORT$label"
    done

    # Construir string RPC
    local rpc_str=""
    for node in "${RPC_NODES[@]}"; do
        [ -n "$rpc_str" ] && rpc_str="$rpc_str,"
        rpc_str="$rpc_str$node:$RPC_PORT"
    done

    # Verificar si ya corre con misma config
    local prev
    prev=$(cat "$ARGS_FILE" 2>/dev/null) || true
    if [ "$prev" = "$rpc_str" ] && is_alive "$PID_LLAMA"; then
        ok "llama-server ya corre con esta configuración"
        echo -e "  API: ${BOLD}http://$MY_IP:$LLAMA_PORT${NC}"
        return 0
    fi

    # Detener anterior
    if is_alive "$PID_LLAMA"; then
        kill "$(cat "$PID_LLAMA")" 2>/dev/null
        sleep 1
    fi

    header "INICIANDO LLAMA-SERVER"
    echo -e "  Modelo: ${BOLD}$(basename "$SELECTED_MODEL")${NC}"
    echo -e "  RPC:    $rpc_str"
    echo -e "  API:    ${BOLD}http://$MY_IP:$LLAMA_PORT${NC}"
    echo ""

    if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--foreground" ]; then
        exec "$BIN_DIR/llama-server" \
            -m "$SELECTED_MODEL" \
            --rpc "$rpc_str" \
            --host 0.0.0.0 --port "$LLAMA_PORT" \
            --ctx-size "$CTX_SIZE" --batch-size "$BATCH_SIZE" \
            --threads "$THREADS" -fa on --cont-batching
    else
        nohup "$BIN_DIR/llama-server" \
            -m "$SELECTED_MODEL" \
            --rpc "$rpc_str" \
            --host 0.0.0.0 --port "$LLAMA_PORT" \
            --ctx-size "$CTX_SIZE" --batch-size "$BATCH_SIZE" \
            --threads "$THREADS" -fa on --cont-batching \
            </dev/null >"$LOG_LLAMA" 2>&1 &
        echo $! > "$PID_LLAMA"
        echo "$rpc_str" > "$ARGS_FILE"

        info "Esperando que cargue el modelo..."
        local tries=0
        while [ $tries -lt 60 ]; do
            if curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then
                ok "llama-server listo"
                echo -e "  API: ${GREEN}http://$MY_IP:$LLAMA_PORT${NC}"
                echo -e "  Log: ${DIM}$LOG_LLAMA${NC}"
                return 0
            fi
            if ! is_alive "$PID_LLAMA"; then
                err "llama-server se detuvo:"
                tail -10 "$LOG_LLAMA" 2>/dev/null | sed 's/^/  /'
                return 1
            fi
            sleep 2
            tries=$((tries+1))
            echo -ne "\r  Cargando... ${tries}s"
        done
        echo ""
        warn "Timeout (modelo muy grande?). Revisa: tail -f $LOG_LLAMA"
    fi
}

# ====================== STATUS ======================

cmd_status() {
    detect_network

    # Adoptar huérfanos
    adopt_orphan "rpc-server" "$PID_RPC" "rpc-server.*-p $RPC_PORT" 2>/dev/null || true
    adopt_orphan "llama-server" "$PID_LLAMA" "llama-server.*--port $LLAMA_PORT" 2>/dev/null || true

    header "ESTADO"
    echo -e "  PC:   $(hostname) — ${BOLD}$MY_IP${NC} ($ETH_IFACE)"
    echo ""

    echo -n "  rpc-server:   "
    if is_alive "$PID_RPC"; then
        echo -e "${GREEN}ACTIVO${NC} (PID $(cat "$PID_RPC"))"
    else
        echo -e "${RED}DETENIDO${NC}"
    fi

    echo -n "  llama-server: "
    if is_alive "$PID_LLAMA"; then
        echo -e "${GREEN}ACTIVO${NC} (PID $(cat "$PID_LLAMA"))"
        echo -e "  API:          http://$MY_IP:$LLAMA_PORT"
        echo -n "  Health:       "
        curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1 && \
            echo -e "${GREEN}OK${NC}" || echo -e "${YELLOW}cargando...${NC}"
    else
        echo -e "${RED}DETENIDO${NC}"
    fi

    echo ""
    info "Escaneando red..."
    scan_nodes
    echo -e "  Nodos RPC: ${BOLD}${#RPC_NODES[@]}${NC}"
    for n in "${RPC_NODES[@]}"; do
        local label=""
        [ "$n" = "$MY_IP" ] && label=" (este PC)"
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
        kill "$(cat "$PID_LLAMA")" 2>/dev/null
        ok "llama-server detenido"
    fi
    if is_alive "$PID_RPC"; then
        kill "$(cat "$PID_RPC")" 2>/dev/null
        ok "rpc-server detenido"
    fi
    rm -f "$PID_RPC" "$PID_LLAMA" "$ARGS_FILE"
    ok "Limpio"
}

# ====================== FIX-IP ======================

cmd_fix_ip() {
    detect_network
    local target_ip="${1:-}"

    header "CONFIGURAR IP ESTÁTICA"

    # Detectar interfaz ethernet
    local iface=""
    for i in $(ls /sys/class/net/ 2>/dev/null); do
        case "$i" in lo|wl*|veth*|br*|docker*|virbr*) continue ;; esac
        iface="$i"
        break
    done

    if [ -z "$iface" ]; then
        err "No se detectó interfaz ethernet"
        exit 1
    fi

    echo "  Interfaz: $iface"
    echo "  IP actual: $(ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[\d.]+' || echo 'ninguna')"

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
    new_ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[\d.]+')
    if [ "$new_ip" = "$target_ip" ]; then
        ok "IP configurada: $new_ip"

        # Guardar en cluster.conf
        echo "CLUSTER_SUBNET=\"$subnet\"" > "$CONF_FILE"
        ok "Subred guardada en cluster.conf"
    else
        err "No se pudo asignar la IP"
    fi
}

# ====================== DIAG ======================

cmd_diag() {
    detect_network
    header "DIAGNÓSTICO"

    echo "  Hostname:  $(hostname)"
    echo "  IP:        $MY_IP"
    echo "  Interfaz:  $ETH_IFACE"
    echo "  Subred:    $SUBNET.0/24"
    echo "  OS:        $(uname -sr)"
    echo "  CPU:       $(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs)"
    echo "  RAM:       $(free -h 2>/dev/null | awk '/Mem:/{print $2 " total, " $7 " libre"}' || echo "?")"
    echo "  Cores:     $(nproc)"
    echo ""

    # Binarios
    echo -n "  rpc-server:   "
    [ -x "$BIN_DIR/rpc-server" ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALTA${NC} (ejecuta ./cluster.sh setup)"

    echo -n "  llama-server: "
    [ -x "$BIN_DIR/llama-server" ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALTA${NC}"

    # Cable ethernet
    for iface in $(ls /sys/class/net/ 2>/dev/null); do
        case "$iface" in lo|wl*|veth*|br*|docker*|virbr*) continue ;; esac
        echo -n "  $iface:  "
        ip link show "$iface" 2>/dev/null | grep -q "state UP" && \
            echo -e "${GREEN}UP${NC}" || echo -e "${RED}DOWN${NC}"
    done

    # Puerto local
    echo -n "  Puerto $RPC_PORT: "
    timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/$RPC_PORT" 2>/dev/null && \
        echo -e "${GREEN}ABIERTO${NC}" || echo -e "${DIM}cerrado${NC}"

    # Hosts en red
    echo ""
    info "Hosts en $SUBNET.0/24..."
    local tmp
    tmp=$(mktemp)
    for i in $(seq 1 254); do
        ( ping -c1 -W 0.3 "$SUBNET.$i" &>/dev/null && echo "$SUBNET.$i" ) >> "$tmp" &
    done
    wait
    local count=0
    sort -t. -k4 -n "$tmp" | while IFS= read -r ip; do
        local label=""
        [ "$ip" = "$MY_IP" ] && label=" (este PC)"
        echo -e "  ${GREEN}●${NC} $ip$label"
        count=$((count+1))
    done
    echo "  Total: $(wc -l < "$tmp") hosts"
    rm -f "$tmp"

    # RPC servers
    echo ""
    info "RPC servers..."
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
        return 1
    fi
    echo -e "${GREEN}OK${NC}"

    info "Enviando prompt..."
    local resp
    resp=$(timeout 30 curl -sf "http://127.0.0.1:$LLAMA_PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{"messages":[{"role":"user","content":"Di hola en una palabra"}],"max_tokens":10}' 2>/dev/null) || true

    if [ -n "$resp" ]; then
        local content
        content=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null) || true
        if [ -n "$content" ]; then
            ok "Respuesta: $content"
        else
            warn "Respuesta recibida pero no parseable"
            echo "  $resp" | head -c 200
        fi
    else
        err "Sin respuesta (timeout o error)"
    fi
}

# ====================== HELP ======================

cmd_help() {
    echo ""
    echo -e "${BOLD}LLAMA.CPP RPC CLUSTER${NC}"
    echo ""
    echo "  Uso: ./cluster.sh <comando> [opciones]"
    echo ""
    echo -e "  ${BOLD}Comandos:${NC}"
    echo "    setup              Clonar y compilar llama.cpp"
    echo "    worker [-d]        Iniciar como worker RPC (-d = daemon)"
    echo "    server [-f]        Iniciar como servidor maestro (-f = foreground)"
    echo "    status             Ver estado del cluster"
    echo "    scan               Escanear nodos en la red"
    echo "    stop               Detener todos los servicios"
    echo "    test               Probar inferencia"
    echo "    fix-ip [IP]        Asignar IP estática a ethernet"
    echo "    diag               Diagnóstico completo"
    echo ""
    echo -e "  ${BOLD}Flujo típico:${NC}"
    echo "    1. En TODAS las PCs:    ./cluster.sh setup"
    echo "    2. En workers:          ./cluster.sh worker"
    echo "    3. En el maestro:       ./cluster.sh server"
    echo ""
    echo -e "  ${BOLD}Archivos:${NC}"
    echo "    models/     ← Pon aquí los archivos .gguf"
    echo "    bin/        ← Binarios compilados (auto)"
    echo "    cluster.conf← Config opcional (auto)"
    echo ""
}

# ====================== MAIN ======================

case "${1:-help}" in
    setup)      source "$SCRIPT_DIR/setup.sh" ;;
    worker|w)   cmd_worker "${2:-}" ;;
    server|s)   cmd_server "${2:-}" ;;
    status|st)  cmd_status ;;
    scan)       cmd_scan ;;
    stop)       cmd_stop ;;
    test|t)     cmd_test ;;
    fix-ip)     cmd_fix_ip "${2:-}" ;;
    diag|d)     cmd_diag ;;
    help|--help|-h|*) cmd_help ;;
esac
