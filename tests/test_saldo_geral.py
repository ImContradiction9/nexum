"""Saldo geral (caixa): Receitas − Despesas + empréstimos(receb−conced) + invest(resg−aplic)."""
from datetime import date

from app.routers.dashboard import dashboard
from app.database import Transacao, Categoria, Conta


def _setup(db):
    conta = Conta(nome="Conta", tipo="Conta Corrente")
    cats = {n: Categoria(nome=n, tipo=t) for n, t in [
        ("Pró-labore", "Receita"), ("Mercado", "Despesa"),
        ("Empréstimos a Terceiros", "Despesa"), ("Investimentos", "Despesa"),
    ]}
    db.add(conta); db.add_all(cats.values()); db.commit()
    db.refresh(conta)
    for c in cats.values():
        db.refresh(c)
    return conta, cats


def _t(db, conta, cat, valor, tipo):
    db.add(Transacao(conta_id=conta.id, categoria_id=cat.id, data=date(2026, 5, 10),
                     descricao="x", valor=valor, tipo=tipo, mes_referencia="05/2026",
                     categoria_origem="manual"))
    db.commit()


def test_saldo_geral_considera_tudo(db):
    conta, cats = _setup(db)
    _t(db, conta, cats["Pró-labore"], 1000.0, "Receita")          # renda
    _t(db, conta, cats["Mercado"], 300.0, "Despesa")              # gasto
    _t(db, conta, cats["Empréstimos a Terceiros"], 200.0, "Receita")   # recebeu de volta
    _t(db, conta, cats["Empréstimos a Terceiros"], 50.0, "Despesa")    # emprestou
    _t(db, conta, cats["Investimentos"], 400.0, "Despesa")        # aplicou
    _t(db, conta, cats["Investimentos"], 100.0, "Receita")        # resgatou

    d = dashboard(data_inicio="2026-05-01", data_fim="2026-05-31", regime="pagamento", db=db)
    assert d["receitas"] == 1000.0
    assert d["despesas"] == 300.0
    assert d["saldo"] == 700.0
    assert d["fluxo_emprestimos"] == {"recebido": 200.0, "concedido": 50.0, "liquido": 150.0}
    assert d["fluxo_investimentos"] == {"resgatado": 100.0, "aplicado": 400.0, "liquido": -300.0}
    # 700 + 150 + (-300) = 550
    assert d["saldo_geral"] == 550.0
