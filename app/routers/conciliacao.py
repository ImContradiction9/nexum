"""Conciliação: sugestões (pagamentos de fatura, duplicatas) e aplicação.
Extraído de main.py (refactor por domínio)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import get_db
from ..conciliacao import (
    detectar_pagamentos_fatura, detectar_duplicatas, aplicar_conciliacao,
)

router = APIRouter()


@router.get("/api/conciliacao/sugestoes")
def sugestoes_conciliacao(db: Session = Depends(get_db)):
    pgtos = detectar_pagamentos_fatura(db)
    dups = detectar_duplicatas(db)
    return {
        "pagamentos_fatura": [
            {"transacao_id": s.transacao_id, "fatura_id": s.fatura_id,
             "tipo": s.tipo, "confianca": s.confianca, "motivo": s.motivo}
            for s in pgtos
        ],
        "duplicatas": [
            {"transacao_id": s.transacao_id, "transacao_b_id": s.transacao_b_id,
             "tipo": s.tipo, "confianca": s.confianca, "motivo": s.motivo}
            for s in dups
        ],
    }


@router.post("/api/conciliacao/aplicar")
def aplicar_sugestao(dados: dict, db: Session = Depends(get_db)):
    from ..conciliacao import SugestaoConciliacao
    sug = SugestaoConciliacao(
        transacao_id=dados["transacao_id"],
        transacao_b_id=dados.get("transacao_b_id"),
        fatura_id=dados.get("fatura_id"),
        tipo=dados["tipo"],
        confianca=dados.get("confianca", 1.0),
        motivo=dados.get("motivo", ""),
    )
    aplicar_conciliacao(db, sug, confirmar=True)
    db.commit()
    return {"ok": True}
