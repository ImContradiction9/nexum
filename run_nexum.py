"""
Launcher do Nexum empacotado como .exe (PyInstaller).

Responsável por:
  1. Apontar o banco (data/financeiro.db) para uma pasta AO LADO do .exe
     — não dentro do bundle temporário, que é apagado ao sair.
  2. Subir o servidor uvicorn em background (sem reload, numa thread).
  3. Abrir o navegador em modo app (Chrome/Edge), com fallback ao padrão.
  4. Encerrar o servidor automaticamente quando o navegador for fechado
     — sem janela de controle. Detecta o fim do processo do navegador
     (modo app) ou, no fallback, a parada do heartbeat enviado pela página.

Rodar em dev:  python run_nexum.py
Empacotar:     ver Nexum.spec / build_exe.ps1
"""
import os
import shutil
import sys
import socket
import threading
import time
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. Pasta base e caminho do banco (ANTES de importar o app!)
# ---------------------------------------------------------------------------
def _pasta_base() -> Path:
    """Pasta do executável (frozen) ou da raiz do projeto (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _pasta_dados(base: Path) -> Path:
    """Decide onde os dados (banco + backups) devem viver.

    Prioridade:
      1. NEXUM_DATA_DIR (override explícito — power user / scripts).
      2. Modo portátil: existe `portable.txt` ao lado do exe → usa `<exe>/data`
         (pen drive, sem instalar; dados andam junto com o programa).
      3. Instalado (frozen): `%APPDATA%\\Nexum` — o exe pode estar em
         Program Files (só-leitura), então os dados NÃO podem ficar ao lado dele.
      4. Dev (não-frozen): `<raiz do projeto>/data`, como sempre.
    """
    override = os.environ.get("NEXUM_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if getattr(sys, "frozen", False):
        if (base / "portable.txt").exists():
            return base / "data"
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Nexum"

    return base / "data"


def _migrar_dados_antigos(data_dir: Path, base: Path) -> None:
    """Migração única: se a pasta nova não tem banco mas há um `data/` antigo
    ao lado do exe (ex.: usuário portátil que instalou e copiou a pasta), traz
    o banco e os backups pra cá. Não sobrescreve nada existente."""
    if (data_dir / "financeiro.db").exists():
        return
    antigo = base / "data"
    try:
        if antigo.resolve() == data_dir.resolve():
            return
    except Exception:
        return
    origem_db = antigo / "financeiro.db"
    if not origem_db.exists():
        return
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem_db, data_dir / "financeiro.db")
        backups_antigos = antigo / "backups"
        if backups_antigos.is_dir():
            shutil.copytree(backups_antigos, data_dir / "backups", dirs_exist_ok=True)
    except Exception:
        pass  # migração é best-effort; nunca deve impedir a abertura do app


BASE = _pasta_base()
DATA_DIR = _pasta_dados(BASE)
DATA_DIR.mkdir(parents=True, exist_ok=True)
_migrar_dados_antigos(DATA_DIR, BASE)
# deps.py lê FINANCEIRO_DB; definimos antes de qualquer import do app.
os.environ.setdefault("FINANCEIRO_DB", str(DATA_DIR / "financeiro.db"))

# PyInstaller em modo janela (console=False): sys.stdout/stderr são None.
# Várias libs (uvicorn faz `sys.stdout.isatty()`) quebram com isso. Redireciona
# para um arquivo de log em data/ — também serve pra diagnosticar erros.
if sys.stdout is None or sys.stderr is None:
    try:
        _logf = open(DATA_DIR / "nexum.log", "a", buffering=1,
                     encoding="utf-8", errors="replace")
    except Exception:
        _logf = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

try:
    PORTA_PADRAO = int(os.environ.get("NEXUM_PORT") or 8765)
except ValueError:
    PORTA_PADRAO = 8765
HOST = "127.0.0.1"          # usado para abrir o navegador e checar saúde (local)
# Escutamos em todas as interfaces para permitir acesso pelo celular na rede
# local. O acesso de fora do PC é barrado por padrão pelo middleware de rede
# (só passa com "Compartilhar na rede" ligado + PIN). Localhost sempre entra.
BIND_HOST = "0.0.0.0"

# Detecção de "navegador fechado" por CONEXÃO: a página mantém um EventSource
# (SSE) aberto em /api/stream. Enquanto houver ao menos uma conexão viva, o app
# fica de pé; quando a última cai (janela fechada), o servidor se encerra.
# Robusto: não depende do modelo de processos do navegador (handoff do Chrome)
# nem de timers de aba, que browsers limitam em segundo plano.
_conns = {"n": 0, "viu_alguem": False}  # nº de conexões vivas; já viu alguém?


# ---------------------------------------------------------------------------
# 2. Utilidades de rede
# ---------------------------------------------------------------------------
def _porta_livre(porta_inicial: int) -> int:
    """Acha uma porta livre a partir de porta_inicial."""
    for porta in range(porta_inicial, porta_inicial + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, porta))
                return porta
            except OSError:
                continue
    return porta_inicial


def _health_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _nexum_ja_rodando(porta: int) -> bool:
    """Detecta se já há um Nexum respondendo nessa porta (evita 2 instâncias)."""
    return _health_ok(f"http://{HOST}:{porta}/api/health")


# ---------------------------------------------------------------------------
# 3. Servidor uvicorn
# ---------------------------------------------------------------------------
_server = None  # referência global para podermos encerrar


def _subir_servidor(porta: int):
    """Sobe o uvicorn numa thread, sem instalar signal handlers (não é main thread)."""
    global _server
    import asyncio
    import uvicorn
    from fastapi import Request
    from starlette.responses import StreamingResponse
    from app.main import app as fastapi_app

    # Endpoint SSE: a página mantém essa conexão aberta. Conta conexões vivas;
    # quando a janela fecha, o socket cai e o `finally` decrementa o contador.
    async def _stream(request: Request):
        _conns["n"] += 1
        _conns["viu_alguem"] = True

        async def gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    yield ": keep\n\n"          # comentário SSE (keepalive)
                    await asyncio.sleep(3)
            finally:
                _conns["n"] = max(0, _conns["n"] - 1)

        return StreamingResponse(gen(), media_type="text/event-stream")

    if not any(getattr(r, "path", None) == "/api/stream"
               for r in fastapi_app.router.routes):
        fastapi_app.add_api_route("/api/stream", _stream, methods=["GET"])

    # Registra a porta real no módulo de rede (a UI usa pra montar a URL do celular).
    try:
        from app import rede as rede_mod
        rede_mod.set_porta(porta)
    except Exception:
        pass

    config = uvicorn.Config(
        fastapi_app, host=BIND_HOST, port=porta,
        log_level="warning", access_log=False,
        log_config=None,  # evita o dictConfig do uvicorn (formatter colorido
                          # chama sys.stdout.isatty(), que quebra em modo janela)
    )
    _server = uvicorn.Server(config)
    _server.install_signal_handlers = lambda: None  # noqa: E731
    t = threading.Thread(target=_server.run, daemon=True)
    t.start()
    return t


def _esperar_servidor(porta: int, segundos: int = 40) -> bool:
    url = f"http://{HOST}:{porta}/api/health"
    for _ in range(segundos * 2):
        if _health_ok(url):
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# 4. Navegador
# ---------------------------------------------------------------------------
def _abrir_navegador(porta: int):
    """Abre o navegador. Devolve o processo (Popen) do navegador em modo app,
    ou None se caiu no fallback do navegador padrão (sem handle do processo)."""
    url = f"http://{HOST}:{porta}"
    perfil = str(DATA_DIR / "chrome-profile")

    candidatos = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for exe in candidatos:
        if os.path.isfile(exe):
            try:
                import subprocess
                # Perfil dedicado: a janela do app vira o processo "dono" e só
                # termina quando o usuário fecha a janela — é nisso que esperamos.
                return subprocess.Popen([
                    exe, f"--app={url}",
                    "--window-size=1400,900",
                    f"--user-data-dir={perfil}",
                    # Evita que o Chrome/Edge crie atalho na Área de Trabalho e
                    # rode a "primeira execução" ao usar um perfil dedicado novo.
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-pings",
                    "--disable-features=ProfileShortcutManager",
                ])
            except Exception:
                break
    # Fallback: navegador padrão do sistema (sem handle → usamos heartbeat).
    import webbrowser
    webbrowser.open(url)
    return None


# ---------------------------------------------------------------------------
# 5. Encerramento automático (sem janela): segue o navegador
# ---------------------------------------------------------------------------
def _encerrar():
    global _server
    if _server is not None:
        _server.should_exit = True
    # dá um instante pro uvicorn fechar e força a saída do processo
    time.sleep(0.3)
    os._exit(0)


def _vigia_conexoes(espera_inicial: int = 120, carencia: int = 6):
    """Encerra o servidor quando a última janela do navegador fecha.

    - Aguarda até `espera_inicial`s pela 1ª conexão SSE (página carregar).
      Se ninguém conectar, encerra (a página não abriu).
    - Depois, encerra se ficar `carencia`s sem nenhuma conexão viva. A carência
      cobre reload/navegação (a conexão cai e volta em ~1s) sem derrubar o app.
    """
    try:
        from app import rede as rede_mod
    except Exception:
        rede_mod = None

    def _compartilhando() -> bool:
        return bool(rede_mod and rede_mod.compartilhando())

    inicio = time.monotonic()
    while not _conns["viu_alguem"]:
        if _compartilhando():
            break  # ligou compartilhamento antes mesmo de abrir a janela: segue de pé
        if time.monotonic() - inicio > espera_inicial:
            _encerrar()
            return
        time.sleep(1)
    zero_desde = None
    while True:
        # Enquanto estiver compartilhando na rede, NÃO encerra mesmo sem janela
        # aberta no PC — o celular precisa que o servidor continue de pé.
        if _compartilhando():
            zero_desde = None
        elif _conns["n"] <= 0:
            if zero_desde is None:
                zero_desde = time.monotonic()
            elif time.monotonic() - zero_desde > carencia:
                _encerrar()
                return
        else:
            zero_desde = None
        time.sleep(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _selftest():
    """
    Modo de diagnóstico (NEXUM_SELFTEST=1): valida que o ambiente empacotado
    consegue importar pypdfium2 (binário nativo) e toda a cadeia de parsers,
    e que a extração de PDF funciona. Escreve o resultado em data/_selftest.txt
    e sai. Usado para testar o .exe sem abrir janela/navegador.
    """
    res = DATA_DIR / "_selftest.txt"
    linhas = []
    ok = True
    try:
        import pypdfium2 as pdfium
        linhas.append(f"pypdfium2 import OK (pdfium {pdfium.PdfiumError.__module__})")
    except Exception as e:
        ok = False
        linhas.append(f"pypdfium2 FALHOU: {e}")
    try:
        from app.parsers import parse_fatura  # noqa: F401
        from app.parsers.pdf_text import extrair_texto  # noqa: F401
        linhas.append("cadeia de parsers import OK")
    except Exception as e:
        ok = False
        linhas.append(f"parsers FALHOU: {e}")
    # Se houver um PDF de teste ao lado do exe, tenta extrair.
    teste_pdf = BASE / "_selftest.pdf"
    if teste_pdf.exists():
        try:
            from app.parsers.pdf_text import extrair_texto
            txt = extrair_texto(str(teste_pdf), layout=True)
            linhas.append(f"extração OK: {len(txt)} chars")
        except Exception as e:
            ok = False
            linhas.append(f"extração FALHOU: {e}")
    linhas.insert(0, "SELFTEST OK" if ok else "SELFTEST FALHOU")
    res.write_text("\n".join(linhas), encoding="utf-8")
    os._exit(0 if ok else 1)


def main():
    if os.environ.get("NEXUM_SELFTEST") == "1":
        _selftest()
        return

    # Se já há um Nexum rodando na porta padrão, só abre o navegador.
    if _nexum_ja_rodando(PORTA_PADRAO):
        _abrir_navegador(PORTA_PADRAO)
        return

    porta = _porta_livre(PORTA_PADRAO)
    _subir_servidor(porta)
    if not _esperar_servidor(porta):
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("Nexum", "O servidor não iniciou a tempo.")
        except Exception:
            print("Erro: o servidor não iniciou a tempo.")
        os._exit(1)

    if os.environ.get("NEXUM_NO_BROWSER") != "1":
        _abrir_navegador(porta)
    # Sem janela de controle: o servidor segue de pé enquanto a página mantiver
    # a conexão SSE aberta; encerra sozinho quando a última janela fechar.
    _vigia_conexoes()


if __name__ == "__main__":
    main()
