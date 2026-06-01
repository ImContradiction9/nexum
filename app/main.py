"""
Aplicação FastAPI principal.
Serve a UI HTML e expõe endpoints REST para todas as operações.
"""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .seed import seed
# Bootstrap (caminho do banco, backup, engine, sessão, get_db) vive em deps.py
# — compartilhado entre main.py e os routers, sem import circular.
from .deps import SessionLocal

# Seed na primeira execução
with SessionLocal() as s:
    seed(s)
    s.commit()


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
    dashboard, extrato, importar, diagnostico, cambio,
)
for _mod in (investimentos, metas, atualizacao, bancos, conciliacao, config,
             emprestimos, categorias, atribuicoes, regras, contas, faturas, transacoes,
             dashboard, extrato, importar, diagnostico, cambio):
    app.include_router(_mod.router)


# ===========================================================
# UI — serve a SPA
# ===========================================================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"v": BOOT_TIMESTAMP})


