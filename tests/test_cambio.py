"""Testes do módulo de câmbio (cotação atual USD→BRL, manual + cache BCB).

A rede do BCB é mockada no conftest (cambio.sincronizar vira no-op), então
estes testes cobrem a lógica de resolução da taxa, não o download.
"""
from app import cambio
from app.database import Configuracao


def _set(db, chave, valor):
    db.add(Configuracao(chave=chave, valor=str(valor)))
    db.commit()


def test_brl_sempre_1(db):
    assert cambio.taxa_atual(db, "BRL") == 1.0
    assert cambio.taxa_atual(db, "brl") == 1.0
    assert cambio.taxa_atual(db, None) == 1.0


def test_sem_dados_retorna_none(db):
    assert cambio.taxa_atual(db, "USD") is None


def test_usa_cache_automatico(db):
    _set(db, "cambio_usd", "5.04")
    assert cambio.taxa_atual(db, "USD") == 5.04


def test_manual_tem_prioridade_sobre_auto(db):
    _set(db, "cambio_usd", "5.04")
    cambio.set_manual(db, "USD", 6.10)
    assert cambio.taxa_atual(db, "USD") == 6.10


def test_manual_limpo_volta_pro_automatico(db):
    _set(db, "cambio_usd", "5.04")
    cambio.set_manual(db, "USD", 6.10)
    cambio.set_manual(db, "USD", "")          # limpa override
    assert cambio.taxa_atual(db, "USD") == 5.04


def test_manual_aceita_virgula(db):
    cambio.set_manual(db, "USD", "5,25")
    assert cambio.taxa_atual(db, "USD") == 5.25


def test_valores_invalidos_ou_zero_sao_ignorados(db):
    cambio.set_manual(db, "USD", "abc")       # inválido → ignora
    assert cambio.taxa_atual(db, "USD") is None
    _set(db, "cambio_usd", "0")               # zero não é cotação válida
    assert cambio.taxa_atual(db, "USD") is None


def test_status_estrutura(db):
    _set(db, "cambio_usd", "5.04")
    _set(db, "cambio_usd_data", "01/06/2026")
    st = cambio.status(db)
    assert "USD" in st["moedas"]
    usd = st["moedas"]["USD"]
    assert usd["auto"] == 5.04
    assert usd["usado"] == 5.04
    assert usd["data_bcb"] == "01/06/2026"
    assert usd["manual"] is None
