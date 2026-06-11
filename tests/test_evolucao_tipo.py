"""Evolução do patrimônio POR TIPO de investimento (gráfico empilhado).

`evolucao_patrimonio` passou a devolver, além de `serie`, as chaves:
- `meses`: lista "YYYY-MM"
- `tipos`: classes presentes (ordenadas pela posição atual desc)
- `series_tipo`: {tipo: [valor por mês]}

Regras validadas:
- o empilhado por tipo SOMA o patrimônio do mês (consistência com a linha total);
- o ÚLTIMO mês usa a posição ao vivo (igual à tabela do resumo `por_tipo`).
"""
from datetime import date, timedelta

import pytest

from app.database import Ativo, OperacaoInvestimento
from app.routers.investimentos import evolucao_patrimonio, resumo_investimentos


def _ativo(db, nome, tipo):
    a = Ativo(nome=nome, tipo=tipo, moeda="BRL", ativo=True, objetivo="patrimonio")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _op(db, ativo, tipo, valor, dias_atras):
    db.add(OperacaoInvestimento(
        ativo_id=ativo.id, tipo=tipo, valor_total=valor,
        data=date.today() - timedelta(days=dias_atras),
    ))
    db.commit()


def test_evolucao_por_tipo_soma_e_bate_com_resumo(db):
    rdb = _ativo(db, "Caixinha", "RDB")
    etf = _ativo(db, "VWRA", "ETF Internacional")
    _op(db, rdb, "Compra", 10000.0, dias_atras=120)
    _op(db, etf, "Compra", 5000.0, dias_atras=120)

    e = evolucao_patrimonio(db)
    assert set(e["tipos"]) == {"RDB", "ETF Internacional"}
    assert "series_tipo" in e and "meses" in e

    # Cada mês: a soma dos tipos == o patrimônio daquele mês.
    patr_por_mes = {p["mes"]: p["patrimonio"] for p in e["serie"]}
    for i, m in enumerate(e["meses"]):
        soma = sum(e["series_tipo"][t][i] for t in e["tipos"])
        if patr_por_mes.get(m) is not None:
            assert soma == pytest.approx(patr_por_mes[m], abs=0.02)

    # Último mês = posição ao vivo (igual ao resumo por_tipo).
    r = resumo_investimentos(db)
    tabela = {t["tipo"]: round(t["atual_brl"], 2) for t in r["por_tipo"]}
    ult = {t: e["series_tipo"][t][-1] for t in e["tipos"]}
    for tipo in tabela:
        assert ult.get(tipo, 0) == pytest.approx(tabela[tipo], abs=0.02)


def test_evolucao_sem_ativos_nao_quebra(db):
    e = evolucao_patrimonio(db)
    assert e["serie"] == []
    assert e["tipos"] == [] and e["series_tipo"] == {}
