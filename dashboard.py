#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import socket
import concurrent.futures
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import mimetypes

# Configuración
PORT = 9000
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE_DIR, ".state")
MODEL_DIR = os.path.join(WORKSPACE_DIR, "models")
CONF_FILE = os.path.join(WORKSPACE_DIR, "cluster.conf")

# Default values
DEFAULTS = {
    "THREADS": "4",
    "CTX_SIZE": "4096",
    "BATCH_SIZE": "512",
    "LLAMA_PORT": "8080",
    "RPC_PORT": "50052",
    "CLUSTER_SUBNET": ""
}

# --- CATÁLOGO DE MODELOS DISPONIBLES ---
# Cada modelo tiene: nombre, url de Hugging Face, tamaño estimado, RAM mínima requerida
MODEL_CATALOG = [
    # --- CODING: Modelos pequeños (rápidos, para PCs limitadas) ---
    {
        "id": "qwen2.5-coder-0.5b",
        "name": "Qwen2.5 Coder 0.5B",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf",
        "size_gb": 0.4,
        "ram_min_gb": 1,
        "description": "Micro modelo de código. Autocompletado rápido, snippets simples.",
        "speed": "Muy rápido",
        "quality": "Básico",
        "ctx": 32768,
        "tags": ["coding", "lightweight"]
    },
    {
        "id": "qwen2.5-coder-1.5b",
        "name": "Qwen2.5 Coder 1.5B",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.0,
        "ram_min_gb": 2,
        "description": "Bueno para autocompletado y snippets. Python, JS, etc.",
        "speed": "Rápido",
        "quality": "Bueno",
        "ctx": 32768,
        "tags": ["coding", "lightweight"]
    },
    {
        "id": "deepseek-coder-1.3b",
        "name": "DeepSeek Coder 1.3B Lite",
        "family": "DeepSeek Coder",
        "url": "https://huggingface.co/bartowski/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-GGUF/resolve/main/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "filename": "deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "size_gb": 1.0,
        "ram_min_gb": 2,
        "description": "DeepSeek Coder V2 Lite. Excelente para código en 200+ lenguajes.",
        "speed": "Rápido",
        "quality": "Bueno",
        "ctx": 131072,
        "tags": ["coding", "lightweight"]
    },
    # --- CODING: Modelos medianos ---
    {
        "id": "qwen2.5-coder-3b",
        "name": "Qwen2.5 Coder 3B",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.9,
        "ram_min_gb": 3,
        "description": "Sweet spot para coding en 4-8GB RAM. Genera funciones completas.",
        "speed": "Rápido",
        "quality": "Muy Bueno",
        "ctx": 32768,
        "tags": ["coding"]
    },
    {
        "id": "codegemma-2b",
        "name": "CodeGemma 2B",
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
        "id": "qwen2.5-coder-7b",
        "name": "Qwen2.5 Coder 7B",
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
        "id": "deepseek-coder-6.7b",
        "name": "DeepSeek Coder V2 16B (Light)",
        "family": "DeepSeek Coder",
        "url": "https://huggingface.co/bartowski/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-GGUF/resolve/main/deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "filename": "deepseek-ai_DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "size_gb": 4.7,
        "ram_min_gb": 7,
        "description": "DeepSeek V2 Lite. 16B params, arquitectura MoE. Coding de nivel premium.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["coding"]
    },
    {
        "id": "codellama-7b",
        "name": "CodeLlama 7B Instruct",
        "family": "CodeLlama",
        "url": "https://huggingface.co/bartowski/codellama/CodeLlama-7b-Instruct-GGUF/resolve/main/codellama-7b-instruct-Q4_K_M.gguf",
        "filename": "codellama-7b-instruct-Q4_K_M.gguf",
        "size_gb": 4.1,
        "ram_min_gb": 6,
        "description": "Meta CodeLlama. El clásico para código. Buena documentación.",
        "speed": "Medio",
        "quality": "Muy Bueno",
        "ctx": 16384,
        "tags": ["coding"]
    },
    # --- CODING: Modelos grandes ---
    {
        "id": "qwen2.5-coder-14b",
        "name": "Qwen2.5 Coder 14B",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        "size_gb": 8.8,
        "ram_min_gb": 12,
        "description": "Coding de clase mundial. Arquitectura completa, testing, refactoring.",
        "speed": "Lento",
        "quality": "Premium",
        "ctx": 131072,
        "tags": ["coding", "premium"]
    },
    {
        "id": "qwen2.5-coder-32b",
        "name": "Qwen2.5 Coder 32B",
        "family": "Qwen 2.5 Coder",
        "url": "https://huggingface.co/unsloth/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        "size_gb": 18.0,
        "ram_min_gb": 24,
        "description": "EL MEJOR modelo de código open source. Nivel GPT-4 para coding.",
        "speed": "Muy Lento",
        "quality": "Top",
        "ctx": 131072,
        "tags": ["coding", "premium"]
    },
    # --- GENERAL: Buenos para todo incluyendo código ---
    {
        "id": "phi-3.5-mini",
        "name": "Phi-3.5 Mini Instruct",
        "family": "Phi",
        "url": "https://huggingface.co/bartowski/microsoft_Phi-3.5-mini-instruct-GGUF/resolve/main/microsoft_Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "filename": "microsoft_Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size_gb": 2.4,
        "ram_min_gb": 4,
        "description": "Microsoft Phi. Excelente razonamiento y código para su tamaño.",
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
        "description": "Google Gemma 4. Multimodal, buen código y conversación.",
        "speed": "Medio",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general"]
    },
    {
        "id": "qwen2.5-7b-instruct",
        "name": "Qwen2.5 7B Instruct",
        "family": "Qwen 2.5",
        "url": "https://huggingface.co/unsloth/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.7,
        "ram_min_gb": 7,
        "description": "General purpose top tier. Muy bueno para código también.",
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
        "speed": "Lento",
        "quality": "Excelente",
        "ctx": 131072,
        "tags": ["general"]
    }
]

