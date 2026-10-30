#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error
import time
import argparse

from cluster_core import (
    STATE_DIR,
    MODEL_DIR,
    MODEL_CATALOG,
    is_termux,
    get_system_ram_gb,
    load_config,
    get_pid_status,
    get_local_ip_and_subnet,
    scan_network_rpc_detailed,
    query_active_model,
    format_bytes,
    download_model_cli,
    ensure_dir,
)

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


def cmd_status():
    config = load_config()
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

    local_ip, subnet = get_local_ip_and_subnet(config)

    health_status = f"{C_RED}DETENIDO{C_RESET}"
    if llama_running:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{llama_port}/health", timeout=0.5) as response:
                if response.status == 200:
                    health_status = f"{C_GREEN}ACTIVO (OK){C_RESET}"
                else:
                    health_status = f"{C_YELLOW}CARGANDO...{C_RESET}"
        except Exception:
            health_status = f"{C_YELLOW}CARGANDO / ESPERANDO MODELO{C_RESET}"

    active_model = query_active_model(llama_port) if llama_running else None
    env_label = "Android Termux" if is_termux() else "Linux"

    print(f"\n{C_CYAN}{C_BOLD}=== ESTADO DEL CLUSTER ({env_label}) ==={C_RESET}\n")
    print(f"  {C_BOLD}IP Local:{C_RESET}       {local_ip} (Subred: {subnet}.0/24)")
    print(f"  {C_BOLD}rpc-server:{C_RESET}     " + (f"{C_GREEN}ACTIVO{C_RESET} (PID {rpc_pid}, Puerto {rpc_port})" if rpc_running else f"{C_RED}DETENIDO{C_RESET}"))
    print(f"  {C_BOLD}llama-server:{C_RESET}   " + (f"{C_GREEN}ACTIVO{C_RESET} (PID {llama_pid}, Puerto {llama_port})" if llama_running else f"{C_RED}DETENIDO{C_RESET}"))
    print(f"  {C_BOLD}Health API:{C_RESET}     {health_status}")
    print(f"  {C_BOLD}Modelo Activo:{C_RESET}  " + (f"{C_PURPLE}{active_model}{C_RESET}" if active_model else "Ninguno"))

    print(f"\n{C_CYAN}Escaneando nodos RPC en la subred...{C_RESET}")
    start_time = time.time()
    _, detailed_nodes = scan_network_rpc_detailed(
        subnet,
        rpc_port,
        custom_nodes=config.get("CUSTOM_NODES", ""),
        excluded_nodes=config.get("EXCLUDED_NODES", ""),
        local_ip=local_ip
    )
    duration = time.time() - start_time

    print(f"  {C_BOLD}Nodos Encontrados:{C_RESET} {len(detailed_nodes)} (Escaneo en {duration:.2f}s)")
    for node in detailed_nodes:
        is_me = " (este dispositivo)" if node["is_local"] else ""
        custom_tag = " [manual]" if node["is_custom"] else ""
        print(f"    {C_GREEN}●{C_RESET} {node['ip']}:{node['port']}{is_me}{custom_tag} {C_DIM}({node['latency_ms']} ms){C_RESET}")
    print()


def cmd_list():
    print(f"\n{C_CYAN}{C_BOLD}=== MODELOS GGUF EN DISCO ({MODEL_DIR}) ==={C_RESET}\n")
    ensure_dir(MODEL_DIR)

    models_found = False
    for filename in sorted(os.listdir(MODEL_DIR)):
        if filename.endswith(".gguf"):
            full_path = os.path.join(MODEL_DIR, filename)
            size_human = format_bytes(os.path.getsize(full_path))
            print(f"  {C_GREEN}●{C_RESET} {C_BOLD}{filename}{C_RESET} ({size_human})")
            models_found = True

    if not models_found:
        print(f"  {C_YELLOW}No se encontraron modelos .gguf descargados.{C_RESET}")
        print(f"  Ejecuta {C_GREEN}python3 cluster-cli.py download{C_RESET} o {C_GREEN}./cluster.sh download{C_RESET} para descargar uno.")
    print()


