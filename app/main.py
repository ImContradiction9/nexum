"""
Aplicação FastAPI principal.
Serve a UI HTML e expõe endpoints REST para todas as operações.
"""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .seed import seed
from . import rede as rede_mod
# Bootstrap (caminho do banco, backup, engine, sessão, get_db) vive em deps.py
# — compartilhado entre main.py e os routers, sem import circular.
from .deps import SessionLocal

# Seed na primeira execução
with SessionLocal() as s:
    seed(s)
    s.commit()

# Compartilhamento automático: se o usuário marcou "iniciar ao abrir" (rede_auto=1)
# e há PIN definido, já liga o compartilhamento na rede nesta inicialização.
try:
    from .database import Configuracao as _Cfg
    with SessionLocal() as _s:
        _auto = _s.query(_Cfg).filter(_Cfg.chave == "rede_auto").first()
        _pin = _s.query(_Cfg).filter(_Cfg.chave == "rede_pin_hash").first()
        if _auto and _auto.valor == "1" and _pin:
            rede_mod.ativar()
except Exception:
    pass


# === FastAPI ===
app = FastAPI(title="Nexum", version="1.0")

# Cache busting: timestamp do boot do servidor — força reload de assets a cada reinício
BOOT_TIMESTAMP = str(int(datetime.now().timestamp()))

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Routers por domínio (refactor incremental de main.py).
from .routers import (
    investimentos, metas, atualizacao, bancos, conciliacao, config,
    emprestimos, categorias, atribuicoes, regras, contas, faturas, transacoes,
    dashboard, extrato, importar, diagnostico, cambio, rede, exportar,
)
for _mod in (investimentos, metas, atualizacao, bancos, conciliacao, config,
             emprestimos, categorias, atribuicoes, regras, contas, faturas, transacoes,
             dashboard, extrato, importar, diagnostico, cambio, rede, exportar):
    app.include_router(_mod.router)


# ===========================================================
# Controle de acesso pela rede (acesso pelo celular)
# ===========================================================
# Localhost (o próprio PC) entra sempre, sem PIN. Aparelhos da rede só passam
# quando "Compartilhar na rede" está ligado E têm um cookie de sessão válido
# (obtido digitando o PIN em /rede/entrar). Caso contrário são barrados.
_ROTAS_LIVRES_REDE = ("/rede/entrar", "/rede/login", "/api/health")


@app.middleware("http")
async def _controle_rede(request: Request, call_next):
    host = request.client.host if request.client else None
    if rede_mod.eh_local(host):
        return await call_next(request)   # próprio PC: acesso total, sem PIN

    # Requisição veio de outro aparelho (rede).
    if not rede_mod.compartilhando():
        return JSONResponse({"detail": "Compartilhamento desligado."}, status_code=403)

    path = request.url.path
    if path in _ROTAS_LIVRES_REDE:
        return await call_next(request)

    if rede_mod.token_valido(request.cookies.get("nexum_rede")):
        return await call_next(request)

    # Sem sessão válida: API → 401; navegação → manda pro login.
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Não autenticado."}, status_code=401)
    return RedirectResponse(url="/rede/entrar", status_code=303)


# ===========================================================
# UI — serve a SPA
# ===========================================================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # no-store: a janela nativa (WebView2) não pode servir uma versão em cache da
    # SPA — senão pode mostrar dados/tela "velhos" após atualizar ou reimportar.
    resp = templates.TemplateResponse(request, "index.html", {"v": BOOT_TIMESTAMP})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


