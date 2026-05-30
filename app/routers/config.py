"""Configurações chave-valor. Extraído de main.py (refactor por domínio)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Configuracao

router = APIRouter()


@router.get("/api/config")
def listar_config(db: Session = Depends(get_db)):
    """Retorna todas as configurações chave-valor."""
    return {c.chave: c.valor for c in db.query(Configuracao).all()}


@router.put("/api/config/{chave}")
def salvar_config(chave: str, dados: dict, db: Session = Depends(get_db)):
    """Cria ou atualiza uma configuração."""
    valor = dados.get("valor", "")
    cfg = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    if cfg is None:
        cfg = Configuracao(chave=chave, valor=valor)
        db.add(cfg)
    else:
        cfg.valor = valor
    db.commit()
    return {"chave": chave, "valor": valor}
