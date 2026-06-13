"""Orçamento: média de gasto por período + marcador de tendência (subindo/descendo)."""
from datetime import date

import pytest

from app.database import Categoria, Conta, Transacao
from app.routers.dashboard import orcamentos_media, _ultimos_meses


def _setup(db):
    cat = Categoria(nome="Mercado", tipo="Despesa", orcamento_mensal=1000)
    conta = Conta(nome="CC", tipo="Conta Corrente")
    db.add_all([cat, conta])
    db.commit()
    db.refresh(cat); db.refresh(conta)
    return cat, conta


def _desp(db, cat, conta, valor, mes_ref):
    db.add(Transacao(conta_id=conta.id, categoria_id=cat.id, data=date(2026, 1, 1),
                     descricao="X", valor=valor, tipo="Despesa", mes_referencia=mes_ref))
    db.commit()


def test_ultimos_meses():
    assert _ultimos_meses("03/2026", 4) == ["12/2025", "01/2026", "02/2026", "03/2026"]


def test_media_e_tendencia_subindo(db):
    cat, conta = _setup(db)
    # janela de 6 meses terminando em 06/2026; gasto crescente na metade recente
    valores = {"01/2026": 200, "02/2026": 200, "03/2026": 200,
               "04/2026": 600, "05/2026": 600, "06/2026": 600}
    for mes, v in valores.items():
        _desp(db, cat, conta, v, mes)

    r = orcamentos_media(mes="06/2026", meses=6, db=db)
    item = next(i for i in r["itens"] if i["nome"] == "Mercado")
    assert item["media"] == pytest.approx(400.0)        # (200*3 + 600*3)/6
    assert item["anterior"] == pytest.approx(200.0)     # metade antiga
    assert item["recente"] == pytest.approx(600.0)      # metade recente
    assert item["tendencia"] == "subindo"
    assert item["orcamento"] == 1000
    assert r["tendencia"] == "subindo"


def test_media_tendencia_descendo(db):
    cat, conta = _setup(db)
    valores = {"01/2026": 800, "02/2026": 800, "03/2026": 800,
               "04/2026": 300, "05/2026": 300, "06/2026": 300}
    for mes, v in valores.items():
        _desp(db, cat, conta, v, mes)
    r = orcamentos_media(mes="06/2026", meses=6, db=db)
    item = next(i for i in r["itens"] if i["nome"] == "Mercado")
    assert item["tendencia"] == "descendo"
    assert item["media"] == pytest.approx(550.0)
