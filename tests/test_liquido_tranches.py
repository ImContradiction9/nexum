"""Líquido de renda fixa CDI-auto calculado por aporte (tranche).

Regressão do bug em que o líquido usava um prazo médio único pra posição
inteira e, como o IOF é não-linear nos 1ºs 30 dias, superestimava o imposto
(aportes antigos eram tributados como se fossem recentes).
"""
from datetime import date, timedelta
from types import SimpleNamespace

from app import cdi as cdi_mod, impostos
from app.routers.investimentos import _liquido_renda_fixa_cdi


def _op(tipo, d, valor):
    return SimpleNamespace(tipo=tipo, data=d, valor_total=valor, taxas=0.0)


def _serie_constante(ate: date, dias: int, taxa_pct_dia=0.05) -> dict:
    """Série CDI sintética: taxa diária constante nos `dias` dias até `ate`."""
    return {ate - timedelta(days=i): taxa_pct_dia for i in range(dias)}


def test_por_tranche_bate_soma_manual_e_difere_do_prazo_medio():
    hoje = date.today()
    serie = _serie_constante(hoje, 60)
    # Aporte grande e velho + aporte recente: o prazo médio único trata todo o
    # rendimento como se tivesse a mesma idade; por tranche cada um paga o seu.
    ops = [
        _op("Compra", hoje - timedelta(days=22), 4500.0),
        _op("Aporte", hoje - timedelta(days=17), 4800.0),
        _op("Aporte", hoje - timedelta(days=1), 227.0),
    ]
    saldo = cdi_mod.saldo_composto(
        [(o.data, o.valor_total) for o in ops], serie, 100.0
    )
    investido = sum(o.valor_total for o in ops)
    rend = saldo - investido

    # Método antigo (prazo médio único): superestima/distorce o IOF.
    sp = sum(o.valor_total * (hoje - o.data).days for o in ops)
    prazo = int(round(sp / investido))
    antigo = impostos.calcular_liquido(saldo, rend, prazo, "CDB")

    # Método novo (por tranche) — deve bater com a soma manual tranche-a-tranche.
    novo = _liquido_renda_fixa_cdi(ops, serie, 100.0, "CDB", saldo)

    esperado_iof = esperado_ir = 0.0
    for o in ops:
        s = cdi_mod.saldo_composto([(o.data, o.valor_total)], serie, 100.0)
        L = impostos.calcular_liquido(s, s - o.valor_total, (hoje - o.data).days, "CDB")
        esperado_iof += L["iof_valor"]
        esperado_ir += L["ir_valor"]

    assert novo["iof_valor"] == round(esperado_iof, 2)
    assert novo["ir_valor"] == round(esperado_ir, 2)
    # E o resultado por-tranche é diferente do prazo-médio (o bug original).
    assert novo["saldo_liquido"] != antigo["saldo_liquido"]


def test_sem_resgate_soma_brutos_igual_saldo():
    """Sem resgate, o saldo bruto = soma dos brutos por tranche → sem escala."""
    hoje = date.today()
    serie = _serie_constante(hoje, 60)
    ops = [
        _op("Compra", hoje - timedelta(days=20), 1000.0),
        _op("Aporte", hoje - timedelta(days=5), 500.0),
    ]
    saldo = cdi_mod.saldo_composto(
        [(o.data, o.valor_total) for o in ops], serie, 100.0
    )
    r = _liquido_renda_fixa_cdi(ops, serie, 100.0, "CDB", saldo)
    # líquido < bruto (tem imposto) mas > investido (tem ganho)
    assert r["saldo_liquido"] < saldo
    assert r["saldo_liquido"] > 1500.0
    assert r["iof_valor"] > 0  # aportes ainda dentro dos 30 dias


def test_iof_zera_apos_30_dias_por_tranche():
    """Aportes todos com >30 dias → IOF zero em todas as tranches."""
    hoje = date.today()
    serie = _serie_constante(hoje, 120)
    ops = [
        _op("Compra", hoje - timedelta(days=90), 1000.0),
        _op("Aporte", hoje - timedelta(days=40), 500.0),
    ]
    saldo = cdi_mod.saldo_composto(
        [(o.data, o.valor_total) for o in ops], serie, 100.0
    )
    r = _liquido_renda_fixa_cdi(ops, serie, 100.0, "CDB", saldo)
    assert r["iof_valor"] == 0.0
    assert r["ir_valor"] > 0  # IR ainda incide


def test_resgate_escala_imposto_proporcional():
    """Com resgate, o saldo real < soma dos brutos → imposto escala junto."""
    hoje = date.today()
    serie = _serie_constante(hoje, 60)
    ops = [
        _op("Compra", hoje - timedelta(days=20), 2000.0),
        _op("Resgate", hoje - timedelta(days=2), 500.0),
    ]
    flows = [(o.data, o.valor_total if o.tipo in ("Compra", "Aporte") else -o.valor_total)
             for o in ops]
    saldo = cdi_mod.saldo_composto(flows, serie, 100.0)
    r = _liquido_renda_fixa_cdi(ops, serie, 100.0, "CDB", saldo)
    # Sem escala, o imposto seria o do aporte cheio (2000); com resgate é menor.
    sem_resgate = _liquido_renda_fixa_cdi(
        [ops[0]], serie, 100.0, "CDB",
        cdi_mod.saldo_composto([(ops[0].data, 2000.0)], serie, 100.0),
    )
    assert r["iof_valor"] < sem_resgate["iof_valor"]
    assert r["saldo_liquido"] <= saldo
