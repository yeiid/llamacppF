#!/usr/bin/env python3
"""
Módulo central compartido para LLAMA.CPP RPC CLUSTER (CLI, Bash y Dashboard Web).
Soporta Linux (x86_64/ARM64) y Android Termux sin root.
Centraliza configuración, detección de red (Ethernet, Wi-Fi, USB Tethering y UDP route),
escaneo de nodos RPC con medición de latencia, catálogo y descarga de modelos GGUF,
gestión de PIDs y sincronización con OpenCode.
"""
import os
import re
import sys
import json
import time
import socket
import shutil
import subprocess
import threading
import urllib.request
import concurrent.futures

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE_DIR, ".state")
MODEL_DIR = os.path.join(WORKSPACE_DIR, "models")
CONF_FILE = os.path.join(WORKSPACE_DIR, "cluster.conf")
OPENCODE_FILE = os.path.join(WORKSPACE_DIR, "opencode.json")

_config_lock = threading.Lock()


def ensure_dir(path):
    """Garantiza que un directorio existe incluso si es un symlink (ej. Google Drive montado en Colab)."""
    if os.path.islink(path):
        real = os.path.realpath(path)
        if not os.path.exists(real):
            try:
                os.makedirs(real, exist_ok=True)
                return
            except Exception:
                try:
                    os.unlink(path)
                except Exception:
                    pass
    os.makedirs(path, exist_ok=True)


def is_termux():
    """Detecta si estamos ejecutando dentro de Termux en Android."""
    if os.environ.get("TERMUX_VERSION"):
        return True
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix or os.path.isdir("/data/data/com.termux"):
        return True
    return False


