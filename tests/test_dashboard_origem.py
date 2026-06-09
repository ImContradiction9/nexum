"""Dashboard: agregação 'por_origem' — origem dos recebimentos (receitas).

Agrupa as receitas visíveis por categoria (salário, pró-labore, cashback, etc.).
Não inclui abatedoras (estorno/reembolso, que reduzem despesa) nem despesas.
"""
from datetime import date

from app.database import Transacao, Categoria, Conta
from app.routers.dashboard import dashboard


def _conta(db):
    c = Conta(nome="Nubank Conta", tipo="Conta Corrente")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _cat(db, nome, tipo, icone=None):
    c = Categoria(nome=nome, tipo=tipo, icone=icone)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _rec(db, conta, cat, valor, desc, dia=10):
    t = Transacao(conta_id=conta.id, categoria_id=cat.id if cat else None,
                  data=date(2026, 5, dia), descricao=desc, valor=valor,
                  tipo="Receita", mes_referencia="05/2026")
    db.add(t)
    db.commit()


def test_por_origem_agrupa_receitas_por_categoria(db):
    conta = _conta(db)
    salario = _cat(db, "Salário", "Receita", "💼")
    cashback = _cat(db, "Cashback", "Despesa")  # tipo Despesa mas conta como receita
    _rec(db, conta, salario, 5000.0, "SALARIO MICAEL")
    _rec(db, conta, salario, 3000.0, "SALARIO ANDREINA")
    _rec(db, conta, cashback, 42.50, "CASHBACK NUBANK")

    r = dashboard(mes="05/2026", db=db)
    origem = {o["nome"]: o["total"] for o in r["por_origem"]}
    assert origem == {"Salário": 8000.0, "Cashback": 42.50}
    # Ordenado desc por valor
    assert r["por_origem"][0]["nome"] == "Salário"


def test_por_origem_ignora_abatedoras_e_despesas(db):
    conta = _conta(db)
    salario = _cat(db, "Salário", "Receita")
    mercado = _cat(db, "Mercado", "Despesa")
    # Despesa normal não entra
    db.add(Transacao(conta_id=conta.id, categoria_id=mercado.id, data=date(2026, 5, 5),
                     descricao="SUPER", valor=200.0, tipo="Despesa", mes_referencia="05/2026"))
    # Receita com categoria de Despesa (≠ Cashback) = abatedora → não conta como origem
    db.add(Transacao(conta_id=conta.id, categoria_id=mercado.id, data=date(2026, 5, 6),
                     descricao="ESTORNO SUPER", valor=50.0, tipo="Receita", mes_referencia="05/2026"))
    db.commit()
    _rec(db, conta, salario, 5000.0, "SALARIO")

    r = dashboard(mes="05/2026", db=db)
    origem = {o["nome"]: o["total"] for o in r["por_origem"]}
    assert origem == {"Salário": 5000.0}


def test_por_origem_receita_sem_categoria(db):
    conta = _conta(db)
    _rec(db, conta, None, 1234.0, "PIX RECEBIDO")
    r = dashboard(mes="05/2026", db=db)
    origem = {o["nome"]: o["total"] for o in r["por_origem"]}
    assert origem == {"Sem categoria": 1234.0}
