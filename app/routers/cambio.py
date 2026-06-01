"""Endpoints de câmbio (cotação atual de moeda estrangeira → BRL).

GET  /api/cambio/status       → cotação automática (BCB), override manual e usada.
POST /api/cambio/sincronizar  → força atualizar a cotação no Banco Central.
POST /api/cambio/manual       → define/limpa o override manual {moeda, valor}.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import get_db
from .. import cambio as cambio_mod

router = APIRouter()


@router.get("/api/cambio/status")
def cambio_status(db: Session = Depends(get_db)):
    # Sincroniza de forma preguiçosa (só vai à rede se o cache estiver velho).
    try:
        cambio_mod.sincronizar(db)
    except Exception:
        pass
    return cambio_mod.status(db)


@router.post("/api/cambio/sincronizar")
def cambio_sincronizar(db: Session = Depends(get_db)):
    res = cambio_mod.sincronizar(db, forcar=True)
    res["status"] = cambio_mod.status(db)
    return res


@router.post("/api/cambio/manual")
def cambio_manual(dados: dict, db: Session = Depends(get_db)):
    """Define o override manual. {moeda:'USD', valor: 5.04} — valor vazio limpa."""
    moeda = (dados.get("moeda") or "USD").upper()
    cambio_mod.set_manual(db, moeda, dados.get("valor"))
    return cambio_mod.status(db)
