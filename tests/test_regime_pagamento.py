"""Regime emissão vs pagamento + data de pagamento efetiva da fatura.

- emissão: compra conta no mês da compra (`data`).
- pagamento (caixa): compra de cartão conta no mês do pagamento da fatura
  (manual > pagamento vinculado no extrato > vencimento).
"""
from datetime import date

from app.database import Transacao, Categoria, Conta, Fatura
from app.conciliacao import (
    data_pagamento_fatura, recalcular_data_pagamento,
    detectar_pagamentos_fatura, conciliar_pagamentos_auto,
)
from app.routers.dashboard import dashboard


def _base(db):
    cartao = Conta(nome="Nubank Crédito", tipo="Cartão de Crédito")
    corrente = Conta(nome="Nubank Conta", tipo="Conta Corrente")
    cat = Categoria(nome="Compras", tipo="Despesa")
    db.add_all([cartao, corrente, cat])
    db.commit()
    db.refresh(cartao); db.refresh(corrente); db.refresh(cat)
    return cartao, corrente, cat


def _fatura(db, conta, total, venc, mes):
    f = Fatura(banco="Nubank", conta_id=conta.id, mes_referencia=mes,
               data_vencimento=venc, total=total)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def test_data_pagamento_fatura_prioridade(db):
    cartao, corrente, cat = _base(db)
    f = _fatura(db, cartao, 100.0, date(2026, 5, 13), "05/2026")
    # 1) só vencimento
    assert data_pagamento_fatura(db, f) == date(2026, 5, 13)
    # 2) pagamento vinculado no extrato (antecipado) vence o vencimento
    pag = Transacao(conta_id=corrente.id, data=date(2026, 4, 28), descricao="PAGAMENTO DE FATURA",
                    valor=100.0, tipo="Despesa", mes_referencia="04/2026",
                    pagamento_de_fatura_id=f.id)
    db.add(pag); db.commit()
    assert data_pagamento_fatura(db, f) == date(2026, 4, 28)
    # 3) manual vence tudo
    f.data_pagamento_manual = date(2026, 4, 20)
    db.commit()
    assert data_pagamento_fatura(db, f) == date(2026, 4, 20)


def test_dashboard_emissao_vs_pagamento(db):
    cartao, corrente, cat = _base(db)
    f = _fatura(db, cartao, 200.0, date(2026, 5, 13), "05/2026")
    # Compra emissão 15/04, paga na fatura de 13/05
    t = Transacao(conta_id=cartao.id, fatura_id=f.id, categoria_id=cat.id,
                  data=date(2026, 4, 15), descricao="AMAZON", valor=200.0, tipo="Despesa",
                  mes_referencia="05/2026", categoria_origem="manual",
                  data_pagamento=date(2026, 5, 13))
    db.add(t); db.commit()

    # Por emissão: cai em ABRIL
    abr_e = dashboard(data_inicio="2026-04-01", data_fim="2026-04-30", regime="emissao", db=db)
    mai_e = dashboard(data_inicio="2026-05-01", data_fim="2026-05-31", regime="emissao", db=db)
    assert abr_e["despesas"] == 200.0
    assert mai_e["despesas"] == 0.0
    # Por pagamento: cai em MAIO
    abr_p = dashboard(data_inicio="2026-04-01", data_fim="2026-04-30", regime="pagamento", db=db)
    mai_p = dashboard(data_inicio="2026-05-01", data_fim="2026-05-31", regime="pagamento", db=db)
    assert abr_p["despesas"] == 0.0
    assert mai_p["despesas"] == 200.0


def test_conciliacao_casa_pagamento_ofx(db):
    """Regressão: pagamento vindo de OFX (com fatura_id de extrato e
    movimentacao='fatura') deve casar com a fatura de cartão."""
    cartao, corrente, cat = _base(db)
    f_cartao = _fatura(db, cartao, 300.0, date(2026, 5, 13), "05/2026")
    # compra do cartão (pra ter o que recalcular)
    compra = Transacao(conta_id=cartao.id, fatura_id=f_cartao.id, categoria_id=cat.id,
                       data=date(2026, 4, 10), descricao="LOJA", valor=300.0, tipo="Despesa",
                       mes_referencia="05/2026", data_pagamento=date(2026, 5, 13))
    # extrato: fatura do extrato + a transação de pagamento (movimentacao='fatura')
    f_extrato = Fatura(banco="Nubank", conta_id=corrente.id, mes_referencia="04/2026", total=0)
    db.add_all([compra, f_extrato]); db.commit(); db.refresh(f_extrato)
    pag = Transacao(conta_id=corrente.id, fatura_id=f_extrato.id, data=date(2026, 4, 28),
                    descricao="Pagamento de fatura", valor=300.0, tipo="Despesa",
                    mes_referencia="04/2026", movimentacao="fatura", data_pagamento=date(2026, 4, 28))
    db.add(pag); db.commit()

    sugestoes = detectar_pagamentos_fatura(db)
    assert any(s.fatura_id == f_cartao.id and s.transacao_id == pag.id for s in sugestoes)

    n = conciliar_pagamentos_auto(db)
    db.commit()
    assert n == 1
    db.refresh(pag); db.refresh(compra)
    assert pag.pagamento_de_fatura_id == f_cartao.id
    # data de pagamento da compra do cartão antecipou pro dia do pagamento real
    assert compra.data_pagamento == date(2026, 4, 28)


def test_recalcular_data_pagamento_manual(db):
    cartao, corrente, cat = _base(db)
    f = _fatura(db, cartao, 50.0, date(2026, 5, 13), "05/2026")
    t = Transacao(conta_id=cartao.id, fatura_id=f.id, data=date(2026, 4, 9),
                  descricao="X", valor=50.0, tipo="Despesa", mes_referencia="05/2026",
                  data_pagamento=date(2026, 5, 13))
    db.add(t); db.commit()
    f.data_pagamento_manual = date(2026, 4, 30)
    db.commit()
    recalcular_data_pagamento(db, f)
    db.refresh(t)
    assert t.data_pagamento == date(2026, 4, 30)


def test_dashboard_periodo_perto_de_date_min_nao_quebra(db):
    """Regressão: período começando em 0001-01-01 fazia o cálculo do período
    anterior estourar (OverflowError) e o dashboard retornava 500. Agora deve
    apenas omitir o comparativo, sem quebrar."""
    cartao, corrente, cat = _base(db)
    t = Transacao(conta_id=corrente.id, categoria_id=cat.id,
                  data=date(2026, 5, 10), descricao="Compra", valor=50.0,
                  tipo="Despesa", mes_referencia="05/2026", categoria_origem="manual")
    db.add(t); db.commit()
    # data_inicio = date.min → di - 1 dia estouraria sem a blindagem
    r = dashboard(mes=None, data_inicio="0001-01-01", data_fim="2026-12-31",
                  regime="pagamento", db=db)
    assert "despesas" in r
    assert r["tem_mes_anterior"] is False
    assert r["mes_anterior"] is None
