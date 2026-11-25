"""`findash app` e `findash demo`: sobe o servidor local (só 127.0.0.1) e abre o navegador."""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime

import httpx

from findash.config import Paths, utcnow

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) == 0


def _already_running(port: int) -> bool:
    try:
        response = httpx.get(f"http://{HOST}:{port}/api/meta", timeout=2.0)
        return response.status_code == 200 and "months" in response.json()
    except (httpx.HTTPError, ValueError):
        return False


def _log_to_file_without_console(paths: Paths) -> None:
    """Sob pythonw.exe (tarefa do Agendador, sem janela) não há console: as mensagens vão para um arquivo."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    stream = open(paths.logs_dir / "servidor.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def run(
    paths: Paths,
    *,
    demo: bool = False,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    clock: Callable[[], datetime] = utcnow,
) -> int:
    import uvicorn

    _log_to_file_without_console(paths)

    from findash.web.app import DIST_DIR, create_app

    url = f"http://{HOST}:{port}/"
    if _port_in_use(port):
        if _already_running(port):
            print(f"O painel já está aberto em {url}")
            if open_browser:
                webbrowser.open(url)
            return 0
        print(f"A porta {port} está ocupada por outro programa. Use --porta OUTRA")
        return 1
    if not (DIST_DIR / "index.html").exists():
        print(
            "Aviso: o frontend ainda não foi compilado (frontend/dist). Rode: npm --prefix frontend ci && "
            "npm --prefix frontend run build"
        )
    app = create_app(paths, demo=demo, clock=clock)
    print(f"Painel {'(DEMONSTRAÇÃO, dados sintéticos) ' if demo else ''}em {url}  —  Ctrl+C para fechar")
    if open_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