def get_system_ram_gb():
    """Obtiene la RAM total del sistema en GB desde /proc/meminfo."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if "MemTotal" in line:
                    kb = int(line.split(":")[1].strip().split()[0])
                    return round(kb / (1024 * 1024), 1)
    except Exception:
        pass
    return 4.0


def get_optimal_threads():
    """
    Calcula el número óptimo de hilos para llama.cpp evitando Hyper-Threading (SMT)
    en x86 y núcleos de eficiencia (LITTLE) en ARM/Termux, lo cual evita contención
    de barreras y multiplica la velocidad de generación hasta por 18x.
    """
    # 1. En x86/Linux: contar pares únicos (physical id, core id) en /proc/cpuinfo
    try:
        if os.path.exists("/proc/cpuinfo"):
            phys_id = "0"
            cores = set()
            cpu_cores_field = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("physical id"):
                        phys_id = line.split(":", 1)[1].strip()
                    elif line.startswith("core id"):
                        core_id = line.split(":", 1)[1].strip()
                        cores.add((phys_id, core_id))
                    elif line.startswith("cpu cores") and cpu_cores_field is None:
                        try:
                            cpu_cores_field = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
            if len(cores) >= 1:
                return len(cores)
            if cpu_cores_field and cpu_cores_field >= 1:
                return cpu_cores_field
    except Exception:
        pass

    # 2. En ARM / Termux (big.LITTLE): contar solo núcleos de alto rendimiento por frecuencia máxima
    try:
        cpu_base = "/sys/devices/system/cpu"
        if os.path.isdir(cpu_base):
            freqs = []
            for entry in os.listdir(cpu_base):
                if re.match(r"^cpu\d+$", entry):
                    freq_file = os.path.join(cpu_base, entry, "cpufreq", "cpuinfo_max_freq")
                    if os.path.exists(freq_file):
                        with open(freq_file, "r", encoding="utf-8") as f:
                            freqs.append(int(f.read().strip()))
            if len(freqs) >= 4 and max(freqs) > min(freqs):
                min_f = min(freqs)
                perf_cores = sum(1 for f in freqs if f > min_f)
                if perf_cores >= 2:
                    return perf_cores
    except Exception:
        pass

    cpus = os.cpu_count() or 4
    if is_termux() and cpus >= 6:
        return cpus // 2
    return max(1, cpus // 2) if cpus >= 4 else cpus


DEFAULTS = {
    "THREADS": str(get_optimal_threads()),
    "CTX_SIZE": "2048" if (is_termux() or get_system_ram_gb() < 5.0) else "4096",
    "BATCH_SIZE": "512",
    "LLAMA_PORT": "8080",
    "RPC_PORT": "50052",
    "CLUSTER_SUBNET": "",
    "NGL": "auto",
    "KV_CACHE_TYPE": "f16",
    "RPC_CACHE": "true",
    "CUSTOM_NODES": "",
    "EXCLUDED_NODES": ""
}

# --- CATÁLOGO COMPARTIDO DE MODELOS GGUF ---
MODEL_CATALOG = [
    # --- ULTRA LIGEROS / TERMUX / MÓVIL (1-2 GB RAM) ---
    {
        "id": "smollm2-360m",
        "name": "SmolLM2 360M Instruct",
        "family": "SmolLM2",
        "url": "https://huggingface.co/bartowski/SmolLM2-360M-Instruct-GGUF/resolve/main/SmolLM2-360M-Instruct-Q8_0.gguf",
        "filename": "SmolLM2-360M-Instruct-Q8_0.gguf",
        "size_gb": 0.38,
        "ram_min_gb": 1,
        "description": "Ultra ligero (~380 MB). Ideal para pruebas rápidas, Termux en celulares y dispositivos con poca RAM.",
        "speed": "Instantáneo",
        "quality": "Básico",
        "ctx": 8192,
        "tags": ["general", "lightweight", "termux"]
    },
    {
        "id": "qwen2.5-coder-0.5b",
        "name": "Qwen2.5 Coder 0.5B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf",
        "size_gb": 0.4,
        "ram_min_gb": 1,
        "description": "Micro modelo de código y chat (~400 MB). Corre excelente en Termux y PCs de bajos recursos.",
        "speed": "Muy rápido",
        "quality": "Básico",
        "ctx": 32768,
        "tags": ["coding", "lightweight", "termux"]
    },
    {
        "id": "llama-3.2-1b",
        "name": "Llama 3.2 1B Instruct",
        "family": "Llama 3.2",
        "url": "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size_gb": 0.8,
        "ram_min_gb": 2,
        "description": "Meta Llama 3.2 1B optimizado para ARM/móviles y CPU. Muy fluido en Termux y laptops.",
        "speed": "Muy rápido",
        "quality": "Bueno",
        "ctx": 32768,
        "tags": ["general", "lightweight", "termux"]
    },
    {
        "id": "qwen2.5-coder-1.5b",
        "name": "Qwen2.5 Coder 1.5B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.0,
        "ram_min_gb": 2,
        "description": "Excelente equilibrio tamaño/calidad (1 GB) para código y conversación en Termux o PC.",
        "speed": "Rápido",
        "quality": "Bueno",
        "ctx": 32768,
        "tags": ["coding", "lightweight", "termux"]
    },
    {
        "id": "deepseek-coder-1.3b",
        "name": "DeepSeek Coder 1.3B Instruct",
        "family": "DeepSeek Coder",
        "url": "https://huggingface.co/TheBloke/deepseek-coder-1.3b-instruct-GGUF/resolve/main/deepseek-coder-1.3b-instruct.Q4_K_M.gguf",
        "filename": "deepseek-coder-1.3b-instruct.Q4_K_M.gguf",
        "size_gb": 0.9,
        "ram_min_gb": 2,
        "description": "DeepSeek Coder 1.3B ligero. Rápido en múltiples lenguajes de programación.",
        "speed": "Rápido",
        "quality": "Bueno",
        "ctx": 16384,
        "tags": ["coding", "lightweight", "termux"]
    },
    # --- MEDIANOS (3-6 GB RAM) ---
    {
        "id": "qwen2.5-coder-3b",
        "name": "Qwen2.5 Coder 3B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.9,
        "ram_min_gb": 3,
        "description": "Sweet spot para coding en 4-8GB RAM (Android gama media/alta o PC).",
        "speed": "Rápido",
        "quality": "Muy Bueno",
        "ctx": 32768,
        "tags": ["coding"]
    },
    {
        "id": "hermes-3-llama-3.2-3b",
        "name": "Hermes 3 Llama 3.2 3B (Agente / Tool Calling)",
        "family": "Nous Hermes 3",
        "url": "https://huggingface.co/NousResearch/Hermes-3-Llama-3.2-3B-GGUF/resolve/main/Hermes-3-Llama-3.2-3B.Q4_K_M.gguf",
        "filename": "Hermes-3-Llama-3.2-3B.Q4_K_M.gguf",
        "size_gb": 2.02,
        "ram_min_gb": 3,
        "description": "NousResearch Hermes 3 (3B). Especializado en agentes autónomos, llamada a herramientas (function calling), salidas JSON estructuradas y razonamiento sin censura.",
        "speed": "Rápido",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general", "coding", "termux"]
    },
    {
        "id": "llama-3.2-3b",
        "name": "Llama 3.2 3B Instruct",
        "family": "Llama 3.2",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 2.0,
        "ram_min_gb": 4,
        "description": "Meta Llama 3.2 3B. Gran capacidad de razonamiento y resumen en español/inglés.",
        "speed": "Rápido",
        "quality": "Muy Bueno",
        "ctx": 32768,
        "tags": ["general"]
    },
    {
        "id": "hermes-3-llama-3.1-8b",
        "name": "Hermes 3 Llama 3.1 8B (Agente Maestro)",
        "family": "Nous Hermes 3",
        "url": "https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B-GGUF/resolve/main/Hermes-3-Llama-3.1-8B.Q4_K_M.gguf",
        "filename": "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf",
        "size_gb": 4.92,
        "ram_min_gb": 7,
        "description": "NousResearch Hermes 3 (8B). El mejor modelo agente abierto para orquestar herramientas, OpenCode, JSON estricto y planificación multi-paso.",
        "speed": "Medio",
        "quality": "Premium",
        "ctx": 131072,
        "tags": ["general", "coding", "premium"]
    },
    {
        "id": "codegemma-2b",
        "name": "CodeGemma 2B IT",
        "family": "Gemma",
        "url": "https://huggingface.co/bartowski/google_codegemma-2b-GGUF/resolve/main/google_codegemma-2b-it-Q4_K_M.gguf",
        "filename": "google_codegemma-2b-it-Q4_K_M.gguf",
        "size_gb": 1.6,
        "ram_min_gb": 3,
        "description": "Google CodeGemma. Entrenado específicamente para código.",
        "speed": "Rápido",
        "quality": "Muy Bueno",
        "ctx": 8192,
        "tags": ["coding"]
    },
    {
        "id": "phi-3.5-mini",
        "name": "Phi-3.5 Mini Instruct (3.8B)",
        "family": "Phi",
        "url": "https://huggingface.co/bartowski/microsoft_Phi-3.5-mini-instruct-GGUF/resolve/main/microsoft_Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "filename": "microsoft_Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size_gb": 2.4,
        "ram_min_gb": 4,
        "description": "Microsoft Phi. Excelente razonamiento lógico y código para su tamaño.",
        "speed": "Rápido",
        "quality": "Muy Bueno",
        "ctx": 131072,
        "tags": ["general", "coding"]
    },
    {
        "id": "gemma-4-E4B-it",
        "name": "Gemma 4 4B IT",
        "family": "Gemma",
        "url": "https://huggingface.co/bartowski/google_gemma-4-4B-it-GGUF/resolve/main/google_gemma-4-4B-it-Q4_K_M.gguf",
        "filename": "gemma-4-E4B-it-Q4_K_M.gguf",
        "size_gb": 3.0,
        "ram_min_gb": 5,
        "description": "Google Gemma 4. Buen código y conversación general.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general"]
    },
    # --- GRANDES / CLUSTER (7B - 32B) ---
    {
        "id": "qwen2.5-coder-7b",
        "name": "Qwen2.5 Coder 7B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.7,
        "ram_min_gb": 7,
        "description": "El MEJOR 7B para código. Genera proyectos completos, debugging, tests.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["coding"]
    },
    {
        "id": "qwen2.5-7b-instruct",
        "name": "Qwen2.5 7B Instruct",
        "family": "Qwen 2.5",
        "url": "https://huggingface.co/unsloth/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.7,
        "ram_min_gb": 7,
        "description": "General purpose top tier. Muy bueno para conversación y código.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general"]
    },
    {
        "id": "llama-3.1-8b-instruct",
        "name": "Llama 3.1 8B Instruct",
        "family": "Llama",
        "url": "https://huggingface.co/bartowski/meta-llama_Llama-3.1-8B-Instruct-GGUF/resolve/main/meta-llama_Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "filename": "meta-llama_Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.9,
        "ram_min_gb": 7,
        "description": "El estándar de la industria. Versátil para todo.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general"]
    },
    {
        "id": "qwen2.5-coder-14b",
        "name": "Qwen2.5 Coder 14B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        "size_gb": 8.8,
        "ram_min_gb": 12,
        "description": "Coding de clase mundial. Ideal para distribuir entre 2+ nodos RPC.",
        "speed": "Lento",
        "quality": "Premium",
        "ctx": 131072,
        "tags": ["coding", "premium"]
    },
    {
        "id": "deepseek-coder-6.7b",
        "name": "DeepSeek Coder V2 16B Lite",
        "family": "DeepSeek Coder",
        "url": "https://huggingface.co/bartowski/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-GGUF/resolve/main/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "filename": "deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "size_gb": 9.8,
        "ram_min_gb": 12,
        "description": "DeepSeek V2 Lite. 16B params, arquitectura MoE. Rápido en cluster RPC.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["coding", "premium"]
    },
    {
        "id": "qwen2.5-coder-32b",
        "name": "Qwen2.5 Coder 32B Instruct",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        "size_gb": 18.0,
        "ram_min_gb": 24,
        "description": "Modelo 32B para clusters RPC de múltiples máquinas.",
        "speed": "Muy Lento",
        "quality": "Top",
        "ctx": 131072,
        "tags": ["coding", "premium"]
    }
]


def load_config():
    """Carga cluster.conf combinándolo con los valores por defecto."""
    config = DEFAULTS.copy()
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        config[k.strip()] = v
        except Exception as e:
            print(f"Error loading config: {e}")
    return config


def save_config(updates):
    """Guarda y fusiona actualizaciones en cluster.conf de forma atómica."""
    with _config_lock:
        current = load_config()
        current.update({k: str(v) for k, v in updates.items() if v is not None})
        try:
            tmp_file = CONF_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write("# Configuración del Cluster Llama.cpp (Auto-generado)\n")
                for k, v in current.items():
                    f.write(f'{k}="{v}"\n')
            os.replace(tmp_file, CONF_FILE)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False


def get_pid_status(pid_file, orphan_pattern=None):
    """Verifica si el proceso en pid_file está activo o adopta un huérfano si coincide."""
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True, pid
        except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
            pass

    if orphan_pattern and shutil.which("pgrep"):
        try:
            res = subprocess.run(
                ["pgrep", "-f", orphan_pattern],
                capture_output=True,
                text=True,
                timeout=1.0
            )
            if res.returncode == 0 and res.stdout.strip():
                my_pid = os.getpid()
                for line in res.stdout.strip().splitlines():
                    pid = int(line.strip())
                    if pid != my_pid:
                        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
                        with open(pid_file, "w", encoding="utf-8") as f:
                            f.write(str(pid))
                        return True, pid
        except Exception:
            pass

    return False, None


def get_local_ip_and_subnet(config=None):
    """
    Detecta la IP local y subred con soporte completo para Linux y Android/Termux:
    1. Interfaces Ethernet / USB Tethering (eth*, enp*, ens*, eno*, usb*, rndis*)
    2. Interfaces Wi-Fi (wlan*, wlp*, wl*, ap*, swlan*)
    3. Ruta de socket UDP estándar (funciona en Android 10-15 / Termux sin permisos netlink)
    4. Salida de ifconfig / ip addr / hostname -I
    5. Fallback 127.0.0.1 para uso offline local
    """
    if config is None:
        config = load_config()
    configured_subnet = config.get("CLUSTER_SUBNET", "").strip()

    local_ip = None

    # 1 y 2. Intentar por interfaces en /sys/class/net si el sistema lo permite
    try:
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir) and shutil.which("ip"):
            ifaces = sorted(os.listdir(net_dir))
            skip_prefixes = ("lo", "veth", "br", "docker", "virbr", "tun", "tap", "dummy", "rmnet", "ccmni")
            # Primero cableadas / USB tethering, luego Wi-Fi
            eth_ifaces = [i for i in ifaces if not i.startswith(skip_prefixes) and not i.startswith(("wl", "ap", "swlan"))]
            wifi_ifaces = [i for i in ifaces if i.startswith(("wl", "wlan", "wlp", "ap", "swlan"))]
            for iface in eth_ifaces + wifi_ifaces:
                res = subprocess.run(
                    ["ip", "-4", "addr", "show", iface],
                    capture_output=True,
                    text=True,
                    timeout=1.0
                )
                if res.returncode == 0:
                    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", res.stdout)
                    if m and not m.group(1).startswith("127."):
                        local_ip = m.group(1)
                        break
    except Exception:
        pass

    # 3. Socket UDP (Método más fiable en Termux/Android donde SELinux bloquea netlink)
    if not local_ip:
        for target in ("8.8.8.8", "1.1.1.1", "192.168.1.1", "192.168.0.1"):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(0.3)
                    s.connect((target, 80))
                    candidate = s.getsockname()[0]
                    if candidate and not candidate.startswith("127."):
                        local_ip = candidate
                        break
            except Exception:
                pass

    # 4. Fallback: ifconfig (común en Termux) o hostname -I
    if not local_ip and shutil.which("ifconfig"):
        try:
            res = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0:
                for m in re.finditer(r"inet\s+(?:addr:)?(\d+\.\d+\.\d+\.\d+)", res.stdout):
                    ip_cand = m.group(1)
                    if not ip_cand.startswith("127."):
                        local_ip = ip_cand
                        break
        except Exception:
            pass

    if not local_ip and shutil.which("hostname"):
        try:
            res = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout.strip():
                for ip_cand in res.stdout.strip().split():
                    if "." in ip_cand and not ip_cand.startswith("127."):
                        local_ip = ip_cand
                        break
        except Exception:
            pass

    if not local_ip:
        local_ip = "127.0.0.1"

    parts = local_ip.split(".")
    detected_subnet = ".".join(parts[:3]) if len(parts) == 4 and local_ip != "127.0.0.1" else "192.168.1"
    subnet = configured_subnet if configured_subnet else detected_subnet
    return local_ip, subnet


def scan_ip_port_with_latency(ip, port, timeout=0.18):
    """Intenta conectar por TCP a ip:port y devuelve (ip, port, latency_ms) o None."""
    t0 = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, int(port)))
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return (ip, int(port), latency_ms)
    except Exception:
        return None


def scan_network_rpc_detailed(subnet, port, custom_nodes="", excluded_nodes="", local_ip=""):
    """
    Escanea la subred /24 más los nodos personalizados en paralelo,
    excluyendo los nodos en excluded_nodes.
    Retorna (active_ips_list, detailed_nodes_list).
    """
    port = int(port)
    excluded_set = {x.strip() for x in excluded_nodes.split(",") if x.strip()}
    custom_targets = []
    custom_ips = set()

    for raw in custom_nodes.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if ":" in raw:
            cip, cport = raw.split(":", 1)
            cport = int(cport)
        else:
            cip, cport = raw, port
        if cip not in excluded_set:
            custom_targets.append((cip, cport))
            custom_ips.add(cip)

    if local_ip == "127.0.0.1" and not custom_targets:
        targets = [("127.0.0.1", port)]
    else:
        targets = [(f"{subnet}.{i}", port) for i in range(1, 255) if f"{subnet}.{i}" not in excluded_set]
    for ct in custom_targets:
        if ct not in targets:
            targets.append(ct)

    detailed = []
    seen_ips = set()

    max_workers = 48 if is_termux() else 96
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scan_ip_port_with_latency, ip, p) for ip, p in targets]
        for fut in futures:
            res = fut.result()
            if res:
                ip, p, lat = res
                if ip not in seen_ips:
                    seen_ips.add(ip)
                    detailed.append({
                        "ip": ip,
                        "port": p,
                        "latency_ms": lat,
                        "is_local": ip == local_ip or ip == "127.0.0.1",
                        "is_custom": ip in custom_ips
                    })

    def _ip_key(item):
        try:
            return [int(x) for x in item["ip"].split(".")]
        except Exception:
            return [999, 999, 999, 999]

    detailed.sort(key=_ip_key)
    active_ips = [d["ip"] for d in detailed]
    return active_ips, detailed


def scan_network_rpc(subnet, port, config=None):
    """Envoltorio compatible que retorna la lista de IPs activas."""
    if config is None:
        config = load_config()
    local_ip, _ = get_local_ip_and_subnet(config)
    ips, _ = scan_network_rpc_detailed(
        subnet,
        port,
        custom_nodes=config.get("CUSTOM_NODES", ""),
        excluded_nodes=config.get("EXCLUDED_NODES", ""),
        local_ip=local_ip
    )
    return ips


def query_active_model(port):
    """Consulta el modelo activo desde /props de llama-server o desde .state/llama.model."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/props")
        with urllib.request.urlopen(req, timeout=0.4) as response:
            data = json.loads(response.read().decode("utf-8"))
            model_path = data.get("default_generation_settings", {}).get("model", "") or data.get("model_path", "")
            if model_path:
                return os.path.basename(model_path)
    except Exception:
        pass

    model_file = os.path.join(STATE_DIR, "llama.model")
    if os.path.exists(model_file):
        try:
            with open(model_file, "r", encoding="utf-8") as f:
                name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
    return None


