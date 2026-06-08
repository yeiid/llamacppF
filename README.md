# LLAMA.CPP RPC CLUSTER
# Cluster de inferencia distribuida con llama.cpp

Sistema autocontenido para crear un cluster de inferencia con llama.cpp
usando el protocolo RPC sobre LAN.

## Inicio Rápido

```bash
# 1. Setup (clonar + compilar llama.cpp)
chmod +x cluster.sh setup.sh
./cluster.sh setup

# 2. Poner modelos .gguf en la carpeta models/

# 3. En PCs worker:
./cluster.sh worker

# 4. En la PC maestro:
./cluster.sh server
```

## Comandos

| Comando | Descripción |
|---------|-------------|
| `./cluster.sh setup` | Clona y compila llama.cpp con RPC |
| `./cluster.sh worker` | Inicia como worker (ofrece CPU) |
| `./cluster.sh server` | Inicia como maestro (carga modelo) |
| `./cluster.sh status` | Estado del cluster |
| `./cluster.sh scan` | Busca nodos en la red |
| `./cluster.sh stop` | Detiene todo |
| `./cluster.sh fix-ip 192.168.194.X` | Configura IP estática |
| `./cluster.sh diag` | Diagnóstico completo |
| `./cluster.sh test` | Prueba inferencia |

## Estructura

```
llamacppF/
├── cluster.sh      ← Script principal
├── setup.sh        ← Clona y compila
├── models/         ← Modelos .gguf aquí
├── bin/            ← Binarios (generado por setup)
├── llama.cpp/      ← Código fuente (generado por setup)
├── cluster.conf    ← Config (auto-generado)
└── .state/         ← PIDs y logs
```

## Requisitos

- Linux (x86_64 o ARM)
- git, cmake, gcc/g++, make
- Conexión LAN entre las PCs
