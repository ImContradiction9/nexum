"""Divisão de transação em partes (transações-filhas).

A original vira "pai" (dividida=True, fora dos totais e da lista de Transações,
mas visível no Extrato); as filhas (parte_de_id) somam o valor do pai e entram
nos totais/categorias.
"""
from datetime import date

import pytest

from app.routers.transacoes import (
    definir_partes, listar_partes, listar_transacoes, excluir_transacao,
)
from app.routers.dashboard import dashboard
from app.routers.extrato import extrato_conta
from app.database import Transacao, Categoria, Conta


def _conta(db):
    c = Conta(nome="Nubank Conta", tipo="Conta Corrente")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _cat(db, nome):
    c = Categoria(nome=nome, tipo="Despesa")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _despesa(db, conta, valor=100.0):
    t = Transacao(
        conta_id=conta.id, data=date(2026, 5, 10), descricao="AMAZON",
        descricao_normalizada="amazon", valor=valor, tipo="Despesa",
        mes_referencia="05/2026", categoria_origem="nao_categorizado",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _listar(db, **kw):
    return listar_transacoes(mes=None, data_inicio=None, data_fim=None, db=db, **kw)


def test_dividir_cria_filhas_que_somam(db):
    conta = _conta(db)
    merc = _cat(db, "Mercado")
    comp = _cat(db, "Compras")
    t = _despesa(db, conta, 100.0)

    out = definir_partes(t.id, [
        {"valor": 60, "categoria_id": merc.id},
        {"valor": 40, "categoria_id": comp.id},
    ], db=db)
    assert out["dividida"] is True
    assert len(out["partes"]) == 2

    db.refresh(t)
    assert t.dividida is True
    filhas = db.query(Transacao).filter(Transacao.parte_de_id == t.id).all()
    assert len(filhas) == 2
    assert round(sum(f.valor for f in filhas), 2) == 100.0
    assert all(f.tipo == "Despesa" for f in filhas)


def test_soma_divergente_da_400(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    with pytest.raises(Exception):
        definir_partes(t.id, [{"valor": 60}, {"valor": 30}], db=db)  # soma 90 != 100


def test_listagem_esconde_pai_mostra_filhas(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)

    res = _listar(db)
    ids = [i["id"] for i in res["items"]]
    assert t.id not in ids                      # pai escondido
    partes = [i for i in res["items"] if i["parte_de_id"] == t.id]
    assert len(partes) == 2                      # filhas visíveis


def test_dashboard_total_inalterado_apos_dividir(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    antes = dashboard(mes="05/2026", db=db)["despesas"]
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)
    depois = dashboard(mes="05/2026", db=db)["despesas"]
    assert antes == depois == 100.0              # filhas substituem o pai, total igual


def test_extrato_mostra_pai_esconde_filhas(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)

    ext = extrato_conta(conta_id=conta.id, mes="05/2026", db=db)
    ids = [i["id"] for i in ext["items"]]
    assert t.id in ids                           # pai (movimento real) aparece
    assert ext["n_transacoes"] == 1              # só o pai, sem duplicar


def test_desfazer_divisao(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)
    definir_partes(t.id, [], db=db)              # lista vazia = desfaz
    db.refresh(t)
    assert t.dividida is False
    assert db.query(Transacao).filter(Transacao.parte_de_id == t.id).count() == 0


def test_excluir_pai_apaga_filhas(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)
    excluir_transacao(t.id, db=db)
    assert db.query(Transacao).filter(Transacao.parte_de_id == t.id).count() == 0
    assert db.query(Transacao).get(t.id) is None


def test_listar_partes_aceita_id_de_filha(db):
    conta = _conta(db)
    t = _despesa(db, conta, 100.0)
    definir_partes(t.id, [{"valor": 60}, {"valor": 40}], db=db)
    filha = db.query(Transacao).filter(Transacao.parte_de_id == t.id).first()
    out = listar_partes(filha.id, db=db)         # passa id da filha
    assert out["pai"]["id"] == t.id              # resolve o pai
    assert len(out["partes"]) == 2
