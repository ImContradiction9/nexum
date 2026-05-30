"""Endpoints de auto-atualização via GitHub Releases.

GET  /api/atualizacao/status   → diz se há versão nova (e se o app é instalado).
POST /api/atualizacao/instalar → baixa o NexumSetup.exe, lança um updater que
     reinstala em silêncio e reabre o Nexum, e encerra o app (libera o .exe).

O repositório do GitHub vem de: env NEXUM_UPDATE_REPO → config 'atualizacao_repo'.
"""
import os
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db, DB_PATH
from ..database import Configuracao
from .. import __version__
from .. import atualizacao as up

router = APIRouter()

CONFIG_REPO = "atualizacao_repo"


def _repo(db: Session) -> str:
    """Slug 'usuario/repo' do GitHub: env tem prioridade, senão config."""
    env = os.environ.get("NEXUM_UPDATE_REPO")
    if env:
        return env.strip()
    cfg = db.query(Configuracao).filter(Configuracao.chave == CONFIG_REPO).first()
    return (cfg.valor if cfg else "") or ""


def _instalado() -> bool:
    """Auto-instalação só faz sentido no .exe empacotado (frozen)."""
    return bool(getattr(sys, "frozen", False))


@router.get("/api/atualizacao/status")
def status(db: Session = Depends(get_db)):
    repo = _repo(db)
    info = up.verificar(__version__, repo)
    info["repo"] = repo
    info["instalado"] = _instalado()
    return info


@router.post("/api/atualizacao/instalar")
def instalar(db: Session = Depends(get_db)):
    if not _instalado():
        raise HTTPException(400, "Auto-instalação só funciona no app instalado (.exe).")
    info = up.verificar(__version__, _repo(db))
    if not info["tem_atualizacao"]:
        raise HTTPException(400, info.get("erro") or "Não há atualização disponível.")

    update_dir = Path(DB_PATH).parent / "update"
    setup = update_dir / "NexumSetup.exe"
    try:
        up.baixar(info["url_download"], setup)
    except Exception as e:
        raise HTTPException(502, f"Falha ao baixar o instalador: {e}")

    bat = up.escrever_updater_bat(setup, Path(sys.executable), update_dir / "update.bat")

    # Lança o updater destacado (sem janela) e agenda a saída do app.
    import subprocess
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    # 1s dá tempo da resposta HTTP voltar antes de matar o processo.
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True, "versao": info["versao_disponivel"]}
