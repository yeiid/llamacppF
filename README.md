# LLAMA.CPP RPC CLUSTER (Linux & Android Termux)
# Cluster de inferencia distribuida con llama.cpp

Sistema autocontenido para crear y administrar un cluster de inferencia distribuida con `llama.cpp` usando el protocolo RPC sobre LAN / Wi-Fi / USB Tethering, compatible tanto con **PCs Linux (x86_64 / ARM64)** como con **Android Termux** sin root.

---

## 📱 Guía Rápida en Android (Termux)

```bash
# 1. Instalar paquetes básicos en Termux (setup.sh también los instala automáticamente)
pkg update -y && pkg install -y git cmake clang make python curl procps iproute2 libomp

# 2. Compilar e instalar binarios (ajusta los hilos automáticamente según tu RAM para evitar OOM)
chmod +x cluster.sh setup.sh dashboard.sh
./cluster.sh setup

# 3. Descargar un modelo ligero recomendado para móvil (ej: SmolLM2 360M o Qwen2.5 Coder 0.5B)
./cluster.sh download qwen2.5-coder-0.5b

# 4. Opción A: Ejecutar el modelo directamente en terminal
./cluster.sh run "Escribe un hola mundo en Python"

# 4. Opción B: Iniciar servidor + Chat interactivo o Dashboard Web
./cluster.sh chat
# o abrir el panel web en http://localhost:9000:
./dashboard.sh start
```

---

## 💻 Guía Rápida en PC Linux / Cluster LAN

```bash
# 1. Setup (clonar + compilar llama.cpp con soporte RPC)
chmod +x cluster.sh setup.sh dashboard.sh
./cluster.sh setup

# 2. Descargar un modelo GGUF desde el catálogo interactivo
./cluster.sh download

# 3. En las PCs o celulares que actuarán como Workers RPC:
./cluster.sh worker -d

# 4. En el nodo Maestro (PC o Termux):
./cluster.sh server
```
> **Nota importante de rendimiento:** Cuando `server` no detecta workers remotos en la red, ejecuta `llama-server` en **Modo Local Directo** (sin pasarse a sí mismo por `--rpc`), ahorrando el 50% de RAM y evitando la serialización TCP redundante. Cuando detecta otros dispositivos con `rpc-server` activo en la red, distribuye las capas automáticamente entre ellos.

---

## Herramientas Incluidas

### 1. CLI Principal (`./cluster.sh`)

| Comando | Descripción |
|---------|-------------|
| `./cluster.sh setup` | Clona y compila `llama.cpp` (`ggml-rpc-server`, `llama-server`, `llama-cli`, `llama-bench`) |
| `./cluster.sh download [ID\|URL]` | Abre el catálogo interactivo de modelos GGUF o descarga directamente por ID/URL |
| `./cluster.sh server [-f]` | Inicia el servidor maestro (distribuido por RPC si hay workers remotos, o local directo) |
| `./cluster.sh chat` | Inicia el servidor (si no está activo) y abre el chat interactivo en consola |
| `./cluster.sh run [prompt]` | Corre un modelo directamente con `llama-cli` sin levantar servidor HTTP |
| `./cluster.sh worker [-d]` | Inicia este dispositivo como nodo worker RPC (`-d` para segundo plano) |
| `./cluster.sh status` | Estado de los procesos del cluster y nodos RPC en la red |
| `./cluster.sh scan` | Escanea la subred LAN / Wi-Fi buscando workers RPC activos |
| `./cluster.sh stop` | Detiene todos los servicios locales del cluster y libera `termux-wake-lock` |
| `./cluster.sh diag` | Diagnóstico completo de hardware, red, binarios y puertos |
| `./cluster.sh test` | Prueba rápida de inferencia contra el servidor activo |

### 2. Dashboard Web (`./dashboard.sh start` -> `http://localhost:9000`)
- **Control del Cluster:** Inicia/detiene `llama-server` (Maestro) y `rpc-server` (Worker local), escanea nodos RPC en segundo plano mostrando su latencia en `ms`.
- **Gestor de Modelos GGUF:** Catálogo integrado con modelos desde `380 MB` (especiales para Termux) hasta `32B` (para clusters), descarga directa por URL `.gguf` con barra de progreso y cancelación.
- **Playground de Chat:** Streaming SSE con proxy integrado (`/api/chat`), botón para detener generación, perfiles de sistema y resaltado de código.
- **Monitoreo y Benchmark:** Gráficas en tiempo real de CPU, RAM, temperaturas, red, I/O de disco y prueba de velocidad (Tokens/s y TTFT).

### 3. CLI Python (`python3 cluster-cli.py`)

```bash
python3 cluster-cli.py status              # Estado detallado con latencia por nodo RPC
python3 cluster-cli.py list                # Lista de modelos .gguf descargados
python3 cluster-cli.py download [ID|URL]   # Descarga interactiva o directa de modelos .gguf
python3 cluster-cli.py chat                # Playground de chat interactivo en terminal
python3 cluster-cli.py benchmark           # Benchmark de velocidad (Tokens/s y TTFT)
```
