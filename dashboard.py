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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import mimetypes

from cluster_core import (
    WORKSPACE_DIR,
    STATE_DIR,
    MODEL_DIR,
    CONF_FILE,
    DEFAULTS,
    MODEL_CATALOG,
    is_termux,
    get_system_ram_gb,
    load_config,
    save_config,
    get_pid_status,
    get_local_ip_and_subnet,
    scan_network_rpc,
    scan_network_rpc_detailed,
    query_active_model,
    format_bytes,
    sync_opencode_json,
)

# Configuración
PORT = 9000

# --- ESTADO DE DESCARGAS ---
download_state = {}  # { "filename": {"status": "downloading|done|error|cancelled", "progress": 0-100, "speed": "...", "error": "..."} }
_download_cancel = set()
_download_lock = threading.Lock()


def cancel_model_download(filename):
    """Marca una descarga en progreso para cancelación"""
    with _download_lock:
        if filename in download_state and download_state[filename].get("status") == "downloading":
            _download_cancel.add(filename)
            return True
    return False


def start_model_download(url, filename):
    """Inicia la descarga de un modelo en un hilo escribiendo a archivo .part temporal"""
    def _download():
        os.makedirs(MODEL_DIR, exist_ok=True)
        dest = os.path.join(MODEL_DIR, filename)
        temp_dest = dest + ".part"
        with _download_lock:
            _download_cancel.discard(filename)
            download_state[filename] = {"status": "downloading", "progress": 0, "speed": "", "error": ""}
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "llamacppF-dashboard/2.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                start = time.time()
                with open(temp_dest, "wb") as f:
                    while True:
                        with _download_lock:
                            if filename in _download_cancel:
                                _download_cancel.discard(filename)
                                raise InterruptedError("Descarga cancelada por el usuario")
                        chunk = resp.read(131072)
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
            os.replace(temp_dest, dest)
            with _download_lock:
                download_state[filename]["status"] = "done"
                download_state[filename]["progress"] = 100
        except InterruptedError as ie:
            with _download_lock:
                download_state[filename]["status"] = "cancelled"
                download_state[filename]["error"] = str(ie)
            try:
                if os.path.exists(temp_dest):
                    os.remove(temp_dest)
            except Exception:
                pass
        except Exception as e:
            with _download_lock:
                download_state[filename]["status"] = "error"
                download_state[filename]["error"] = str(e)
            try:
                if os.path.exists(temp_dest):
                    os.remove(temp_dest)
            except Exception:
                pass

    t = threading.Thread(target=_download, daemon=True)
    t.start()


def get_active_model_name():
    is_running, _ = get_pid_status(os.path.join(STATE_DIR, "llama.pid"))
    if not is_running:
        return None
    config = load_config()
    port = int(config.get("LLAMA_PORT", 8080))
    return query_active_model(port)


_prev_cpu_stat = {"idle": 0.0, "total": 0.0, "last_pct": 0.0}
_cpu_lock = threading.Lock()