# --- ESTADO DE DESCARGAS ---
download_state = {}  # { "filename": {"status": "downloading|done|error", "progress": 0-100, "speed": "...", "error": "..."} }
_download_lock = threading.Lock()

def get_system_ram_gb():
    """Obtiene la RAM total del sistema en GB"""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    kb = int(line.split(":")[1].strip().split()[0])
                    return round(kb / (1024 * 1024), 1)
    except Exception:
        pass
    return 4.0

def start_model_download(url, filename):
    """Inicia la descarga de un modelo en un hilo"""
    def _download():
        dest = os.path.join(MODEL_DIR, filename)
        with _download_lock:
            download_state[filename] = {"status": "downloading", "progress": 0, "speed": "", "error": ""}
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "llamacppF-dashboard/1.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                start = time.time()
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        if elapsed > 0:
                            speed = downloaded / elapsed / 1024 / 1024  # MB/s
                            with _download_lock:
                                download_state[filename]["speed"] = f"{speed:.1f} MB/s"
                        if total > 0:
                            pct = round(downloaded / total * 100, 1)
                            with _download_lock:
                                download_state[filename]["progress"] = pct
            with _download_lock:
                download_state[filename]["status"] = "done"
                download_state[filename]["progress"] = 100
        except Exception as e:
            with _download_lock:
                download_state[filename]["status"] = "error"
                download_state[filename]["error"] = str(e)
            # Clean up partial file
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except Exception:
                pass
    
    t = threading.Thread(target=_download, daemon=True)
    t.start()

def load_config():
    config = DEFAULTS.copy()
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        # Remove quotes if present
                        v = v.strip().strip('"').strip("'")
                        config[k.strip()] = v
        except Exception as e:
            print(f"Error loading config: {e}")
    return config

def save_config(config):
    try:
        with open(CONF_FILE, "w") as f:
            f.write("# Configuración del Cluster Llama.cpp (Generado por Dashboard)\n")
            for k, v in config.items():
                f.write(f'{k}="{v}"\n')
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def get_pid_status(pid_file):
    if not os.path.exists(pid_file):
        return False, None
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        # Check if pid is running
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
        return False, None

def get_local_ip_and_subnet(config):
    # If subnet is already configured, try to use it
    configured_subnet = config.get("CLUSTER_SUBNET", "")
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    
    parts = local_ip.split('.')
    if len(parts) == 4:
        detected_subnet = ".".join(parts[:3])
    else:
        detected_subnet = "192.168.1"
        
    subnet = configured_subnet if configured_subnet else detected_subnet
    return local_ip, subnet

def scan_ip_port(ip, port, timeout=0.15):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            return ip
    except Exception:
        return None

