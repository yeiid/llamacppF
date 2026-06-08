#!/bin/bash
# ============================================================
#  LLAMA.CPP RPC CLUSTER — SETUP AUTOMÁTICO
#  Clona, compila e instala llama.cpp con soporte RPC
#
#  Uso: ./setup.sh
#  Requisitos: git, cmake, gcc/g++, make
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

# ====================== VERIFICAR DEPENDENCIAS ======================
check_deps() {
    header "1/4 — VERIFICANDO DEPENDENCIAS"
    local missing=()

    for cmd in git cmake gcc g++ make; do
        if command -v "$cmd" &>/dev/null; then
            ok "$cmd: $(command -v "$cmd")"
        else
            err "$cmd: NO ENCONTRADO"
            missing+=("$cmd")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        err "Faltan dependencias: ${missing[*]}"
        echo ""
        echo "  Instala con:"
        echo "    Ubuntu/Debian: sudo apt install git cmake build-essential"
        echo "    Fedora:        sudo dnf install git cmake gcc-c++ make"
        echo "    Arch:          sudo pacman -S git cmake base-devel"
        exit 1
    fi
    ok "Todas las dependencias OK"
}

# ====================== CLONAR LLAMA.CPP ======================
clone_llama() {
    header "2/4 — CLONANDO LLAMA.CPP"

    if [ -d "$LLAMA_DIR/.git" ]; then
        info "llama.cpp ya clonado, actualizando..."
        cd "$LLAMA_DIR"
        git pull --ff-only 2>/dev/null || warn "No se pudo actualizar (sin conexión?)"
        cd "$SCRIPT_DIR"
    else
        info "Clonando llama.cpp (solo la última versión)..."
        rm -rf "$LLAMA_DIR"
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
    fi
    ok "Código fuente listo"
}

# ====================== COMPILAR ======================
compile_llama() {
    header "3/4 — COMPILANDO CON SOPORTE RPC"

    local nprocs
    nprocs=$(nproc 2>/dev/null || echo 2)

    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    info "Configurando cmake (RPC=ON)..."
    cmake .. \
        -DGGML_RPC=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=ON \
        -DLLAMA_BUILD_SERVER=ON \
        2>&1 | tail -5

    echo ""
    info "Compilando con $nprocs hilos (esto tarda 2-5 min)..."
    cmake --build . --config Release -j "$nprocs" 2>&1 | tail -10

    cd "$SCRIPT_DIR"
    ok "Compilación completada"
}

# ====================== INSTALAR BINARIOS ======================
install_bins() {
    header "4/4 — INSTALANDO BINARIOS"

    mkdir -p "$BIN_DIR"

    # Copiar binarios principales
    local bins_found=0
    for bin in rpc-server llama-server llama-cli; do
        local src="$BUILD_DIR/bin/$bin"
        if [ -f "$src" ]; then
            cp "$src" "$BIN_DIR/"
            ok "$bin copiado"
            bins_found=$((bins_found + 1))
        else
            warn "$bin no encontrado en build"
        fi
    done

    # Copiar librerías compartidas
    for lib in "$BUILD_DIR"/bin/lib*.so*; do
        [ -f "$lib" ] && cp -P "$lib" "$BIN_DIR/" 2>/dev/null
    done
    ok "Librerías copiadas"

    # Verificar que los binarios críticos existen
    if [ ! -f "$BIN_DIR/rpc-server" ] || [ ! -f "$BIN_DIR/llama-server" ]; then
        err "Binarios críticos faltantes. Revisa la compilación."
        exit 1
    fi

    # Test rápido
    export LD_LIBRARY_PATH="$BIN_DIR:${LD_LIBRARY_PATH:-}"
    if "$BIN_DIR/rpc-server" --help &>/dev/null; then
        ok "rpc-server funcional"
    else
        warn "rpc-server puede necesitar librerías adicionales"
    fi

    chmod +x "$BIN_DIR"/*

    echo ""
    ok "Instalación completa. Binarios en: $BIN_DIR/"
    echo ""
    echo -e "  ${BOLD}Siguiente paso:${NC}"
    echo -e "    Worker:  ${GREEN}./cluster.sh worker${NC}"
    echo -e "    Server:  ${GREEN}./cluster.sh server${NC}"
    echo -e "    Status:  ${GREEN}./cluster.sh status${NC}"
    echo ""
}

# ====================== MAIN ======================
header "LLAMA.CPP RPC CLUSTER — SETUP"
echo "  Directorio: $SCRIPT_DIR"
echo "  Arquitectura: $(uname -m)"
echo "  OS: $(uname -s)"
echo ""

check_deps
clone_llama
compile_llama
install_bins
