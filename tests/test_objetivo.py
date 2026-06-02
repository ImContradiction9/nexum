"""Objetivo do investimento (patrimonio vs aquisicao): gráfico e meta de
patrimônio total ignoram os de 'aquisicao' (reservas pra carro/casa)."""
from datetime import date

from app.database import Ativo, Meta, OperacaoInvestimento
from app.routers.metas import _calcular_progresso_meta
from app.routers.investimentos import evolucao_patrimonio


def _saldos():
    return {
        "total_brl": 1000.0, "total_liquido_brl": 1000.0,
        "por_ativo": {1: 700.0, 2: 300.0}, "por_ativo_liquido": {1: 700.0, 2: 300.0},
        "ritmo_por_ativo_mensal": {1: 70.0, 2: 30.0},
        "objetivo_por_ativo": {1: "patrimonio", 2: "aquisicao"},
        "tipo_por_ativo": {1: "CDB", 2: "RDB"},
        "ritmo_mensal_brl": 100.0,
        "por_tipo": {}, "por_tipo_liquido": {},
        "taxa_anual_total": 0.0, "taxa_anual_liq_total": 0.0,
        "taxa_anual_por_tipo": {}, "taxa_anual_liq_por_tipo": {},
        "taxa_anual_por_ativo": {}, "taxa_anual_liq_por_ativo": {}, "cdi_anual": 0.0,
    }


def test_meta_patrimonio_total_ignora_aquisicao():
    m = Meta(nome="x", escopo="patrimonio_total", valor_alvo=10000.0)
    prog = _calcular_progresso_meta(m, _saldos())
    assert prog["valor_atual"] == 700.0            # só o ativo 1 (patrimonio)
    assert prog["ritmo_mensal_estimado"] == 70.0   # ritmo idem


def test_evolucao_ignora_aquisicao(db):
    p = Ativo(nome="P", tipo="CDB", moeda="BRL", ativo=True, objetivo="patrimonio")
    a = Ativo(nome="A", tipo="RDB", moeda="BRL", ativo=True, objetivo="aquisicao")
    db.add_all([p, a]); db.flush()
    db.add_all([
        OperacaoInvestimento(ativo_id=p.id, tipo="Compra", data=date(2026, 1, 5), valor_total=1000.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2026, 1, 5), valor_total=5000.0),
    ])
    db.commit()
    serie = {x["mes"]: x for x in evolucao_patrimonio(db=db)["serie"]}
    assert serie["2026-01"]["investido"] == 1000.0   # 5000 da aquisição ficam de fora
