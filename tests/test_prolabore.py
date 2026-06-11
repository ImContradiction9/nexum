"""Pró-labore: registro de quanto peguei × quanto falta pegar (por ano).

- pego = soma das receitas categorizadas como "Pró-labore" no ano (automático);
- devido = mensal do ano × meses decorridos (ano atual = meses passados; anteriores = 12);
- valor mensal configurável POR ANO.
"""
from datetime import date

import pytest

from app.database import Categoria, Conta, Transacao
from app.routers.prolabore import resumo_prolabore, salvar_prolabore_config


def _setup(db):
    cat = Categoria(nome="Pró-labore", tipo="Receita")
    conta = Conta(nome="CC", tipo="Conta Corrente")
    db.add_all([cat, conta])
    db.commit()
    db.refresh(cat); db.refresh(conta)
    return cat, conta


def _receita(db, cat, conta, valor, dia):
    db.add(Transacao(conta_id=conta.id, categoria_id=cat.id, data=dia,
                     descricao="PRO LABORE", valor=valor, tipo="Receita",
                     mes_referencia=dia.strftime("%m/%Y")))
    db.commit()


def test_pego_automatico_por_ano(db):
    cat, conta = _setup(db)
    ano = date.today().year
    _receita(db, cat, conta, 5000.0, date(ano, 1, 10))
    _receita(db, cat, conta, 5000.0, date(ano, 2, 10))
    # ano anterior
    _receita(db, cat, conta, 3000.0, date(ano - 1, 6, 10))

    r = resumo_prolabore(db)
    por_ano = {l["ano"]: l for l in r["linhas"]}
    assert por_ano[ano]["pego"] == pytest.approx(10000.0)
    assert por_ano[ano - 1]["pego"] == pytest.approx(3000.0)
    assert r["tem_categoria"] is True


def test_devido_meses_decorridos_e_falta(db):
    cat, conta = _setup(db)
    hoje = date.today()
    ano = hoje.year
    # configura mensal por ano (ano atual 6000, ano passado 5000)
    salvar_prolabore_config(
        {"mensal_por_ano": {str(ano): 6000, str(ano - 1): 5000}}, db)
    # peguei só parte
    _receita(db, cat, conta, 12000.0, date(ano, 3, 10))

    r = resumo_prolabore(db)
    por_ano = {l["ano"]: l for l in r["linhas"]}
    # ano atual: devido = 6000 * meses decorridos (mês atual)
    assert por_ano[ano]["meses"] == hoje.month
    assert por_ano[ano]["devido"] == pytest.approx(6000.0 * hoje.month)
    assert por_ano[ano]["falta"] == pytest.approx(6000.0 * hoje.month - 12000.0)
    # ano anterior: 12 meses, peguei 0 → falta = 60000
    assert por_ano[ano - 1]["meses"] == 12
    assert por_ano[ano - 1]["devido"] == pytest.approx(60000.0)
    assert por_ano[ano - 1]["falta"] == pytest.approx(60000.0)


def test_pego_manual_sobrescreve_automatico(db):
    cat, conta = _setup(db)
    hoje = date.today()
    ano = hoje.year
    # transações automáticas no ano atual
    _receita(db, cat, conta, 10000.0, date(ano, 1, 10))
    # ano anterior SEM transações no app → peguei manual
    salvar_prolabore_config({
        "mensal_por_ano": {str(ano - 1): 32000},
        "pego_manual_por_ano": {str(ano - 1): 113952.84},
    }, db)

    r = resumo_prolabore(db)
    por_ano = {l["ano"]: l for l in r["linhas"]}
    # ano anterior: peguei manual vence; devido = 32000*12 = 384000
    assert por_ano[ano - 1]["pego"] == pytest.approx(113952.84)
    assert por_ano[ano - 1]["pego_manual"] is True
    assert por_ano[ano - 1]["devido"] == pytest.approx(384000.0)
    assert por_ano[ano - 1]["falta"] == pytest.approx(384000.0 - 113952.84)
    # ano atual: continua automático (sem manual)
    assert por_ano[ano]["pego"] == pytest.approx(10000.0)
    assert por_ano[ano]["pego_manual"] is False


def test_config_limpa_valores_invalidos(db):
    _setup(db)
    r = salvar_prolabore_config(
        {"mensal_por_ano": {"2025": 5000, "2026": 0, "abc": 100, "2024": -5}}, db)
    anos = {l["ano"]: l["mensal"] for l in r["linhas"]}
    assert anos.get(2025) == 5000.0
    assert 2026 not in anos and 2024 not in anos  # 0 e negativo descartados
