"""Resumo de empréstimos é ACUMULADO (saldo a receber), não cortado pelo período.

Bug: empréstimo cujas compras caem antes do recorte (ex.: compras de dez/2025 na
fatura de jan/2026) ficava de fora quando se via o ano 2026 (filtro por `data`),
e o saldo a receber aparecia errado.
"""
from datetime import date

from app.routers.dashboard import dashboard
from app.database import Transacao, Categoria, Atribuicao, Conta


def _setup(db):
    cat = Categoria(nome="Empréstimos a Terceiros", tipo="Despesa")
    atr = Atribuicao(nome="Fulano", tipo="Grupo")
    conta = Conta(nome="Cartão", tipo="Cartão de Crédito")
    db.add_all([cat, atr, conta])
    db.commit()
    db.refresh(cat); db.refresh(atr); db.refresh(conta)
    return cat, atr, conta


def _t(db, conta, cat, atr, data, valor, tipo, mes):
    db.add(Transacao(
        conta_id=conta.id, categoria_id=cat.id, atribuicao_id=atr.id,
        data=data, descricao="Emprestimo", valor=valor, tipo=tipo,
        mes_referencia=mes, categoria_origem="manual",
    ))
    db.commit()


def test_emprestimo_acumulado_inclui_fora_do_periodo(db):
    cat, atr, conta = _setup(db)
    # Emprestou em dez/2025 (data fora do ano 2026, mas fatura jan/2026)
    _t(db, conta, cat, atr, date(2025, 12, 20), 1000.0, "Despesa", "01/2026")
    # Recebeu de volta em maio/2026
    _t(db, conta, cat, atr, date(2026, 5, 6), 1000.0, "Receita", "05/2026")

    out = dashboard(data_inicio="2026-01-01", data_fim="2026-12-31", db=db)
    e = out["emprestimos"]
    # Acumulado: conta o empréstimo de dez/2025 mesmo vendo "2026"
    assert round(e["emprestado"], 2) == 1000.0
    assert round(e["recebido"], 2) == 1000.0
    assert round(e["saldo"], 2) == 0.0
    fulano = next(p for p in e["por_pessoa"] if p["nome"] == "Fulano")
    assert round(fulano["saldo"], 2) == 0.0
