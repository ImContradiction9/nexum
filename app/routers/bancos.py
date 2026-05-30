"""Bancos: CRUD. Extraído de main.py (refactor por domínio)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Banco, Conta

router = APIRouter()


@router.get("/api/bancos")
def listar_bancos(db: Session = Depends(get_db)):
    return [{"id": b.id, "nome": b.nome, "cor": b.cor, "ativo": b.ativo}
            for b in db.query(Banco).filter(Banco.ativo == True).order_by(Banco.nome).all()]


@router.post("/api/bancos")
def criar_banco(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    if db.query(Banco).filter(Banco.nome == nome).first():
        raise HTTPException(400, f"Já existe um banco '{nome}'")
    b = Banco(nome=nome, cor=dados.get("cor", "#888888"))
    db.add(b)
    db.commit()
    return {"id": b.id, "nome": b.nome}


@router.patch("/api/bancos/{bid}")
def atualizar_banco(bid: int, dados: dict, db: Session = Depends(get_db)):
    b = db.query(Banco).get(bid)
    if not b:
        raise HTTPException(404)
    if "nome" in dados and dados["nome"]:
        b.nome = dados["nome"].strip()
    for campo in ("cor", "ativo"):
        if campo in dados:
            setattr(b, campo, dados[campo])
    db.commit()
    return {"id": b.id, "ok": True}


@router.delete("/api/bancos/{bid}")
def excluir_banco(bid: int, db: Session = Depends(get_db)):
    b = db.query(Banco).get(bid)
    if not b:
        raise HTTPException(404)
    n_contas = db.query(Conta).filter(Conta.banco_id == bid).count()
    if n_contas > 0:
        raise HTTPException(400, f"{n_contas} conta(s) usam este banco. Reatribua antes.")
    db.delete(b)
    db.commit()
    return {"ok": True}
