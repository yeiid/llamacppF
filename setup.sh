#!/usr/bin/env bash
# ============================================================
#  LLAMA.CPP RPC CLUSTER — SETUP AUTOMÁTICO (Linux & Termux)
#  Clona, compila e instala llama.cpp con soporte RPC
#
#  Uso: ./setup.sh
#  Compatible con: Linux (x86_64, ARM64) y Android Termux
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LLAMA_DIR="$SCRIPT_DIR/llama.cpp"
BUILD_DIR="$LLAMA_DIR/build"
BIN_DIR="$SCRIPT_DIR/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }

header() {
    echo ""
    echo -e "${CYAN}${BOLD}══════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}══════════════════════════════════════════════${NC}"
    echo ""
}

# Detectar entorno Termux / Android
IS_TERMUX="false"
if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]] || [ -d "/data/data/com.termux" ]; then
    IS_TERMUX="true"
fi

# ====================== VERIFICAR DEPENDENCIAS ======================
check_deps() {
    header "1/4 — VERIFICANDO DEPENDENCIAS"

    if [ "$IS_TERMUX" = "true" ]; then
        info "Entorno Android Termux detectado."
        command -v termux-wake-lock &>/dev/null && termux-wake-lock 2>/dev/null || true
    fi

    local missing=()

    for cmd in git cmake make python3 curl; do
        if command -v "$cmd" &>/dev/null; then
            ok "$cmd: $(command -v "$cmd")"
        else
            err "$cmd: NO ENCONTRADO"
            missing+=("$cmd")
        fi
    done

    # Verificar compilador C/C++ (clang/clang++ en Termux o gcc/g++ en Linux)
    if command -v clang &>/dev/null && command -v clang++ &>/dev/null; then
        ok "Compilador C/C++: clang / clang++ ($(command -v clang++))"
    elif command -v gcc &>/dev/null && command -v g++ &>/dev/null; then
        ok "Compilador C/C++: gcc / g++ ($(command -v g++))"
    else
        err "Compilador C/C++ (clang++ o g++): NO ENCONTRADO"
        missing+=("compiler")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        warn "Faltan dependencias: ${missing[*]}"
        if [ "$IS_TERMUX" = "true" ] && command -v pkg &>/dev/null; then
            info "Instalando dependencias automáticamente en Termux..."
            pkg update -y
            pkg install -y git cmake clang make python curl procps iproute2 libomp
            ok "Paquetes de Termux instalados"
        else
            echo ""
            echo "  Instala con:"
            echo "    Termux:        pkg install git cmake clang make python curl procps iproute2 libomp"
            echo "    Ubuntu/Debian: sudo apt update && sudo apt install -y git cmake build-essential python3 curl"
            echo "    Fedora:        sudo dnf install -y git cmake gcc-c++ make python3 curl"
            echo "    Arch:          sudo pacman -S --needed git cmake base-devel python curl"
            exit 1
        fi
    fi
    ok "Todas las dependencias OK"
}

# ====================== CLONAR LLAMA.CPP ======================
clone_llama() {
    header "2/4 — CLONANDO LLAMA.CPP"

    if [ -d "$LLAMA_DIR/.git" ]; then
        info "llama.cpp ya clonado, actualizando..."
        cd "$LLAMA_DIR"
        git pull --ff-only 2>/dev/null || warn "No se pudo actualizar (usando versión local)"
        cd "$SCRIPT_DIR"
    else
        info "Clonando llama.cpp (última versión)..."
        rm -rf "$LLAMA_DIR"
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
    fi
    ok "Código fuente listo"
}