def cmd_download(target=None):
    download_model_cli(target)


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

        with urllib.request.urlopen(req, timeout=60.0) as response:
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

    active_model = query_active_model(llama_port)
    if not active_model:
        print(f"\n{C_RED}✗ Llama-Server no responde en el puerto {llama_port}.{C_RESET}")
        print(f"  Por favor inicia el servidor ejecutando:")
        print(f"  {C_GREEN}./cluster.sh chat{C_RESET} o {C_GREEN}./cluster.sh server{C_RESET}\n")
        return

    print(f"\n{C_PURPLE}{C_BOLD}=== CHAT PLAYGROUND TERMINAL ==={C_RESET}")
    print(f"  {C_BOLD}Modelo:{C_RESET} {active_model}")
    print(f"  {C_BOLD}Endpoint:{C_RESET} {url}")
    print(f"  Comandos: {C_BOLD}/model{C_RESET} (cambiar modelo descargado), {C_BOLD}clear{C_RESET} (limpiar), {C_BOLD}salir{C_RESET}\n")

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

            if user_input.lower() in ['/model', '/models', 'modelo']:
                import subprocess
                subprocess.run(["./cluster.sh", "server"], cwd=os.path.dirname(os.path.abspath(__file__)))
                active_model = query_active_model(llama_port) or active_model
                print(f"\n{C_GREEN}✓ Modelo activo ahora: {C_BOLD}{active_model}{C_RESET}")
                continue

            if user_input.lower() == 'clear':
                messages = [messages[0]]
                print(f"{C_YELLOW}Historial de chat limpio.{C_RESET}")
                continue

            messages.append({"role": "user", "content": user_input})

            api_payload = {
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 512,
                "stream": True,
                "timings_per_token": True,
                "stream_options": {"include_usage": True}
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(api_payload).encode('utf-8'),
                headers={"Content-Type": "application/json"}
            )

            print(f"\n{C_PURPLE}{C_BOLD}IA > {C_RESET}", end="", flush=True)

            assistant_response = ""
            t_start = time.time()
            t_first = None
            tok_count = 0
            server_timings = None

            with urllib.request.urlopen(req, timeout=120.0) as response:
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
                            if chunk.get("timings"):
                                server_timings = chunk["timings"]
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                if t_first is None:
                                    t_first = time.time()
                                tok_count += 1
                                assistant_response += content
                                print(content, end="", flush=True)
                        except Exception:
                            pass
            t_end = time.time()
            print()

            # Mostrar métricas de velocidad de generación de tokens
            gen_tps = (
                server_timings.get("predicted_per_second")
                if server_timings and server_timings.get("predicted_per_second")
                else (tok_count / max(0.05, t_end - (t_first or t_start)))
            )
            ttft_ms = (
                int(server_timings.get("prompt_ms"))
                if server_timings and server_timings.get("prompt_ms")
                else int(((t_first or t_end) - t_start) * 1000)
            )
            final_tokens = (server_timings.get("predicted_n") if server_timings else None) or tok_count
            print(f"{C_DIM}  [⚡ {C_GREEN}{gen_tps:.2f} tokens/s{C_RESET}{C_DIM} | TTFT: {ttft_ms} ms | {final_tokens} tokens | {t_end - t_start:.2f}s]{C_RESET}")

            # Extraer bloques de código automáticamente a workspace_code/
            import re
            code_blocks = re.findall(r"```([a-zA-Z0-9_-]*)\n(.*?)```", assistant_response, re.DOTALL)
            if code_blocks:
                ws_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace_code")
                os.makedirs(ws_dir, exist_ok=True)
                ext_map = {"python": "py", "py": "py", "javascript": "js", "js": "js", "bash": "sh", "sh": "sh", "html": "html", "cpp": "cpp", "c": "c"}
                for idx_b, (lang_b, code_b) in enumerate(code_blocks, 1):
                    ext = ext_map.get(lang_b.lower().strip(), "txt")
                    fname = f"ultimo_chat_{idx_b}.{ext}"
                    fpath = os.path.join(ws_dir, fname)
                    with open(fpath, "w", encoding="utf-8") as f_out:
                        f_out.write(code_b.strip() + "\n")
                    print(f"  {C_CYAN}💾 Código guardado en:{C_RESET} workspace_code/{fname}")

            messages.append({"role": "assistant", "content": assistant_response})

        except KeyboardInterrupt:
            print(f"\n\n{C_YELLOW}Generación interrumpida. Escribe 'salir' para cerrar.{C_RESET}")
        except urllib.error.URLError:
            print(f"\n{C_RED}✗ Error: Se perdió la conexión con llama-server.{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}✗ Error de chat: {e}{C_RESET}\n")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Llama.cpp RPC Cluster Suite — CLI (Linux & Termux)",
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    subparsers.add_parser("status", help="Muestra el estado de los procesos y nodos del cluster")
    subparsers.add_parser("list", help="Lista los modelos GGUF descargados en models/")

    dl_parser = subparsers.add_parser("download", help="Descarga un modelo GGUF del catálogo o por URL")
    dl_parser.add_argument("target", nargs="?", default=None, help="ID del modelo, número de lista o URL .gguf")

    subparsers.add_parser("chat", help="Inicia una conversación interactiva con el modelo activo")

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
    elif args.command == "download":
        cmd_download(args.target)
    elif args.command == "chat":
        cmd_chat()
    elif args.command == "benchmark":
        cmd_benchmark(args.prompt, args.tokens)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