def format_bytes(size_bytes):
    """Formatea bytes a unidad legible (B, KB, MB, GB, TB)."""
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if val < 1024.0:
            return f"{val:.2f} {unit}"
        val /= 1024.0
    return f"{val:.2f} PB"


def download_model_cli(target=None):
    """
    Descarga un modelo del catálogo (por índice, ID o URL directa) desde terminal
    mostrando barra de progreso.
    """
    ensure_dir(MODEL_DIR)
    ram_gb = get_system_ram_gb()

    selected_url = None
    selected_filename = None

    if not target:
        print(f"\n=== CATÁLOGO DE MODELOS GGUF (RAM detectada: {ram_gb} GB) ===\n")
        for idx, m in enumerate(MODEL_CATALOG, 1):
            exists = os.path.exists(os.path.join(MODEL_DIR, m["filename"]))
            rec = ram_gb >= m["ram_min_gb"]
            status = "[DESCARGADO]" if exists else ("[RECOMENDADO]" if rec else f"[Req {m['ram_min_gb']}GB]")
            print(f"  [{idx:2d}] {m['name']:<28} ({m['size_gb']:>4.1f} GB) {status}")
            print(f"       ID: {m['id']} — {m['description']}")
        print("\n  También puedes pegar una URL directa a un archivo .gguf de HuggingFace.")
        try:
            choice = input("\n  Selecciona número, ID o URL (Enter para cancelar): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not choice:
            return None
        target = choice

    # Resolver target
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(MODEL_CATALOG):
            selected_url = MODEL_CATALOG[idx]["url"]
            selected_filename = MODEL_CATALOG[idx]["filename"]
    if not selected_url:
        for m in MODEL_CATALOG:
            if m["id"].lower() == target.lower() or m["filename"].lower() == target.lower():
                selected_url = m["url"]
                selected_filename = m["filename"]
                break
    if not selected_url and (target.startswith("http://") or target.startswith("https://")):
        selected_url = target
        selected_filename = target.split("?")[0].rstrip("/").split("/")[-1]
        if not selected_filename.endswith(".gguf"):
            selected_filename += ".gguf"

    if not selected_url:
        print(f"✗ Modelo o URL no reconocido: {target}")
        return None

    dest_path = os.path.join(MODEL_DIR, selected_filename)
    if os.path.exists(dest_path):
        print(f"✓ El modelo ya existe en: {dest_path}")
        return dest_path

    part_path = dest_path + ".part"
    print(f"\nDescargando: {selected_filename}")
    print(f"Origen:      {selected_url}")
    print(f"Destino:     {dest_path}\n")

    # Preferir curl -L si está disponible porque maneja redirecciones CDN y barra nativa muy bien en Termux/Linux
    if shutil.which("curl"):
        cmd = ["curl", "-L", "--fail", "--progress-bar", "-C", "-", "-o", part_path, selected_url]
        ret = subprocess.call(cmd)
        if ret == 0 and os.path.exists(part_path):
            os.replace(part_path, dest_path)
            print(f"\n✓ Modelo descargado exitosamente: {dest_path}")
            return dest_path
        else:
            print("\n✗ Descarga interrumpida o fallida.")
            return None

    # Fallback con urllib en Python
    try:
        req = urllib.request.Request(selected_url, headers={"User-Agent": "llamacppF-cli/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            t0 = time.time()
            with open(part_path, "wb") as f:
                while True:
                    chunk = resp.read(131072)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(0.001, time.time() - t0)
                    speed = downloaded / elapsed / (1024 * 1024)
                    if total > 0:
                        pct = downloaded * 100.0 / total
                        sys.stdout.write(f"\r  Progreso: {pct:5.1f}% ({format_bytes(downloaded)} / {format_bytes(total)}) @ {speed:.1f} MB/s")
                    else:
                        sys.stdout.write(f"\r  Descargado: {format_bytes(downloaded)} @ {speed:.1f} MB/s")
                    sys.stdout.flush()
        os.replace(part_path, dest_path)
        print(f"\n✓ Modelo descargado exitosamente: {dest_path}")
        return dest_path
    except KeyboardInterrupt:
        print("\n! Descarga cancelada por el usuario.")
        return None
    except Exception as e:
        print(f"\n✗ Error descargando modelo: {e}")
        return None


def sync_opencode_json(model_name=None, llama_port=8080, ctx_size=131072):
    """Sincroniza opencode.json con el puerto y modelo actual del cluster."""
    try:
        data = {}
        if os.path.exists(OPENCODE_FILE):
            with open(OPENCODE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

        if not model_name:
            model_name = "gemma-4-E4B-it-Q4_K_M.gguf"

        provider = data.setdefault("provider", {}).setdefault("llamacpp", {
            "api": "openai",
            "name": "llama.cpp",
            "options": {},
            "models": {}
        })
        provider.setdefault("options", {})["baseURL"] = f"http://127.0.0.1:{llama_port}/v1"
        provider["options"].setdefault("apiKey", "dummy")

        models_dict = provider.setdefault("models", {})
        if model_name not in models_dict:
            models_dict[model_name] = {
                "id": model_name,
                "name": f"{model_name} (llama.cpp RPC)",
                "family": model_name.split("-")[0].lower(),
                "limit": {
                    "context": int(ctx_size),
                    "input": int(ctx_size),
                    "output": int(ctx_size)
                },
                "modalities": {
                    "input": ["text"],
                    "output": ["text"]
                },
                "cost": {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_write": 0
                }
            }
        data["model"] = f"llamacpp/{model_name}"

        with open(OPENCODE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error syncing opencode.json: {e}")
        return False
