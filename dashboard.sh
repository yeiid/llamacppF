#!/usr/bin/env bash
# ============================================================
#  LAUNCHER SCRIPT FOR LLAMA.CPP CLUSTER DASHBOARD
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.state/dashboard.pid"
LOG_FILE="$SCRIPT_DIR/.state/dashboard.log"
PORT=9000

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info() { echo -e "${CYAN}ℹ${NC} $1"; }
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }

is_running() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

cmd_start() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        warn "El Dashboard ya está corriendo (PID $pid)"
        echo -e "  Accede en: ${BOLD}http://localhost:$PORT${NC}"
        return 0
    fi

    mkdir -p "$(dirname "$PID_FILE")"
    
    info "Iniciando Dashboard Suite en puerto $PORT..."
    command -v termux-wake-lock &>/dev/null && termux-wake-lock 2>/dev/null || true
    nohup python3 "$SCRIPT_DIR/dashboard.py" </dev/null > "$LOG_FILE" 2>&1 &
    0echo $! > "$PID_FILE"
    
    sleep 1.5
    if is_running; then
        local my_ip
        my_ip=$(python3 -c "import cluster_core; print(cluster_core.get_local_ip_and_subnet()[0])" 2>/dev/null) || my_ip="127.0.0.1"
        ok "Dashboard iniciado con éxito!"
        echo ""
        echo -e "  ${BOLD}URL Local:${NC}   ${GREEN}http://localhost:$PORT${NC}"
        echo -e "  ${BOLD}URL Red LAN:${NC} ${GREEN}http://$my_ip:$PORT${NC}"
        echo -e "  ${BOLD}Log:${NC}         $LOG_FILE"
        echo ""
        echo "  Usa './dashboard.sh stop' para apagarlo."
    else
        err "No se pudo iniciar el Dashboard. Revisa el log:"
        tail -n 10 "$LOG_FILE"
    fi
}

cmd_stop() {
    if ! is_running; then
        warn "El Dashboard no está activo."
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    info "Deteniendo Dashboard (PID $pid)..."
    kill "$pid" 2>/dev/null
    
    # Detener también los servicios de llama.cpp si el usuario lo desea
    if [ -x "$SCRIPT_DIR/cluster.sh" ]; then
        info "Deteniendo servicios asociados del cluster..."
        "$SCRIPT_DIR/cluster.sh" stop >/dev/null 2>&1
    fi
    
    rm -f "$PID_FILE"
    ok "Dashboard detenido."
}

cmd_status() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        ok "Dashboard está ${GREEN}ACTIVO${NC} (PID $pid)"
        echo -e "  URL: ${BOLD}http://localhost:$PORT${NC}"
    else
        warn "Dashboard está ${RED}DETENIDO${NC}"
    fi
}

cmd_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -n 50 -f "$LOG_FILE"
    else
        err "No hay archivo de log disponible."
    fi
}

cmd_help() {
    echo ""
    echo -e "${BOLD}LLAMA.CPP CLUSTER DASHBOARD LAUNCHER${NC}"
    echo ""
    echo "  Uso: ./dashboard.sh <comando>"
    echo ""
    echo -e "  ${BOLD}Comandos:${NC}"
    echo "    start      Inicia el dashboard web en background"
    echo "    stop       Detiene el dashboard y limpia procesos"
    echo "    status     Muestra si el dashboard está activo"
    echo "    logs       Muestra los logs del backend en tiempo real"
    echo "    restart    Detiene y vuelve a iniciar"
    echo ""
}

case "${1:-help}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    restart) cmd_stop; sleep 1; cmd_start ;;
    help|--help|-h|*) cmd_help ;;
esac