def scan_network_rpc(subnet, port):
    active_nodes = []
    ips = [f"{subnet}.{i}" for i in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        results = executor.map(lambda ip: scan_ip_port(ip, port), ips)
        for ip in results:
            if ip:
                active_nodes.append(ip)
    return active_nodes

def get_active_model_name():
    args_file = os.path.join(STATE_DIR, "llama.args")
    if os.path.exists(args_file):
        try:
            # First see if llama-server is actually running
            is_running, _ = get_pid_status(os.path.join(STATE_DIR, "llama.pid"))
            if not is_running:
                return None
            
            # Read arguments to find out what model might be running (or ask server API)
            # Alternatively, query llama-server /props endpoint which is cleaner
            config = load_config()
            port = int(config.get("LLAMA_PORT", 8080))
            req = urllib.request.Request(f"http://127.0.0.1:{port}/props")
            with urllib.request.urlopen(req, timeout=0.5) as response:
                data = json.loads(response.read().decode())
                # Extract model file name from path
                model_path = data.get("default_generation_settings", {}).get("model", "")
                if model_path:
                    return os.path.basename(model_path)
        except Exception:
            # Fallback: read log or state
            pass
            
    # Fallback to checking logs or processes if API request fails
    return None

def get_system_cpu():
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        parts = line.split()
        idle1 = float(parts[4]) + float(parts[5])
        non_idle1 = float(parts[1]) + float(parts[2]) + float(parts[3]) + float(parts[6]) + float(parts[7]) + float(parts[8])
        total1 = idle1 + non_idle1
        
        time.sleep(0.08) # Small sleep, barely noticeable
        
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        parts = line.split()
        idle2 = float(parts[4]) + float(parts[5])
        non_idle2 = float(parts[1]) + float(parts[2]) + float(parts[3]) + float(parts[6]) + float(parts[7]) + float(parts[8])
        total2 = idle2 + non_idle2
        
        total_diff = total2 - total1
        idle_diff = idle2 - idle1
        if total_diff > 0:
            return round((total_diff - idle_diff) / total_diff * 100, 1)
    except Exception:
        pass
    return 0.0

def get_system_mem():
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = parts[1].strip()
        total_kb = int(meminfo["MemTotal"].split()[0])
        free_kb = int(meminfo.get("MemAvailable", meminfo.get("MemFree", "0")).split()[0])
        used_kb = total_kb - free_kb
        
        used_gb = used_kb / (1024.0 * 1024.0)
        total_gb = total_kb / (1024.0 * 1024.0)
        pct = (used_kb / total_kb) * 100 if total_kb > 0 else 0
        return {
            "used_gb": round(used_gb, 2),
            "total_gb": round(total_gb, 2),
            "pct": round(pct, 1)
        }
    except Exception:
        pass
    return {"used_gb": 0.0, "total_gb": 0.0, "pct": 0.0}

def get_process_stats(pid):
    if not pid:
        return {"cpu": 0.0, "mem_mb": 0.0}
    try:
        # Run ps to get CPU and RSS (Resident Set Size) in KB
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "%cpu,rss"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2:
                    cpu = float(parts[0])
                    rss_kb = int(parts[1])
                    rss_mb = rss_kb / 1024.0
                    return {"cpu": cpu, "mem_mb": round(rss_mb, 1)}
    except Exception:
        pass
    return {"cpu": 0.0, "mem_mb": 0.0}

# --- FUNCIONES DE MONITOREO AVANZADO ---

def get_cpu_temperature():
    """Lee la temperatura del CPU desde /sys/class/thermal/"""
    try:
        thermal_zones = "/sys/class/thermal"
        if os.path.isdir(thermal_zones):
            for zone in sorted(os.listdir(thermal_zones)):
                if zone.startswith("thermal_zone"):
                    type_path = os.path.join(thermal_zones, zone, "type")
                    temp_path = os.path.join(thermal_zones, zone, "temp")
                    if os.path.exists(temp_path):
                        with open(temp_path, "r") as f:
                            temp_mc = int(f.read().strip())
                        return round(temp_mc / 1000.0, 1)
    except Exception:
        pass
    return None

def get_disk_usage():
    """Obtiene uso de disco de la partición raíz"""
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        free_gb = free / (1024 ** 3)
        pct = (used / total * 100) if total > 0 else 0
        return {
            "total_gb": round(total_gb, 1),
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 1),
            "percent": round(pct, 1)
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

# Estado previo para calcular deltas de red y disco
_prev_net_io = {"rx": 0, "tx": 0, "timestamp": 0}
_prev_disk_io = {"read": 0, "write": 0, "timestamp": 0}

def get_network_io():
    """Obtiene bytes recibidos/enviados y calcula rate (KB/s)"""
    global _prev_net_io
    try:
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if "eth" in line or "enp" in line or "ens" in line:
                    parts = line.split()
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    now = time.time()
                    dt = now - _prev_net_io["timestamp"] if _prev_net_io["timestamp"] > 0 else 0
                    rate_rx = 0
                    rate_tx = 0
                    if dt > 0 and _prev_net_io["timestamp"] > 0:
                        rate_rx = (rx_bytes - _prev_net_io["rx"]) / dt / 1024  # KB/s
                        rate_tx = (tx_bytes - _prev_net_io["tx"]) / dt / 1024
                    _prev_net_io = {"rx": rx_bytes, "tx": tx_bytes, "timestamp": now}
                    return {
                        "rx_bytes": rx_bytes,
                        "tx_bytes": tx_bytes,
                        "rx_rate_kbs": round(max(0, rate_rx), 1),
                        "tx_rate_kbs": round(max(0, rate_tx), 1)
                    }
        # Si no se encontró interfaz ethernet, usar la primera
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if ":" in line and "lo" not in line:
                    parts = line.split()
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    now = time.time()
                    dt = now - _prev_net_io["timestamp"] if _prev_net_io["timestamp"] > 0 else 0
                    rate_rx = 0
                    rate_tx = 0
                    if dt > 0 and _prev_net_io["timestamp"] > 0:
                        rate_rx = (rx_bytes - _prev_net_io["rx"]) / dt / 1024
                        rate_tx = (tx_bytes - _prev_net_io["tx"]) / dt / 1024
                    _prev_net_io = {"rx": rx_bytes, "tx": tx_bytes, "timestamp": now}
                    return {
                        "rx_bytes": rx_bytes,
                        "tx_bytes": tx_bytes,
                        "rx_rate_kbs": round(max(0, rate_rx), 1),
                        "tx_rate_kbs": round(max(0, rate_tx), 1)
                    }
    except Exception:
        pass
    return {"rx_bytes": 0, "tx_bytes": 0, "rx_rate_kbs": 0, "tx_rate_kbs": 0}

def get_disk_io():
    """Obtiene lecturas/escrituras de disco y calcula rate (KB/s)"""
    global _prev_disk_io
    try:
        with open("/proc/diskstats", "r") as f:
            total_read = 0
            total_write = 0
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    name = parts[2]
                    # Solo discos sda, vda, nvme0n1 (no particiones ni loop)
                    if name.startswith("sd") and not name[-1].isdigit() or \
                       name.startswith("vd") and not name[-1].isdigit() or \
                       name == "nvme0n1":
                        total_read += int(parts[5]) * 512   # sectores de 512 bytes
                        total_write += int(parts[9]) * 512
            now = time.time()
            dt = now - _prev_disk_io["timestamp"] if _prev_disk_io["timestamp"] > 0 else 0
            rate_read = 0
            rate_write = 0
            if dt > 0 and _prev_disk_io["timestamp"] > 0:
                rate_read = (total_read - _prev_disk_io["read"]) / dt / 1024
                rate_write = (total_write - _prev_disk_io["write"]) / dt / 1024
            _prev_disk_io = {"read": total_read, "write": total_write, "timestamp": now}
            return {
                "read_bytes": total_read,
                "write_bytes": total_write,
                "read_rate_kbs": round(max(0, rate_read), 1),
                "write_rate_kbs": round(max(0, rate_write), 1)
            }
    except Exception:
        pass
    return {"read_bytes": 0, "write_bytes": 0, "read_rate_kbs": 0, "write_rate_kbs": 0}

def get_load_avg():
    """Obtiene load average 1, 5, 15 minutos"""
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
        return {
            "load1": round(float(parts[0]), 2),
            "load5": round(float(parts[1]), 2),
            "load15": round(float(parts[2]), 2)
        }
    except Exception:
        return {"load1": 0, "load5": 0, "load15": 0}

def get_process_uptime(pid):
    """Obtiene el uptime de un proceso en segundos"""
    if not pid:
        return 0
    try:
        stat_path = f"/proc/{pid}/stat"
        if os.path.exists(stat_path):
            with open(stat_path, "r") as f:
                data = f.read()
            # El campo 21 (0-indexed 22) es starttime en ticks
            fields = data.split(")")
            if len(fields) > 1:
                proc_fields = fields[1].split()
                start_ticks = int(proc_fields[19])
                # Obtener uptime del sistema
                with open("/proc/uptime", "r") as f:
                    uptime_sec = float(f.read().split()[0])
                # Obtener ticks por segundo
                import os as _os
                clk_tck = _os.sysconf(_os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
                start_sec = start_ticks / clk_tck
                return round(uptime_sec - start_sec, 0)
    except Exception:
        pass
    return 0

# --- RING BUFFER DE MÉTRICAS ---

METRICS_HISTORY = []
MAX_HISTORY = 300  # ~25 min a intervalos de 5 segundos

_prev_collect_net = {"rx": 0, "tx": 0, "timestamp": 0}
_prev_collect_disk = {"read": 0, "write": 0, "timestamp": 0}

def collect_metrics():
    """Recoleta una muestra de métricas y la agrega al historial"""
    global _prev_collect_net, _prev_collect_disk

    # Obtener PIDs
    llama_pid = None
    rpc_pid = None
    try:
        llama_file = os.path.join(STATE_DIR, "llama.pid")
        rpc_file = os.path.join(STATE_DIR, "rpc.pid")
        if os.path.exists(llama_file):
            with open(llama_file, "r") as f:
                llama_pid = int(f.read().strip())
            os.kill(llama_pid, 0)
        else:
            llama_pid = None
    except Exception:
        llama_pid = None
    try:
        if os.path.exists(rpc_file):
            with open(rpc_file, "r") as f:
                rpc_pid = int(f.read().strip())
            os.kill(rpc_pid, 0)
        else:
            rpc_pid = None
    except Exception:
        rpc_pid = None

    sys_cpu = get_system_cpu()
    sys_mem = get_system_mem()
    temp = get_cpu_temperature()
    load = get_load_avg()
    disk = get_disk_usage()
    disk_io = get_disk_io()
    net_io = get_network_io()

    llama_stats = get_process_stats(llama_pid) if llama_pid else {"cpu": 0.0, "mem_mb": 0.0}
    rpc_stats = get_process_stats(rpc_pid) if rpc_pid else {"cpu": 0.0, "mem_mb": 0.0}
    llama_uptime = get_process_uptime(llama_pid) if llama_pid else 0

    point = {
        "t": round(time.time()),
        "cpu": sys_cpu,
        "ram_pct": sys_mem["pct"],
        "ram_used": sys_mem["used_gb"],
        "ram_total": sys_mem["total_gb"],
        "temp": temp,
        "load1": load["load1"],
        "load5": load["load5"],
        "load15": load["load15"],
        "disk_pct": disk["percent"],
        "disk_used": disk["used_gb"],
        "disk_total": disk["total_gb"],
        "disk_read_kbs": disk_io["read_rate_kbs"],
        "disk_write_kbs": disk_io["write_rate_kbs"],
        "net_rx_kbs": net_io["rx_rate_kbs"],
        "net_tx_kbs": net_io["tx_rate_kbs"],
        "proc_cpu_llama": llama_stats["cpu"],
        "proc_ram_llama": llama_stats["mem_mb"],
        "proc_cpu_rpc": rpc_stats["cpu"],
        "proc_ram_rpc": rpc_stats["mem_mb"],
        "llama_uptime": llama_uptime
    }

    METRICS_HISTORY.append(point)
    if len(METRICS_HISTORY) > MAX_HISTORY:
        METRICS_HISTORY.pop(0)

def get_alert_config():
    """Carga configuración de alertas"""
    defaults = {
        "cpu_threshold": "90",
        "ram_threshold": "85",
        "temp_threshold": "80",
        "enabled": "true"
    }
    config = load_config()
    return {
        "cpu_threshold": int(config.get("ALERT_CPU_THRESHOLD", defaults["cpu_threshold"])),
        "ram_threshold": int(config.get("ALERT_RAM_THRESHOLD", defaults["ram_threshold"])),
        "temp_threshold": int(config.get("ALERT_TEMP_THRESHOLD", defaults["temp_threshold"])),
        "enabled": config.get("ALERTS_ENABLED", defaults["enabled"]) == "true"
    }

def check_alerts(metrics):
    """Verifica si alguna métrica supera los umbrales"""
    alert_config = get_alert_config()
    if not alert_config["enabled"]:
        return []
    alerts = []
    if metrics.get("cpu", 0) >= alert_config["cpu_threshold"]:
        alerts.append({"type": "cpu", "value": metrics["cpu"], "threshold": alert_config["cpu_threshold"], "severity": "critical"})
    if metrics.get("ram_pct", 0) >= alert_config["ram_threshold"]:
        alerts.append({"type": "ram", "value": metrics["ram_pct"], "threshold": alert_config["ram_threshold"], "severity": "critical"})
    if metrics.get("temp") is not None and metrics["temp"] >= alert_config["temp_threshold"]:
        alerts.append({"type": "temp", "value": metrics["temp"], "threshold": alert_config["temp_threshold"], "severity": "warning"})
    return alerts

class DashboardAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute standard request logs to keep terminal clean
        pass

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.handle_api_get()
        else:
            self.serve_static_file()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.handle_api_post()
        else:
            self.send_error(404, "Not Found")

    def serve_static_file(self):
        # Normalize path
        path = self.path.split('?')[0]
        if path == "/":
            path = "/index.html"
            
        file_path = os.path.join(WORKSPACE_DIR, "web" + path)
        
        # Security check to prevent directory traversal
        real_file_path = os.path.realpath(file_path)
        real_web_dir = os.path.realpath(os.path.join(WORKSPACE_DIR, "web"))
        
        if not real_file_path.startswith(real_web_dir):
            self.send_error(403, "Forbidden")
            return

        if os.path.exists(real_file_path) and os.path.isfile(real_file_path):
            self.send_response(200)
            mime_type, _ = mimetypes.guess_type(real_file_path)
            if mime_type:
                self.send_header("Content-Type", mime_type)
            self.end_headers()
            with open(real_file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, f"File Not Found: {path}")

    def handle_api_get(self):
        config = load_config()
        
        if self.path == "/api/status":
            rpc_file = os.path.join(STATE_DIR, "rpc.pid")
            llama_file = os.path.join(STATE_DIR, "llama.pid")
            
            rpc_running, rpc_pid = get_pid_status(rpc_file)
            llama_running, llama_pid = get_pid_status(llama_file)
            
            local_ip, subnet = get_local_ip_and_subnet(config)
            
            # Check llama-server health
            llama_port = int(config.get("LLAMA_PORT", 8080))
            health_ok = False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/health", timeout=0.3) as response:
                    health_ok = response.status == 200
            except Exception:
                pass
                
            active_model = get_active_model_name()
            
            # Fast scan of current active nodes on status check (timeout short to avoid blocking)
            rpc_port = int(config.get("RPC_PORT", 50052))
            # Run scan
            active_workers = scan_network_rpc(subnet, rpc_port)
            
            # Recolectar datos de Hardware
            sys_cpu = get_system_cpu()
            sys_mem = get_system_mem()
            llama_hw = get_process_stats(llama_pid) if llama_running else {"cpu": 0.0, "mem_mb": 0.0}
            rpc_hw = get_process_stats(rpc_pid) if rpc_running else {"cpu": 0.0, "mem_mb": 0.0}
            
            hardware_data = {
                "system": {
                    "cpu": sys_cpu,
                    "mem_used_gb": sys_mem["used_gb"],
                    "mem_total_gb": sys_mem["total_gb"],
                    "mem_pct": sys_mem["pct"]
                },
                "processes": {
                    "llama_server": {
                        "running": llama_running,
                        "pid": llama_pid,
                        "cpu": llama_hw["cpu"],
                        "mem_mb": llama_hw["mem_mb"]
                    },
                    "rpc_server": {
                        "running": rpc_running,
                        "pid": rpc_pid,
                        "cpu": rpc_hw["cpu"],
                        "mem_mb": rpc_hw["mem_mb"]
                    }
                },
                "temperature": get_cpu_temperature(),
                "disk": get_disk_usage(),
                "network": get_network_io(),
                "load_avg": get_load_avg()
            }
            
            status_data = {
                "rpc_server_running": rpc_running,
                "rpc_pid": rpc_pid,
                "llama_server_running": llama_running,
                "llama_pid": llama_pid,
                "llama_port": llama_port,
                "health_ok": health_ok,
                "local_ip": local_ip,
                "subnet": subnet,
                "active_workers": active_workers,
                "active_model": active_model,
                "hardware": hardware_data,
                "config": config
            }
            self.send_json(status_data)
            
        elif self.path == "/api/models":
            models_list = []
            if os.path.exists(MODEL_DIR):
                for filename in os.listdir(MODEL_DIR):
                    if filename.endswith(".gguf"):
                        full_path = os.path.join(MODEL_DIR, filename)
                        stat = os.stat(full_path)
                        size_bytes = stat.st_size
                        # Format size to human readable
                        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                            if size_bytes < 1024.0:
                                size_human = f"{size_bytes:.2f} {unit}"
                                break
                            size_bytes /= 1024.0
                        else:
                            size_human = f"{size_bytes:.2f} PB"
                            
                        models_list.append({
                            "name": filename,
                            "size_bytes": stat.st_size,
                            "size_human": size_human,
                            "modified": stat.st_mtime
                        })
            # Sort models by name
            models_list.sort(key=lambda x: x["name"])
            self.send_json({"models": models_list})
            
        elif self.path == "/api/nodes":
            local_ip, subnet = get_local_ip_and_subnet(config)
            rpc_port = int(config.get("RPC_PORT", 50052))
            nodes = scan_network_rpc(subnet, rpc_port)
            self.send_json({"nodes": nodes, "subnet": subnet, "port": rpc_port})
            
        elif self.path.startswith("/api/logs"):
            # Parse query parameters
            query = ""
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
            params = {}
            for pair in query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v
                    
            log_type = params.get("type", "llama")
            lines_count = int(params.get("lines", "100"))
            
            log_file = os.path.join(STATE_DIR, "llama.log" if log_type == "llama" else "rpc.log")
            
            log_content = ""
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        log_content = "".join(lines[-lines_count:])
                except Exception as e:
                    log_content = f"Error reading log file: {e}"
            else:
                log_content = f"Log file {log_file} does not exist yet."
                
            self.send_json({"type": log_type, "content": log_content})
            
        elif self.path == "/api/diag":
            # Run diag and return
            try:
                result = subprocess.run(
                    ["./cluster.sh", "diag"],
                    cwd=WORKSPACE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                self.send_json({
                    "success": result.returncode == 0,
                    "output": result.stdout,
                    "error": result.stderr
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/metrics/history":
            self.send_json({"history": METRICS_HISTORY})

        elif self.path == "/api/alerts/config":
            self.send_json(get_alert_config())

        elif self.path == "/api/alerts/check":
            if METRICS_HISTORY:
                alerts = check_alerts(METRICS_HISTORY[-1])
                self.send_json({"alerts": alerts})
            else:
                self.send_json({"alerts": []})

        elif self.path == "/api/models/catalog":
            ram_gb = get_system_ram_gb()
            # Tag models as recommended/not recommended based on available RAM
            catalog = []
            for m in MODEL_CATALOG:
                item = dict(m)
                item["recommended"] = ram_gb >= m["ram_min_gb"]
                item["ram_available_gb"] = ram_gb
                # Check if already downloaded
                item["downloaded"] = os.path.exists(os.path.join(MODEL_DIR, m["filename"]))
                catalog.append(item)
            self.send_json({"catalog": catalog, "ram_gb": ram_gb})

        else:
            self.send_error(404, "API Endpoint Not Found")

    def handle_api_post(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        try:
            payload = json.loads(post_data) if post_data else {}
        except Exception:
            self.send_json({"success": False, "error": "Invalid JSON"}, status=400)
            return

        config = load_config()

        if self.path == "/api/control":
            action = payload.get("action")
            
            if action == "start_server":
                model_name = payload.get("model")
                if not model_name:
                    self.send_json({"success": False, "error": "No model specified"}, status=400)
                    return
                
                # Optionally update parameters in config
                updated = False
                for param in ["threads", "ctx_size", "batch_size", "llama_port", "rpc_port"]:
                    val = payload.get(param)
                    if val is not None:
                        config[param.upper()] = str(val)
                        updated = True
                if updated:
                    save_config(config)
                
                # Build environment with target model
                env = os.environ.copy()
                env["MODEL"] = model_name
                
                # Execute cluster.sh server in a detached process
                try:
                    # Clean up first if running
                    llama_file = os.path.join(STATE_DIR, "llama.pid")
                    llama_running, llama_pid = get_pid_status(llama_file)
                    if llama_running:
                        subprocess.run(["./cluster.sh", "stop"], cwd=WORKSPACE_DIR, capture_output=True)
                        time.sleep(1)

                    # Start
                    proc = subprocess.Popen(
                        ["./cluster.sh", "server"],
                        cwd=WORKSPACE_DIR,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setpgrp # Create its own process group to prevent termination on parent exit
                    )
                    
                    self.send_json({
                        "success": True, 
                        "message": "Iniciando servidor en segundo plano...",
                        "process_pid": proc.pid
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)
                    
            elif action == "stop_all":
                try:
                    result = subprocess.run(
                        ["./cluster.sh", "stop"],
                        cwd=WORKSPACE_DIR,
                        capture_output=True,
                        text=True
                    )
                    self.send_json({
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)
                    
            elif action == "start_worker":
                # Execute cluster.sh worker -d (daemon mode)
                try:
                    result = subprocess.run(
                        ["./cluster.sh", "worker", "-d"],
                        cwd=WORKSPACE_DIR,
                        capture_output=True,
                        text=True
                    )
                    self.send_json({
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)
                    
            elif action == "stop_worker":
                rpc_file = os.path.join(STATE_DIR, "rpc.pid")
                rpc_running, rpc_pid = get_pid_status(rpc_file)
                if rpc_running:
                    try:
                        os.kill(rpc_pid, 15) # SIGTERM
                        self.send_json({"success": True, "message": f"Worker detenido (PID {rpc_pid})"})
                    except Exception as e:
                        self.send_json({"success": False, "error": str(e)}, status=500)
                else:
                    self.send_json({"success": False, "error": "El worker no está activo"})
                    
            else:
                self.send_json({"success": False, "error": f"Unknown action: {action}"}, status=400)
                
        elif self.path == "/api/settings":
            # Update settings
            updated = False
            for param in ["threads", "ctx_size", "batch_size", "llama_port", "rpc_port", "cluster_subnet"]:
                val = payload.get(param)
                if val is not None:
                    config[param.upper()] = str(val)
                    updated = True
                    
            if updated:
                success = save_config(config)
                self.send_json({"success": success, "config": load_config()})
            else:
                self.send_json({"success": False, "error": "No settings provided"}, status=400)

        elif self.path == "/api/alerts/config":
            # Update alert thresholds
            updated = False
            for param in ["cpu_threshold", "ram_threshold", "temp_threshold"]:
                val = payload.get(param)
                if val is not None:
                    config[param.upper()] = str(val)
                    updated = True
            if "enabled" in payload:
                config["ALERTS_ENABLED"] = "true" if payload["enabled"] else "false"
                updated = True
            if updated:
                success = save_config(config)
                self.send_json({"success": success, "config": get_alert_config()})
            else:
                self.send_json({"success": False, "error": "No alert settings provided"}, status=400)

        elif self.path == "/api/models/download":
            # Start downloading a model from Hugging Face
            model_url = payload.get("url")
            model_name = payload.get("name")
            if not model_url or not model_name:
                self.send_json({"success": False, "error": "url and name are required"}, status=400)
                return
            # Sanitize filename
            model_name = model_name.replace("/", "_").replace("\\", "_")
            if not model_name.endswith(".gguf"):
                model_name += ".gguf"
            dest_path = os.path.join(MODEL_DIR, model_name)
            if os.path.exists(dest_path):
                self.send_json({"success": False, "error": f"El modelo {model_name} ya existe"}, status=409)
                return
            # Start download in background thread
            start_model_download(model_url, model_name)
            self.send_json({"success": True, "message": f"Descargando {model_name}..."})

        elif self.path == "/api/models/download/progress":
            self.send_json({"downloads": download_state})

        elif self.path == "/api/models/delete":
            model_name = payload.get("name")
            if not model_name:
                self.send_json({"success": False, "error": "name is required"}, status=400)
                return
            model_path = os.path.join(MODEL_DIR, model_name)
            if not os.path.exists(model_path):
                self.send_json({"success": False, "error": "Modelo no encontrado"}, status=404)
                return
            try:
                os.remove(model_path)
                self.send_json({"success": True, "message": f"Modelo {model_name} eliminado"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
                
        elif self.path == "/api/benchmark":
            # Run a live benchmark test
            llama_port = int(config.get("LLAMA_PORT", 8080))
            url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"
            
            prompt = payload.get("prompt", "Escribe una historia corta sobre un cluster de computadoras en 3 párrafos.")
            max_tokens = int(payload.get("max_tokens", 150))
            
            # Formulate the payload
            api_payload = {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "stream": True
            }
            
            headers = {"Content-Type": "application/json"}
            req = urllib.request.Request(url, data=json.dumps(api_payload).encode('utf-8'), headers=headers)
            
            try:
                start_time = time.time()
                first_token_time = None
                tokens_count = 0
                response_text = ""
                
                with urllib.request.urlopen(req, timeout=10.0) as response:
                    for line in response:
                        line = line.decode('utf-8').strip()
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    if first_token_time is None:
                                        first_token_time = time.time()
                                    tokens_count += 1
                                    response_text += content
                            except Exception:
                                pass
                                
                end_time = time.time()
                
                if first_token_time is None:
                    first_token_time = end_time
                    
                total_duration = end_time - start_time
                prompt_eval_duration = first_token_time - start_time
                gen_duration = end_time - first_token_time
                
                tokens_per_sec = tokens_count / gen_duration if gen_duration > 0 else 0
                
                self.send_json({
                    "success": True,
                    "prompt_eval_ms": int(prompt_eval_duration * 1000),
                    "gen_ms": int(gen_duration * 1000),
                    "total_ms": int(total_duration * 1000),
                    "tokens_count": tokens_count,
                    "tokens_per_sec": round(tokens_per_sec, 2),
                    "response_preview": response_text
                })
                
            except urllib.error.URLError as e:
                self.send_json({
                    "success": False,
                    "error": f"No se pudo conectar con el servidor llama.cpp en puerto {llama_port}. ¿Está activo? Details: {e}"
                }, status=502)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
        else:
            self.send_error(404, "API Endpoint Not Found")

def metrics_collector_thread():
    """Hilo que recolecta métricas cada 5 segundos en background"""
    # Primer recolección para inicializar deltas
    collect_metrics()
    while True:
        time.sleep(5)
        try:
            collect_metrics()
        except Exception as e:
            print(f"Error collecting metrics: {e}")

def run(port=PORT):
    # Ensure state dir exists
    os.makedirs(STATE_DIR, exist_ok=True)

    # Iniciar hilo de recolección de métricas en background
    collector = threading.Thread(target=metrics_collector_thread, daemon=True)
    collector.start()

    server_address = ('', port)
    httpd = HTTPServer(server_address, DashboardAPIHandler)
    print(f"==================================================")
    print(f" LLAMA.CPP CLUSTER DASHBOARD BACKEND INICIADO")
    print(f"   URL: http://localhost:{port}")
    print(f"   Monitoreo de métricas activo (5s interval)")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor...")
        httpd.server_close()

if __name__ == '__main__':
    run()