# ====================== COMPILAR ======================
compile_llama() {
    header "3/4 — COMPILANDO CON SOPORTE RPC"

    local nprocs mem_gb max_jobs_by_ram
    nprocs=$(nproc 2>/dev/null || echo 2)
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 4)
    [ "$mem_gb" -lt 1 ] && mem_gb=2

    # Evitar que Android LMK (Low Memory Killer) mate a clang++ por falta de RAM en celulares
    if [ "$IS_TERMUX" = "true" ] || [ "$mem_gb" -le 6 ]; then
        max_jobs_by_ram=$(( mem_gb / 2 ))
        [ "$max_jobs_by_ram" -lt 1 ] && max_jobs_by_ram=1
        [ "$max_jobs_by_ram" -gt 4 ] && max_jobs_by_ram=4
        if [ "$nprocs" -gt "$max_jobs_by_ram" ]; then
            info "Ajustando hilos de compilación a $max_jobs_by_ram (RAM: ~${mem_gb}GB) para evitar OOM"
            nprocs="$max_jobs_by_ram"
        fi
    fi

    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    local cmake_extra_flags=()
    if [ "$IS_TERMUX" = "true" ]; then
        # En Termux usar clang explícitamente y desactivar enlaces problemáticos si faltan
        cmake_extra_flags+=(
            "-DCMAKE_C_COMPILER=clang"
            "-DCMAKE_CXX_COMPILER=clang++"
        )
    fi

    info "Configurando cmake (RPC=ON)..."
    cmake .. \
        -DGGML_RPC=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_SERVER=ON \
        "${cmake_extra_flags[@]}" \
        2>&1 | tail -8

    echo ""
    info "Compilando con $nprocs hilos..."
    cmake --build . --config Release -j "$nprocs" --target ggml-rpc-server llama-server llama-cli llama-bench 2>&1 | tail -12 || \
        cmake --build . --config Release -j "$nprocs" 2>&1 | tail -12

    cd "$SCRIPT_DIR"
    ok "Compilación completada"
}

# ====================== INSTALAR BINARIOS ======================
install_bins() {
    header "4/4 — INSTALANDO BINARIOS"

    mkdir -p "$BIN_DIR"

    # Detectar binario RPC (ggml-rpc-server en versiones nuevas, rpc-server en anteriores)
    if [ -f "$BUILD_DIR/bin/ggml-rpc-server" ]; then
        cp "$BUILD_DIR/bin/ggml-rpc-server" "$BIN_DIR/rpc-server"
        cp "$BUILD_DIR/bin/ggml-rpc-server" "$BIN_DIR/ggml-rpc-server"
        ok "ggml-rpc-server -> rpc-server copiado"
    elif [ -f "$BUILD_DIR/bin/rpc-server" ]; then
        cp "$BUILD_DIR/bin/rpc-server" "$BIN_DIR/rpc-server"
        ok "rpc-server copiado"
    else
        warn "rpc-server / ggml-rpc-server no encontrado en build"
    fi

    # Copiar todos los binarios y herramientas llama-* compilados
    local tool_count=0
    for src in "$BUILD_DIR"/bin/llama-*; do
        if [ -f "$src" ] && [ -x "$src" ]; then
            cp -f "$src" "$BIN_DIR/" 2>/dev/null || true
            tool_count=$((tool_count + 1))
        fi
    done
    ok "$tool_count herramientas llama-* copiadas a bin/"

    # Copiar librerías compartidas (.so)
    for lib in "$BUILD_DIR"/bin/lib*.so* "$BUILD_DIR"/src/lib*.so* "$BUILD_DIR"/ggml/src/lib*.so*; do
        [ -e "$lib" ] && cp -P "$lib" "$BIN_DIR/" 2>/dev/null || true
    done
    ok "Librerías compartidas copiadas"

    # Verificar que los binarios críticos existen
    if [ ! -f "$BIN_DIR/rpc-server" ] || [ ! -f "$BIN_DIR/llama-server" ]; then
        err "Binarios críticos faltantes. Revisa la compilación."
        exit 1
    fi

    chmod +x "$BIN_DIR"/* 2>/dev/null || true

    # Test rápido
    export LD_LIBRARY_PATH="$BIN_DIR:${PREFIX:+$PREFIX/lib:}${LD_LIBRARY_PATH:-}"
    if "$BIN_DIR/rpc-server" --help &>/dev/null; then
        ok "rpc-server verificado y funcional"
    else
        warn "rpc-server puede necesitar librerías adicionales en LD_LIBRARY_PATH"
    fi

    echo ""
    ok "Instalación completa. Binarios en: $BIN_DIR/"
    echo ""
    echo -e "  ${BOLD}Siguientes pasos:${NC}"
    echo -e "    Descargar modelo: ${GREEN}./cluster.sh download${NC}"
    echo -e "    Iniciar servidor: ${GREEN}./cluster.sh server${NC}"
    echo -e "    Chatear:          ${GREEN}./cluster.sh chat${NC}"
    echo -e "    Modo Worker RPC:  ${GREEN}./cluster.sh worker${NC}"
    echo -e "    Dashboard Web:    ${GREEN}./dashboard.sh start${NC}"
    echo ""
}

# ====================== MAIN ======================
header "LLAMA.CPP RPC CLUSTER — SETUP"
echo "  Directorio:   $SCRIPT_DIR"
echo "  Arquitectura: $(uname -m)"
echo "  Sistema:      $(uname -s) (Termux: $IS_TERMUX)"
echo ""

check_deps
clone_llama
compile_llama
install_bins
