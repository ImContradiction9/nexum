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
    # Saldo geral = caixa real: soma assinada de tudo na conta (todas as 6 são
    # da mesma Conta Corrente, sem cartão nem transferência) = 1000−300+200−50−400+100
    assert d["saldo_geral"] == 550.0


def test_saldo_geral_e_caixa_real(db):
    """Saldo geral = variação real do caixa: ignora gasto no CARTÃO (só vira caixa
    quando a fatura é paga) e transferências entre contas próprias se ANULAM."""
    conta_a = Conta(nome="Conta A", tipo="Conta Corrente")
    conta_b = Conta(nome="Conta B", tipo="Conta Corrente")
    cartao = Conta(nome="Cartão", tipo="Cartão de Crédito")
    renda = Categoria(nome="Pró-labore", tipo="Receita")
    merc = Categoria(nome="Mercado", tipo="Despesa")
    db.add_all([conta_a, conta_b, cartao, renda, merc]); db.commit()
    for o in (conta_a, conta_b, cartao, renda, merc):
        db.refresh(o)

    def add(conta, cat, valor, tipo, mov=None):
        db.add(Transacao(conta_id=conta.id, categoria_id=(cat.id if cat else None),
                         data=date(2026, 5, 10), descricao="x", valor=valor, tipo=tipo,
                         mes_referencia="05/2026", categoria_origem="manual", movimentacao=mov))
    add(conta_a, renda, 1000.0, "Receita")        # entrou no caixa
    add(conta_a, merc, 300.0, "Despesa")          # saiu do caixa
    add(cartao, merc, 500.0, "Despesa")           # gasto no CARTÃO → NÃO é caixa
    add(conta_a, None, 100.0, "Despesa", "transferencia")   # saiu de A
    add(conta_b, None, 100.0, "Receita", "transferencia")   # entrou em B (anula)
    db.commit()

    d = dashboard(data_inicio="2026-05-01", data_fim="2026-05-31", regime="pagamento", db=db)
    # Caixa = 1000 − 300 (cartão fora; transferência −100+100 = 0) = 700
    assert d["saldo_geral"] == 700.0
    assert d["saldo_caixa"] == 700.0
