"""Configurações chave-valor. Extraído de main.py (refactor por domínio)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Configuracao
from .rede import _so_local

router = APIRouter()

# Chaves que nunca saem na listagem (ex.: hash do PIN da rede — um aparelho da
# rede com sessão válida poderia forçar o PIN offline a partir do hash).
_CHAVES_OCULTAS = {"rede_pin_hash"}


@router.get("/api/config")
def listar_config(db: Session = Depends(get_db)):
    """Retorna todas as configurações chave-valor."""
    return {c.chave: c.valor for c in db.query(Configuracao).all()
            if c.chave not in _CHAVES_OCULTAS}


@router.put("/api/config/{chave}")
def salvar_config(chave: str, dados: dict, request: Request, db: Session = Depends(get_db)):
    """Cria ou atualiza uma configuração. Só do próprio PC: um aparelho da rede
    não pode mexer em config (ex.: trocar o repo de atualização, PIN, etc.)."""
    _so_local(request)
    valor = dados.get("valor", "")
    cfg = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    if cfg is None:
        cfg = Configuracao(chave=chave, valor=valor)
        db.add(cfg)
    else:
        cfg.valor = valor
    db.commit()
    return {"chave": chave, "valor": valor}