def get_system_cpu():
    """Calcula el uso de CPU comparando con la lectura previa de /proc/stat (con fallback ps para Termux)"""
    global _prev_cpu_stat
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        parts = line.split()
        idle = float(parts[4]) + float(parts[5])
        non_idle = float(parts[1]) + float(parts[2]) + float(parts[3]) + float(parts[6]) + float(parts[7]) + float(parts[8])
        total = idle + non_idle

        with _cpu_lock:
            total_diff = total - _prev_cpu_stat["total"]
            idle_diff = idle - _prev_cpu_stat["idle"]
            if _prev_cpu_stat["total"] > 0 and total_diff > 0:
                pct = round(max(0.0, min(100.0, (total_diff - idle_diff) / total_diff * 100.0)), 1)
                _prev_cpu_stat = {"idle": idle, "total": total, "last_pct": pct}
                return pct
            else:
                _prev_cpu_stat["idle"] = idle
                _prev_cpu_stat["total"] = total
                return _prev_cpu_stat["last_pct"]
    except Exception:
        # Fallback para Android / Termux donde SELinux restringe /proc/stat
        try:
            res = subprocess.run(["ps", "-eo", "%cpu"], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0:
                total_cpu = 0.0
                for line in res.stdout.splitlines()[1:]:
                    try:
                        total_cpu += float(line.strip())
                    except ValueError:
                        pass
                cores = max(1, os.cpu_count() or 4)
                return round(min(100.0, total_cpu / cores), 1)
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
                    temp_path = os.path.join(thermal_zones, zone, "temp")
                    if os.path.exists(temp_path):
                        with open(temp_path, "r") as f:
                            temp_mc = int(f.read().strip())
                        if temp_mc > 1000:
                            return round(temp_mc / 1000.0, 1)
                        elif temp_mc > 0:
                            return round(float(temp_mc), 1)
    except Exception:
        pass
    return None

def get_disk_usage():
    """Obtiene uso de disco de la partición donde reside el proyecto (compatible con Termux /data y Linux)"""
    try:
        stat = os.statvfs(WORKSPACE_DIR)
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
    """Obtiene bytes recibidos/enviados y calcula rate (KB/s) soportando Ethernet, Wi-Fi y USB Tethering"""
    global _prev_net_io
    try:
        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()
        for line in lines:
            if any(k in line for k in ("eth", "enp", "ens", "wlan", "wlp", "rndis", "usb")):
                parts = line.replace(":", " ").split()
                if len(parts) >= 10:
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    if rx_bytes == 0 and tx_bytes == 0:
                        continue
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
                    if (name.startswith(("sd", "vd", "mmcblk")) and not name[-1].isdigit()) or name in ("nvme0n1", "mmcblk0"):
                        total_read += int(parts[5]) * 512
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
    """Obtiene load average 1, 5, 15 minutos con fallback os.getloadavg()"""
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
        return {
            "load1": round(float(parts[0]), 2),
            "load5": round(float(parts[1]), 2),
            "load15": round(float(parts[2]), 2)
        }
    except Exception:
        try:
            l1, l5, l15 = os.getloadavg()
            return {"load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2)}
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

# --- RING BUFFER DE MÉTRICAS Y CACHÉ DE ESTADO ---

METRICS_HISTORY = []
MAX_HISTORY = 300  # ~25 min a intervalos de 5 segundos

_state_lock = threading.Lock()
_latest_hardware = None
_cached_nodes = {
    "ips": [],
    "details": [],
    "subnet": "",
    "local_ip": "127.0.0.1",
    "last_scan": 0.0
}


def refresh_nodes_cache(config=None):
    """Escanea los nodos RPC y actualiza la caché en memoria."""
    if config is None:
        config = load_config()
    local_ip, subnet = get_local_ip_and_subnet(config)
    rpc_port = int(config.get("RPC_PORT", 50052))
    ips, details = scan_network_rpc_detailed(
        subnet,
        rpc_port,
        custom_nodes=config.get("CUSTOM_NODES", ""),
        excluded_nodes=config.get("EXCLUDED_NODES", ""),
        local_ip=local_ip
    )
    with _state_lock:
        _cached_nodes["ips"] = ips
        _cached_nodes["details"] = details
        _cached_nodes["subnet"] = subnet
        _cached_nodes["local_ip"] = local_ip
        _cached_nodes["last_scan"] = time.time()
    return ips, details, local_ip, subnet


def collect_metrics():
    """Recolecta una muestra de métricas y actualiza _latest_hardware y METRICS_HISTORY."""
    global _latest_hardware

    config = load_config()
    llama_port = int(config.get("LLAMA_PORT", 8080))
    rpc_port = int(config.get("RPC_PORT", 50052))

    llama_running, llama_pid = get_pid_status(
        os.path.join(STATE_DIR, "llama.pid"),
        orphan_pattern=f"llama-server.*--port {llama_port}"
    )
    rpc_running, rpc_pid = get_pid_status(
        os.path.join(STATE_DIR, "rpc.pid"),
        orphan_pattern=f"rpc-server.*-p {rpc_port}"
    )

    sys_cpu = get_system_cpu()
    sys_mem = get_system_mem()
    temp = get_cpu_temperature()
    load = get_load_avg()
    disk = get_disk_usage()
    disk_io = get_disk_io()
    net_io = get_network_io()

    llama_stats = get_process_stats(llama_pid) if llama_running else {"cpu": 0.0, "mem_mb": 0.0}
    rpc_stats = get_process_stats(rpc_pid) if rpc_running else {"cpu": 0.0, "mem_mb": 0.0}
    llama_uptime = get_process_uptime(llama_pid) if llama_running else 0

    hw_snapshot = {
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
                "cpu": llama_stats["cpu"],
                "mem_mb": llama_stats["mem_mb"]
            },
            "rpc_server": {
                "running": rpc_running,
                "pid": rpc_pid,
                "cpu": rpc_stats["cpu"],
                "mem_mb": rpc_stats["mem_mb"]
            }
        },
        "temperature": temp,
        "disk": disk,
        "network": net_io,
        "load_avg": load
    }

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

    with _state_lock:
        _latest_hardware = hw_snapshot
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
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        path = self.path.split('?')[0]
        if path == "/":
            path = "/index.html"

        file_path = os.path.join(WORKSPACE_DIR, "web" + path)
        real_file_path = os.path.realpath(file_path)
        real_web_dir = os.path.realpath(os.path.join(WORKSPACE_DIR, "web"))

        if not real_file_path.startswith(real_web_dir):
            self.send_error(403, "Forbidden")
            return

        if os.path.exists(real_file_path) and os.path.isfile(real_file_path):
            try:
                with open(real_file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                mime_type, _ = mimetypes.guess_type(real_file_path)
                if mime_type:
                    self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404, f"File Not Found: {path}")

    def handle_api_get(self):
        config = load_config()

        if self.path == "/api/status":
            llama_port = int(config.get("LLAMA_PORT", 8080))
            rpc_port = int(config.get("RPC_PORT", 50052))

            rpc_running, rpc_pid = get_pid_status(
                os.path.join(STATE_DIR, "rpc.pid"),
                orphan_pattern=f"rpc-server.*-p {rpc_port}"
            )
            llama_running, llama_pid = get_pid_status(
                os.path.join(STATE_DIR, "llama.pid"),
                orphan_pattern=f"llama-server.*--port {llama_port}"
            )

            # Check llama-server health quickly
            health_ok = False
            if llama_running:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/health", timeout=0.25) as response:
                        health_ok = response.status == 200
                except Exception:
                    pass

            active_model = get_active_model_name() if llama_running else None

            with _state_lock:
                hw = _latest_hardware
                active_workers = list(_cached_nodes["ips"])
                nodes_detail = list(_cached_nodes["details"])
                local_ip = _cached_nodes["local_ip"]
                subnet = _cached_nodes["subnet"]

            if not subnet:
                local_ip, subnet = get_local_ip_and_subnet(config)

            if hw is None:
                collect_metrics()
                with _state_lock:
                    hw = _latest_hardware

            # Ensure live running flags in hardware snapshot match instant check
            hw_copy = json.loads(json.dumps(hw))
            hw_copy["processes"]["llama_server"]["running"] = llama_running
            hw_copy["processes"]["llama_server"]["pid"] = llama_pid
            hw_copy["processes"]["rpc_server"]["running"] = rpc_running
            hw_copy["processes"]["rpc_server"]["pid"] = rpc_pid

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
                "nodes_detail": nodes_detail,
                "active_model": active_model,
                "hardware": hw_copy,
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
                        models_list.append({
                            "name": filename,
                            "size_bytes": stat.st_size,
                            "size_human": format_bytes(stat.st_size),
                            "modified": stat.st_mtime
                        })
            models_list.sort(key=lambda x: x["name"])
            self.send_json({"models": models_list})

        elif self.path == "/api/nodes":
            rpc_port = int(config.get("RPC_PORT", 50052))
            ips, details, local_ip, subnet = refresh_nodes_cache(config)
            self.send_json({
                "nodes": ips,
                "nodes_detail": details,
                "subnet": subnet,
                "local_ip": local_ip,
                "port": rpc_port
            })

        elif self.path.startswith("/api/logs"):
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
            with _state_lock:
                history_copy = list(METRICS_HISTORY)
            self.send_json({"history": history_copy})

        elif self.path == "/api/alerts/config":
            self.send_json(get_alert_config())

        elif self.path == "/api/alerts/check":
            with _state_lock:
                last_point = METRICS_HISTORY[-1] if METRICS_HISTORY else None
            if last_point:
                alerts = check_alerts(last_point)
                self.send_json({"alerts": alerts})
            else:
                self.send_json({"alerts": []})

        elif self.path == "/api/models/catalog":
            ram_gb = get_system_ram_gb()
            catalog = []
            catalog_filenames = set()
            for m in MODEL_CATALOG:
                item = dict(m)
                item["recommended"] = ram_gb >= m["ram_min_gb"]
                item["ram_available_gb"] = ram_gb
                item["downloaded"] = os.path.exists(os.path.join(MODEL_DIR, m["filename"]))
                catalog_filenames.add(m["filename"])
                with _download_lock:
                    dl_info = download_state.get(m["filename"])
                    if dl_info:
                        item["download_status"] = dict(dl_info)
                catalog.append(item)

            # Incluir también cualquier modelo .gguf local en models/ que no esté en el catálogo
            if os.path.exists(MODEL_DIR):
                for fname in sorted(os.listdir(MODEL_DIR)):
                    if fname.endswith(".gguf") and fname not in catalog_filenames:
                        fpath = os.path.join(MODEL_DIR, fname)
                        size_gb = round(os.path.getsize(fpath) / (1024 ** 3), 2)
                        ram_min = max(1, int(size_gb * 1.3) + 1)
                        catalog.insert(0, {
                            "id": fname,
                            "name": fname.replace(".gguf", ""),
                            "family": "Local / Personalizado",
                            "url": "",
                            "filename": fname,
                            "size_gb": size_gb,
                            "ram_min_gb": ram_min,
                            "recommended": ram_gb >= ram_min,
                            "ram_available_gb": ram_gb,
                            "downloaded": True,
                            "description": "Modelo GGUF local almacenado en tu carpeta models/.",
                            "speed": "Local",
                            "quality": "Personalizado",
                            "ctx": 8192,
                            "tags": ["local", "coding", "general"]
                        })

            # Ordenar para que los modelos ya descargados aparezcan primero
            catalog.sort(key=lambda x: (0 if x.get("downloaded") else 1))
            self.send_json({"catalog": catalog, "ram_gb": ram_gb})

        elif self.path == "/api/snippets":
            snippets_dir = os.path.join(WORKSPACE_DIR, "workspace_code")
            os.makedirs(snippets_dir, exist_ok=True)
            snippets = []
            for fname in sorted(os.listdir(snippets_dir)):
                fpath = os.path.join(snippets_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        stat = os.stat(fpath)
                        ext = os.path.splitext(fname)[1].lstrip(".") or "txt"
                        snippets.append({
                            "name": fname,
                            "filename": fname,
                            "language": ext,
                            "size": stat.st_size,
                            "size_bytes": stat.st_size,
                            "modified": stat.st_mtime,
                            "content": content
                        })
                    except Exception:
                        pass
            self.send_json({"snippets": snippets})

        elif self.path == "/api/tools/list":
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            tool_descriptions = {
                "llama-server": "Servidor HTTP/OpenAI principal con soporte RPC y WebUI",
                "rpc-server": "Servidor Worker RPC para compartir CPU/GPU en red LAN",
                "ggml-rpc-server": "Binario nativo ggml-rpc-server de llama.cpp",
                "llama-cli": "Cliente de inferencia e interacción directa por consola",
                "llama-bench": "Benchmark nativo C++ de velocidad (Prompt Processing y Token Generation)",
                "llama-batched-bench": "Benchmark de inferencia por lotes y concurrencia de contextos",
                "llama-tokenize": "Tokenizador exacto para contar e inspeccionar tokens de cualquier modelo GGUF",
                "llama-quantize": "Cuantizador y recuantizador de modelos GGUF (Q4_K_M, Q5_K_M, Q8_0, etc.)",
                "llama-fit-params": "Calcula los parámetros óptimos (-c, -ngl) según la memoria disponible",
                "llama-gguf-hash": "Calcula y verifica hashes xxh64/SHA256 de cada tensor en un archivo GGUF",
                "llama-gguf-split": "Divide o une archivos .gguf grandes en fragmentos (ideal para FAT32/Android)",
                "llama-gguf": "Inspector y manipulador de cabeceras de archivos GGUF",
                "llama-perplexity": "Evalúa la perplejidad (calidad lingüística) de un modelo sobre un corpus",
                "llama-imatrix": "Calcula matrices de importancia para cuantizaciones de ultra baja pérdida",
                "llama-embedding": "Extrae vectores de embeddings semánticos de textos",
                "llama-speculative": "Inferencia acelerada mediante decodificación especulativa (modelo draft + target)",
                "llama-mtmd-cli": "Inferencia multimodal (texto + imagen/audio)",
                "llama-llava-cli": "Inferencia visual con modelos LLaVA",
                "llama-qwen2vl-cli": "Inferencia visual con modelos Qwen2-VL",
                "llama-gemma3-cli": "Inferencia multimodal con modelos Gemma 3",
                "llama-tts": "Síntesis de voz (Text-to-Speech) con modelos compatibles",
                "llama-retrieval": "Búsqueda semántica RAG sobre documentos con embeddings",
                "llama-export-lora": "Fusiona adaptadores LoRA en un modelo base GGUF",
                "llama-cvector-generator": "Generador de vectores de control (Control Vectors)",
                "llama-lookahead": "Decodificación Jacobi Lookahead sin modelo borrador"
            }
            tools = []
            if os.path.isdir(bin_dir):
                for entry in sorted(os.listdir(bin_dir)):
                    full = os.path.join(bin_dir, entry)
                    if os.path.isfile(full) and os.access(full, os.X_OK) and not entry.startswith("lib"):
                        tools.append({
                            "name": entry,
                            "description": tool_descriptions.get(entry, "Herramienta nativa compilada de la suite llama.cpp"),
                            "size_human": format_bytes(os.path.getsize(full))
                        })
            self.send_json({"tools": tools, "count": len(tools)})

        elif self.path == "/api/tools/slots":
            llama_port = int(config.get("LLAMA_PORT", 8080))
            slots_data = []
            props_data = {}
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/slots", timeout=1.0) as r:
                    slots_data = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/props", timeout=1.0) as r:
                    props_data = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
            self.send_json({"success": True, "slots": slots_data, "props": props_data})

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

                updates = {}
                for param in ["threads", "ctx_size", "batch_size", "llama_port", "rpc_port", "ngl", "kv_cache_type", "rpc_cache", "custom_nodes", "excluded_nodes"]:
                    val = payload.get(param)
                    if val is not None:
                        updates[param.upper()] = str(val)
                if updates:
                    save_config(updates)
                    config = load_config()

                # Sincronizar opencode.json automáticamente
                sync_opencode_json(
                    model_name=model_name,
                    llama_port=int(config.get("LLAMA_PORT", 8080)),
                    ctx_size=int(config.get("CTX_SIZE", 4096))
                )

                env = os.environ.copy()
                env["MODEL"] = model_name

                try:
                    llama_file = os.path.join(STATE_DIR, "llama.pid")
                    llama_running, llama_pid = get_pid_status(llama_file)
                    if llama_running and llama_pid:
                        try:
                            os.kill(llama_pid, 15)
                            time.sleep(0.8)
                        except Exception:
                            pass

                    proc = subprocess.Popen(
                        ["./cluster.sh", "server"],
                        cwd=WORKSPACE_DIR,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setpgrp
                    )

                    threading.Thread(target=lambda: (time.sleep(2.5), refresh_nodes_cache()), daemon=True).start()

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
                    threading.Thread(target=refresh_nodes_cache, daemon=True).start()
                    self.send_json({
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)

            elif action == "start_worker":
                try:
                    result = subprocess.run(
                        ["./cluster.sh", "worker", "-d"],
                        cwd=WORKSPACE_DIR,
                        capture_output=True,
                        text=True
                    )
                    threading.Thread(target=refresh_nodes_cache, daemon=True).start()
                    self.send_json({
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)

            elif action == "stop_worker":
                rpc_port = int(config.get("RPC_PORT", 50052))
                rpc_file = os.path.join(STATE_DIR, "rpc.pid")
                rpc_running, rpc_pid = get_pid_status(rpc_file, orphan_pattern=f"rpc-server.*-p {rpc_port}")
                if rpc_running and rpc_pid:
                    try:
                        os.kill(rpc_pid, 15)
                        if os.path.exists(rpc_file):
                            os.remove(rpc_file)
                        threading.Thread(target=refresh_nodes_cache, daemon=True).start()
                        self.send_json({"success": True, "message": f"Worker detenido (PID {rpc_pid})"})
                    except Exception as e:
                        self.send_json({"success": False, "error": str(e)}, status=500)
                else:
                    if os.path.exists(rpc_file):
                        os.remove(rpc_file)
                    self.send_json({"success": False, "error": "El worker no está activo"})

            else:
                self.send_json({"success": False, "error": f"Unknown action: {action}"}, status=400)

        elif self.path == "/api/settings":
            updates = {}
            for param in [
                "threads", "ctx_size", "batch_size", "llama_port", "rpc_port",
                "cluster_subnet", "ngl", "kv_cache_type", "rpc_cache",
                "custom_nodes", "excluded_nodes"
            ]:
                val = payload.get(param)
                if val is not None:
                    if isinstance(val, bool):
                        updates[param.upper()] = "true" if val else "false"
                    else:
                        updates[param.upper()] = str(val).strip()

            if updates:
                success = save_config(updates)
                new_cfg = load_config()
                sync_opencode_json(
                    model_name=get_active_model_name(),
                    llama_port=int(new_cfg.get("LLAMA_PORT", 8080)),
                    ctx_size=int(new_cfg.get("CTX_SIZE", 4096))
                )
                threading.Thread(target=lambda: refresh_nodes_cache(new_cfg), daemon=True).start()
                self.send_json({"success": success, "config": new_cfg})
            else:
                self.send_json({"success": False, "error": "No settings provided"}, status=400)

        elif self.path == "/api/alerts/config":
            updates = {}
            for param in ["cpu_threshold", "ram_threshold", "temp_threshold"]:
                val = payload.get(param)
                if val is not None:
                    updates[f"ALERT_{param.upper()}"] = str(val)
            if "enabled" in payload:
                updates["ALERTS_ENABLED"] = "true" if payload["enabled"] else "false"
            if updates:
                success = save_config(updates)
                self.send_json({"success": success, "config": get_alert_config()})
            else:
                self.send_json({"success": False, "error": "No alert settings provided"}, status=400)

        elif self.path == "/api/models/download":
            model_url = (payload.get("url") or "").strip()
            model_name = (payload.get("name") or "").strip()
            if not model_url:
                self.send_json({"success": False, "error": "URL es requerida"}, status=400)
                return
            if not model_name:
                model_name = model_url.split("?")[0].rstrip("/").split("/")[-1]
            model_name = model_name.replace("/", "_").replace("\\", "_")
            if not model_name.endswith(".gguf"):
                model_name += ".gguf"
            dest_path = os.path.join(MODEL_DIR, model_name)
            if os.path.exists(dest_path):
                self.send_json({"success": False, "error": f"El modelo {model_name} ya existe"}, status=409)
                return
            start_model_download(model_url, model_name)
            self.send_json({"success": True, "filename": model_name, "message": f"Descargando {model_name}..."})

        elif self.path == "/api/models/download/progress":
            with _download_lock:
                dl_copy = {k: dict(v) for k, v in download_state.items()}
            self.send_json({"downloads": dl_copy})

        elif self.path == "/api/models/download/cancel":
            model_name = payload.get("name")
            if not model_name:
                self.send_json({"success": False, "error": "name is required"}, status=400)
                return
            cancelled = cancel_model_download(model_name)
            self.send_json({"success": cancelled, "message": "Cancelando descarga..." if cancelled else "No hay descarga activa"})

        elif self.path == "/api/models/delete":
            model_name = payload.get("name")
            if not model_name:
                self.send_json({"success": False, "error": "name is required"}, status=400)
                return
            model_name = os.path.basename(model_name)
            model_path = os.path.join(MODEL_DIR, model_name)
            if not os.path.exists(model_path):
                self.send_json({"success": False, "error": "Modelo no encontrado"}, status=404)
                return
            try:
                os.remove(model_path)
                self.send_json({"success": True, "message": f"Modelo {model_name} eliminado"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/snippets/save":
            snippets_dir = os.path.join(WORKSPACE_DIR, "workspace_code")
            os.makedirs(snippets_dir, exist_ok=True)
            filename = os.path.basename((payload.get("filename") or "snippet.py").strip())
            content = payload.get("content") or ""
            if not filename:
                self.send_json({"success": False, "error": "Nombre de archivo inválido"}, status=400)
                return
            dest = os.path.join(snippets_dir, filename)
            try:
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)
                self.send_json({"success": True, "filename": filename, "path": dest})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/snippets/delete":
            snippets_dir = os.path.join(WORKSPACE_DIR, "workspace_code")
            filename = os.path.basename((payload.get("filename") or "").strip())
            target = os.path.join(snippets_dir, filename)
            if os.path.exists(target) and os.path.isfile(target):
                try:
                    os.remove(target)
                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status=500)
            else:
                self.send_json({"success": False, "error": "Archivo no encontrado"}, status=404)

        elif self.path == "/api/tools/tokenize":
            text = payload.get("text") or ""
            model_name = payload.get("model") or get_active_model_name()
            if not model_name and os.path.isdir(MODEL_DIR):
                ggufs = [f for f in sorted(os.listdir(MODEL_DIR)) if f.endswith(".gguf")]
                if ggufs:
                    model_name = ggufs[0]
            if not model_name:
                self.send_json({"success": False, "error": "No hay ningún modelo GGUF disponible"}, status=400)
                return
            model_path = os.path.join(MODEL_DIR, os.path.basename(model_name))
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            try:
                res = subprocess.run(
                    [os.path.join(bin_dir, "llama-tokenize"), "-m", model_path, "-p", text],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=15
                )
                tokens = []
                for line in res.stdout.splitlines():
                    if "->" in line:
                        tid, piece = line.split("->", 1)
                        tokens.append({"id": tid.strip(), "piece": piece.strip().strip("'")})
                self.send_json({
                    "success": res.returncode == 0,
                    "count": len(tokens),
                    "tokens": tokens,
                    "raw": res.stdout
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/tools/native-bench":
            model_name = payload.get("model") or get_active_model_name()
            if not model_name and os.path.isdir(MODEL_DIR):
                ggufs = [f for f in sorted(os.listdir(MODEL_DIR)) if f.endswith(".gguf")]
                if ggufs:
                    model_name = ggufs[0]
            if not model_name:
                self.send_json({"success": False, "error": "Selecciona o descarga un modelo primero"}, status=400)
                return
            model_path = os.path.join(MODEL_DIR, os.path.basename(model_name))
            threads_arg = str(payload.get("threads") or config.get("THREADS", "2")).strip()
            n_prompt = int(payload.get("n_prompt", 32))
            n_gen = int(payload.get("n_gen", 32))
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            try:
                res = subprocess.run(
                    [
                        os.path.join(bin_dir, "llama-bench"),
                        "-m", model_path,
                        "-p", str(n_prompt),
                        "-n", str(n_gen),
                        "-t", threads_arg,
                        "-r", "1",
                        "-o", "json"
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=90
                )
                parsed = []
                try:
                    parsed = json.loads(res.stdout)
                except Exception:
                    pass
                self.send_json({
                    "success": res.returncode == 0,
                    "results": parsed,
                    "raw_stdout": res.stdout,
                    "raw_stderr": res.stderr
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/tools/fit-params":
            model_name = payload.get("model") or get_active_model_name()
            if not model_name and os.path.isdir(MODEL_DIR):
                ggufs = [f for f in sorted(os.listdir(MODEL_DIR)) if f.endswith(".gguf")]
                if ggufs:
                    model_name = ggufs[0]
            if not model_name:
                self.send_json({"success": False, "error": "No hay modelo GGUF disponible"}, status=400)
                return
            model_path = os.path.join(MODEL_DIR, os.path.basename(model_name))
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            try:
                res = subprocess.run(
                    [os.path.join(bin_dir, "llama-fit-params"), "-m", model_path],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=20
                )
                self.send_json({
                    "success": res.returncode == 0,
                    "fitted_args": res.stdout.strip(),
                    "logs": res.stderr[-1500:] if res.stderr else ""
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/tools/gguf-info":
            model_name = payload.get("model") or get_active_model_name()
            if not model_name and os.path.isdir(MODEL_DIR):
                ggufs = [f for f in sorted(os.listdir(MODEL_DIR)) if f.endswith(".gguf")]
                if ggufs:
                    model_name = ggufs[0]
            if not model_name:
                self.send_json({"success": False, "error": "No hay modelo GGUF disponible"}, status=400)
                return
            model_path = os.path.join(MODEL_DIR, os.path.basename(model_name))
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            try:
                res = subprocess.run(
                    [os.path.join(bin_dir, "llama-gguf-hash"), model_path],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30
                )
                lines = res.stdout.strip().splitlines()
                self.send_json({
                    "success": res.returncode == 0,
                    "total_tensors": max(0, len(lines) - 1),
                    "model_hash": lines[-1] if lines else "",
                    "preview": "\n".join(lines[:15] + (["..."] if len(lines) > 20 else []) + lines[-5:])
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/tools/quantize":
            model_name = payload.get("model")
            quant_type = (payload.get("quant_type") or "Q4_K_M").strip()
            if not model_name:
                self.send_json({"success": False, "error": "Selecciona un modelo origen"}, status=400)
                return
            src_path = os.path.join(MODEL_DIR, os.path.basename(model_name))
            base_no_ext = os.path.splitext(os.path.basename(model_name))[0]
            dst_name = f"{base_no_ext}-{quant_type}.gguf"
            dst_path = os.path.join(MODEL_DIR, dst_name)
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            threads = str(config.get("THREADS", "2"))
            try:
                res = subprocess.run(
                    [
                        os.path.join(bin_dir, "llama-quantize"),
                        "--allow-requantize",
                        src_path,
                        dst_path,
                        quant_type,
                        threads
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=300
                )
                self.send_json({
                    "success": res.returncode == 0,
                    "output_model": dst_name,
                    "stdout": (res.stdout + "\n" + res.stderr)[-2500:]
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/tools/run":
            tool_name = os.path.basename((payload.get("tool") or "").strip())
            raw_args = (payload.get("args") or "--help").strip()
            bin_dir = os.path.join(WORKSPACE_DIR, "bin")
            tool_path = os.path.join(bin_dir, tool_name)
            if not tool_name or not os.path.exists(tool_path) or tool_name.startswith("lib"):
                self.send_json({"success": False, "error": f"Herramienta no encontrada: {tool_name}"}, status=404)
                return
            import shlex
            args_list = shlex.split(raw_args) if raw_args else ["--help"]
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"
            try:
                res = subprocess.run(
                    [tool_path] + args_list,
                    cwd=WORKSPACE_DIR,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=45
                )
                combined = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                self.send_json({
                    "success": res.returncode == 0,
                    "returncode": res.returncode,
                    "output": combined[-8000:]
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)

        elif self.path == "/api/chat":
            # Proxy SSE stream hacia llama-server local con métricas timings_per_token activadas
            llama_port = int(config.get("LLAMA_PORT", 8080))
            url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"
            payload["timings_per_token"] = True
            payload["stream_options"] = {"include_usage": True}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=60.0) as resp:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    for raw_line in resp:
                        self.wfile.write(raw_line)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                try:
                    self.send_json({"error": str(e)}, status=502)
                except Exception:
                    pass

        elif self.path == "/api/benchmark":
            llama_port = int(config.get("LLAMA_PORT", 8080))
            url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"

            prompt = payload.get("prompt", "Escribe una historia corta sobre un cluster de computadoras en 3 párrafos.")
            max_tokens = int(payload.get("max_tokens", 150))

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

                with urllib.request.urlopen(req, timeout=30.0) as response:
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
    """Hilo que recolecta métricas de hardware cada 3s y escanea nodos RPC cada 12s."""
    get_system_cpu()
    time.sleep(0.1)
    collect_metrics()
    refresh_nodes_cache()

    tick = 0
    while True:
        time.sleep(3)
        tick += 1
        try:
            collect_metrics()
            if tick % 4 == 0:
                refresh_nodes_cache()
        except Exception as e:
            print(f"Error collecting metrics: {e}")


def run(port=PORT):
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)

    collector = threading.Thread(target=metrics_collector_thread, daemon=True)
    collector.start()

    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, DashboardAPIHandler)
    print("==================================================")
    print(" LLAMA.CPP CLUSTER DASHBOARD BACKEND INICIADO")
    print(f"   URL: http://localhost:{port}")
    print("   Servidor: ThreadingHTTPServer (No bloqueante)")
    print("   Monitoreo de métricas y caché de nodos activo")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor...")
        httpd.server_close()


if __name__ == '__main__':
    run()
