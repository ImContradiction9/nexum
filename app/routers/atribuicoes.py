"""Atribuições (pessoas/grupos): CRUD. Extraído de main.py."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Atribuicao, Transacao, Regra
from ..utils import ordena_pt

router = APIRouter()


@router.get("/api/atribuicoes")
def listar_atribuicoes(db: Session = Depends(get_db)):
    atrs = db.query(Atribuicao).filter(Atribuicao.ativo == True).all()
    return [{"id": a.id, "nome": a.nome, "tipo": a.tipo, "cor": a.cor,
             "descricao": a.descricao}
            for a in ordena_pt(atrs)]


@router.post("/api/atribuicoes")
def criar_atribuicao(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    if db.query(Atribuicao).filter(Atribuicao.nome == nome).first():
        raise HTTPException(400, f"Já existe uma atribuição '{nome}'")
    a = Atribuicao(
        nome=nome,
        tipo=dados.get("tipo", "Pessoa"),
        cor=dados.get("cor", "#888888"),
        descricao=dados.get("descricao", ""),
    )
    db.add(a)
    db.commit()
    return {"id": a.id, "nome": a.nome}


@router.patch("/api/atribuicoes/{aid}")
def atualizar_atribuicao(aid: int, dados: dict, db: Session = Depends(get_db)):
    a = db.query(Atribuicao).get(aid)
    if not a:
        raise HTTPException(404)
    if "nome" in dados and dados["nome"]:
        a.nome = dados["nome"].strip()
    for campo in ("tipo", "cor", "descricao", "ativo"):
        if campo in dados:
            setattr(a, campo, dados[campo])
    db.commit()
    return {"id": a.id, "ok": True}


@router.delete("/api/atribuicoes/{aid}")
def excluir_atribuicao(aid: int, db: Session = Depends(get_db)):
    a = db.query(Atribuicao).get(aid)
    if not a:
        raise HTTPException(404)
    n_trans = db.query(Transacao).filter(Transacao.atribuicao_id == aid).count()
    n_regras = db.query(Regra).filter(Regra.atribuicao_id == aid).count()
    if n_trans > 0 or n_regras > 0:
        raise HTTPException(
            400,
            f"Não posso excluir: {n_trans} transação(ões) e {n_regras} regra(s) "
            f"usam esta atribuição. Considere desativar ou reatribuir antes."
        )
    db.delete(a)
    db.commit()
    return {"ok": True}
