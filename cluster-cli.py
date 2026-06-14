#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error
import time
import argparse
import socket
import concurrent.futures

# Configuración
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE_DIR, ".state")
MODEL_DIR = os.path.join(WORKSPACE_DIR, "models")
CONF_FILE = os.path.join(WORKSPACE_DIR, "cluster.conf")

# Colores ANSI
C_RED = "\033[0;31m"
C_GREEN = "\033[0;32m"
C_YELLOW = "\033[1;33m"
C_BLUE = "\033[0;34m"
C_PURPLE = "\033[0;35m"
C_CYAN = "\033[0;36m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"

DEFAULTS = {
    "LLAMA_PORT": "8080",
    "RPC_PORT": "50052"
}

def load_config():
    config = DEFAULTS.copy()
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    return config

def get_pid_status(pid_file):
    if not os.path.exists(pid_file):
        return False, None
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, OSError):
        return False, None

def get_local_ip_and_subnet(config):
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

def query_active_model(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/props")
        with urllib.request.urlopen(req, timeout=0.5) as response:
            data = json.loads(response.read().decode())
            model_path = data.get("default_generation_settings", {}).get("model", "")
            if model_path:
                return os.path.basename(model_path)
    except Exception:
        pass
    return None

# --- COMANDOS ---

def cmd_status():
    config = load_config()
    llama_port = int(config.get("LLAMA_PORT", 8080))
    rpc_port = int(config.get("RPC_PORT", 50052))
    
    rpc_running, rpc_pid = get_pid_status(os.path.join(STATE_DIR, "rpc.pid"))
    llama_running, llama_pid = get_pid_status(os.path.join(STATE_DIR, "llama.pid"))
    
    local_ip, subnet = get_local_ip_and_subnet(config)
    
    # Check health
    health_status = f"{C_RED}DETENIDO{C_RESET}"
    if llama_running:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/health", timeout=0.5) as response:
                if response.status == 200:
                    health_status = f"{C_GREEN}ACTIVO (OK){C_RESET}"
                else:
                    health_status = f"{C_YELLOW}CARGANDO...{C_RESET}"
        except Exception:
            health_status = f"{C_YELLOW}CARGANDO / ERROR CONEXIÓN{C_RESET}"
            
    active_model = query_active_model(llama_port) if llama_running else None

    print(f"\n{C_CYAN}{C_BOLD}=== ESTADO DEL CLUSTER (CLI) ==={C_RESET}\n")
    print(f"  {C_BOLD}PC Local:{C_RESET}       {local_ip} (Subred: {subnet}.0/24)")
    print(f"  {C_BOLD}rpc-server:{C_RESET}     " + (f"{C_GREEN}ACTIVO{C_RESET} (PID {rpc_pid}, Puerto {rpc_port})" if rpc_running else f"{C_RED}DETENIDO{C_RESET}"))
    print(f"  {C_BOLD}llama-server:{C_RESET}   " + (f"{C_GREEN}ACTIVO{C_RESET} (PID {llama_pid}, Puerto {llama_port})" if llama_running else f"{C_RED}DETENIDO{C_RESET}"))
    print(f"  {C_BOLD}Health API:{C_RESET}     {health_status}")
    print(f"  {C_BOLD}Modelo Activo:{C_RESET}  " + (f"{C_PURPLE}{active_model}{C_RESET}" if active_model else "Ninguno"))
    
    print(f"\n{C_CYAN}Escaneando nodos RPC en la subred...{C_RESET}")
    start_time = time.time()
    nodes = scan_network_rpc(subnet, rpc_port)
    duration = time.time() - start_time
    
    print(f"  {C_BOLD}Nodos Encontrados:{C_RESET} {len(nodes)} (Escaneo en {duration:.2f}s)")
    for ip in nodes:
        is_me = " (este PC)" if ip == local_ip else ""
        print(f"    {C_GREEN}●{C_RESET} {ip}:{rpc_port}{is_me}")
    print()

def cmd_list():
    print(f"\n{C_CYAN}{C_BOLD}=== MODELOS GGUF DISPONIBLES ==={C_RESET}\n")
    if not os.path.exists(MODEL_DIR):
        print(f"  La carpeta 'models/' no existe.")
        return
        
    models_found = False
    for filename in sorted(os.listdir(MODEL_DIR)):
        if filename.endswith(".gguf"):
            full_path = os.path.join(MODEL_DIR, filename)
            size_bytes = os.path.getsize(full_path)
            # Format size
            size_human = ""
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    size_human = f"{size_bytes:.2f} {unit}"
                    break
                size_bytes /= 1024.0
            else:
                size_human = f"{size_bytes:.2f} TB"
                
            print(f"  {C_GREEN}●{C_RESET} {C_BOLD}{filename}{C_RESET} ({size_human})")
            models_found = True
            
    if not models_found:
        print(f"  {C_YELLOW}No se encontraron modelos .gguf en models/{C_RESET}")
        print(f"  Descarga un modelo y guárdalo en {MODEL_DIR}/")
    print()

def cmd_benchmark(prompt, max_tokens):
    config = load_config()
    llama_port = int(config.get("LLAMA_PORT", 8080))
    url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"
    
    print(f"\n{C_CYAN}{C_BOLD}=== EJECUTANDO TEST DE RENDIMIENTO ==={C_RESET}")
    print(f"  {C_BOLD}Prompt:{C_RESET} \"{prompt[:60]}...\"")
    print(f"  {C_BOLD}Tokens máx:{C_RESET} {max_tokens}")
    print(f"  {C_BOLD}Endpoint:{C_RESET} {url}\n")
    
    api_payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": True
    }
    
    req = urllib.request.Request(url, data=json.dumps(api_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    
    try:
        start_time = time.time()
        first_token_time = None
        tokens_count = 0
        
        print(f"{C_DIM}Iniciando inferencia y leyendo stream...{C_RESET}")
        
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
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            if first_token_time is None:
                                first_token_time = time.time()
                            tokens_count += 1
                    except Exception:
                        pass
                        
        end_time = time.time()
        
        if first_token_time is None:
            first_token_time = end_time
            
        total_duration = end_time - start_time
        prompt_eval_duration = first_token_time - start_time
        gen_duration = end_time - first_token_time
        
        tokens_per_sec = tokens_count / gen_duration if gen_duration > 0 else 0
        
        print(f"\n{C_GREEN}{C_BOLD}✓ Resultados del Benchmark:{C_RESET}")
        print(f"  ┌───────────────────────────┬──────────────────────────┐")
        print(f"  │ {C_BOLD}Métrica{C_RESET}                   │ {C_BOLD}Valor{C_RESET}                    │")
        print(f"  ├───────────────────────────┼──────────────────────────┤")
        print(f"  │ Latencia Primer Token     │ {int(prompt_eval_duration * 1000):>6} ms               │")
        print(f"  │ Tiempo de Generación      │ {gen_duration:>9.2f} s                │")
        print(f"  │ Duración Total            │ {total_duration:>9.2f} s                │")
        print(f"  │ Tokens Generados          │ {tokens_count:>6} tokens            │")
        print(f"  ├───────────────────────────┼──────────────────────────┤")
        print(f"  │ {C_GREEN}{C_BOLD}Velocidad Inferencia{C_RESET}      │ {C_GREEN}{C_BOLD}{tokens_per_sec:>9.2f} t/s{C_RESET}               │")
        print(f"  └───────────────────────────┴──────────────────────────┘\n")
        
    except urllib.error.URLError:
        print(f"{C_RED}✗ Error: No se puede conectar con llama-server en puerto {llama_port}.{C_RESET}")
        print("  ¿Iniciaste el servidor con './cluster.sh server' o './dashboard.sh start'?\n")
    except Exception as e:
        print(f"{C_RED}✗ Error durante el benchmark: {e}{C_RESET}\n")

def cmd_chat():
    config = load_config()
    llama_port = int(config.get("LLAMA_PORT", 8080))
    url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"
    
    # Verificar si el servidor corre
    active_model = query_active_model(llama_port)
    if not active_model:
        print(f"\n{C_RED}✗ Llama-Server no responde en el puerto {llama_port}.{C_RESET}")
        print(f"  Por favor inicia el servidor maestro ejecutando:")
        print(f"  {C_GREEN}./cluster.sh server{C_RESET}   (interactivo)")
        print(f"  o usa el panel web iniciando {C_GREEN}./dashboard.sh start{C_RESET}\n")
        return
        
    print(f"\n{C_PURPLE}{C_BOLD}=== CHAT PLAYGROUND TERMINAL ==={C_RESET}")
    print(f"  {C_BOLD}Modelo:{C_RESET} {active_model}")
    print(f"  {C_BOLD}Endpoint:{C_RESET} {url}")
    print(f"  Escribe {C_BOLD}salir{C_RESET} o {C_BOLD}clear{C_RESET} para salir/limpiar chat.\n")
    
    messages = [
        {"role": "system", "content": "Eres un asistente de IA útil y amigable. Respondes en español."}
    ]
    
    while True:
        try:
            user_input = input(f"\n{C_BLUE}{C_BOLD}Tú > {C_RESET}").strip()
            if not user_input:
                continue
                
            if user_input.lower() in ['salir', 'exit', 'quit']:
                print(f"\n{C_CYAN}¡Adiós!{C_RESET}\n")
                break
                
            if user_input.lower() == 'clear':
                messages = [messages[0]]
                print(f"{C_YELLOW}Historial de chat limpio.{C_RESET}")
                continue
                
            messages.append({"role": "user", "content": user_input})
            
            # Request payload
            api_payload = {
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 512,
                "stream": True
            }
            
            req = urllib.request.Request(
                url, 
                data=json.dumps(api_payload).encode('utf-8'), 
                headers={"Content-Type": "application/json"}
            )
            
            print(f"\n{C_PURPLE}{C_BOLD}IA > {C_RESET}", end="", flush=True)
            
            assistant_response = ""
            with urllib.request.urlopen(req, timeout=15.0) as response:
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
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                assistant_response += content
                                print(content, end="", flush=True)
                        except Exception:
                            pass
            print()
            messages.append({"role": "assistant", "content": assistant_response})
            
        except KeyboardInterrupt:
            print(f"\n\n{C_YELLOW}Chat interrumpido. Escribe 'salir' para cerrar.{C_RESET}")
        except urllib.error.URLError:
            print(f"\n{C_RED}✗ Error: Se perdió la conexión con llama-server.{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}✗ Error de chat: {e}{C_RESET}\n")
            break

# --- MAIN CLI RUNNER ---

def main():
    parser = argparse.ArgumentParser(
        description="Llama.cpp RPC Cluster Suite — CLI Companion",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")
    
    # Status command
    subparsers.add_parser("status", help="Muestra el estado de los procesos y nodos del cluster")
    
    # List command
    subparsers.add_parser("list", help="Lista los modelos GGUF descargados en models/")
    
    # Chat command
    subparsers.add_parser("chat", help="Inicia una conversación interactiva con el modelo activo")
    
    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Ejecuta una prueba de velocidad de inferencia")
    bench_parser.add_argument(
        "--prompt", 
        type=str, 
        default="Escribe una pequeña historia de 2 párrafos sobre inteligencia artificial.",
        help="Prompt de prueba"
    )
    bench_parser.add_argument(
        "--tokens", 
        type=int, 
        default=256,
        help="Número máximo de tokens a generar"
    )
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status()
    elif args.command == "list":
        cmd_list()
    elif args.command == "chat":
        cmd_chat()
    elif args.command == "benchmark":
        cmd_benchmark(args.prompt, args.tokens)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
