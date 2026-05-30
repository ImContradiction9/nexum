"""Regras de auto-categorização por palavra-chave: CRUD. Extraído de main.py."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Regra

router = APIRouter()


@router.get("/api/regras")
def listar_regras(db: Session = Depends(get_db)):
    items = db.query(Regra).options(
        joinedload(Regra.categoria), joinedload(Regra.atribuicao)
    ).filter(Regra.ativa == True).order_by(Regra.prioridade.desc(), Regra.palavra_chave).all()
    return [{
        "id": r.id, "palavra_chave": r.palavra_chave,
        "categoria": r.categoria.nome if r.categoria else None,
        "categoria_id": r.categoria_id,
        "atribuicao": r.atribuicao.nome if r.atribuicao else None,
        "atribuicao_id": r.atribuicao_id,
        "prioridade": r.prioridade,
        "comentario": r.comentario,
    } for r in items]


@router.post("/api/regras")
def criar_regra(dados: dict, db: Session = Depends(get_db)):
    r = Regra(
        palavra_chave=dados["palavra_chave"].strip().upper(),
        categoria_id=dados.get("categoria_id"),
        atribuicao_id=dados.get("atribuicao_id"),
        prioridade=dados.get("prioridade", 5),
        comentario=dados.get("comentario", ""),
    )
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/api/regras/{rid}")
def excluir_regra(rid: int, db: Session = Depends(get_db)):
    r = db.query(Regra).get(rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}
