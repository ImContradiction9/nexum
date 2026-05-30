"""Empréstimos a terceiros: saldo por pessoa. Extraído de main.py."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Categoria, Atribuicao, Transacao

router = APIRouter()


@router.get("/api/emprestimos/saldo")
def saldo_emprestimos(db: Session = Depends(get_db)):
    """
    Calcula saldo de empréstimos por atribuição (pessoa).

    Saldo positivo = pessoa te deve
    Saldo negativo = você deve à pessoa

    Considera transações marcadas com categoria "Empréstimos a Terceiros":
      - Despesa (você pagou algo "pela" pessoa) → entra como saldo + (te deve)
      - Receita (pessoa te pagou de volta) → entra como saldo - (abate)
    """
    cat = db.query(Categoria).filter(
        Categoria.nome == "Empréstimos a Terceiros"
    ).first()
    if not cat:
        return {"pessoas": [], "total_a_receber": 0, "total_a_pagar": 0}

    rows = db.query(
        Atribuicao.id,
        Atribuicao.nome,
        Atribuicao.cor,
        Transacao.tipo,
        func.sum(Transacao.valor),
    ).select_from(Transacao).outerjoin(
        Atribuicao, Transacao.atribuicao_id == Atribuicao.id
    ).filter(
        Transacao.categoria_id == cat.id,
    ).group_by(Atribuicao.id, Transacao.tipo).all()

    # Estrutura: {atribuicao_id: {nome, cor, despesa, receita}}
    por_pessoa = {}
    sem_atribuicao = {"despesa": 0, "receita": 0}

    for atr_id, nome, cor, tipo, total in rows:
        if atr_id is None:
            if tipo == "Despesa":
                sem_atribuicao["despesa"] += total or 0
            else:
                sem_atribuicao["receita"] += total or 0
            continue
        if atr_id not in por_pessoa:
            por_pessoa[atr_id] = {
                "id": atr_id,
                "nome": nome,
                "cor": cor or "#888888",
                "emprestou": 0,    # quanto você "pagou" por essa pessoa
                "recebeu": 0,      # quanto a pessoa te devolveu
            }
        if tipo == "Despesa":
            por_pessoa[atr_id]["emprestou"] += total or 0
        else:
            por_pessoa[atr_id]["recebeu"] += total or 0

    pessoas = []
    total_a_receber = 0
    total_a_pagar = 0

    for p in por_pessoa.values():
        saldo = p["emprestou"] - p["recebeu"]
        p["saldo"] = saldo
        if abs(saldo) < 0.01:
            p["status"] = "quitado"
        elif saldo > 0:
            p["status"] = "te_deve"
            total_a_receber += saldo
        else:
            p["status"] = "voce_deve"
            total_a_pagar += abs(saldo)
        pessoas.append(p)

    # Ordena: te_deve primeiro (descendente), depois voce_deve, depois quitado
    pessoas.sort(key=lambda p: (
        0 if p["status"] == "te_deve" else (1 if p["status"] == "voce_deve" else 2),
        -p["saldo"] if p["status"] == "te_deve" else p["saldo"]
    ))

    return {
        "pessoas": pessoas,
        "total_a_receber": total_a_receber,
        "total_a_pagar": total_a_pagar,
        "sem_atribuicao": sem_atribuicao,
    }
