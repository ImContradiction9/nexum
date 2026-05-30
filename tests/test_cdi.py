"""Testes do cálculo de rendimento via CDI (app/cdi.py) — pura matemática, sem rede."""
from datetime import date

import pytest

from app import cdi as cdi_mod


def _serie(dias, taxa=0.05):
    """{data: taxa} para uma sequência de dias consecutivos."""
    return {d: taxa for d in dias}


def test_saldo_composto_sem_fluxos_eh_zero():
    assert cdi_mod.saldo_composto([], {}, 100) == 0.0


def test_saldo_composto_aporte_unico_100pct():
    d0, d1, d2 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)
    serie = _serie([d0, d1, d2], 0.05)  # 0,05% ao dia
    saldo = cdi_mod.saldo_composto([(d0, 1000.0)], serie, 100, ate=d2)
    # Rende nos 3 dias com CDI publicado: 1000 * 1,0005^3
    assert saldo == pytest.approx(1000 * (1.0005 ** 3), rel=1e-9)


def test_saldo_composto_percentual_escala_o_fator():
    d0, d1 = date(2026, 1, 5), date(2026, 1, 6)
    serie = _serie([d0, d1], 0.05)
    s100 = cdi_mod.saldo_composto([(d0, 1000.0)], serie, 100, ate=d1)
    s120 = cdi_mod.saldo_composto([(d0, 1000.0)], serie, 120, ate=d1)
    assert s120 > s100
    assert s120 == pytest.approx(1000 * ((1 + 0.0005 * 1.2) ** 2), rel=1e-9)


def test_saldo_composto_resgate_subtrai_apos_render():
    # Aporta, rende, e resgata no último dia — o resgate sai do saldo já crescido.
    dias = [date(2026, 1, d) for d in range(5, 9)]  # 4 dias
    serie = _serie(dias, 0.10)
    flows = [(dias[0], 1000.0), (dias[-1], -500.0)]
    saldo = cdi_mod.saldo_composto(flows, serie, 100, ate=dias[-1])
    # Cresce 4 dias e no 4º dia subtrai 500 antes do fator daquele dia.
    esperado = 1000 * (1.001 ** 3)          # dias 1..3
    esperado = (esperado - 500) * 1.001     # dia 4: aplica fluxo, depois rende
    assert saldo == pytest.approx(esperado, rel=1e-9)


def test_saldo_composto_cobre_fluxo_posterior_a_ultima_data_cdi():
    # Regressão: resgate datado depois do último CDI publicado precisa ser aplicado.
    d0 = date(2026, 1, 5)
    serie = {d0: 0.05}                       # CDI só do dia do aporte
    resgate_dia = date(2026, 1, 9)          # depois do fim da série
    flows = [(d0, 1000.0), (resgate_dia, -300.0)]
    saldo = cdi_mod.saldo_composto(flows, serie, 100)  # ate=None → cobre o resgate
    # 1000 rende 1 dia (1,0005) e depois -300 (dias sem CDI não rendem).
    assert saldo == pytest.approx(1000 * 1.0005 - 300, rel=1e-9)


def test_cdi_anual_a_partir_da_serie():
    serie = {date(2026, 1, 5): 0.05}
    # (1 + 0,0005)^252 - 1
    assert cdi_mod.cdi_anual(serie) == pytest.approx(1.0005 ** 252 - 1, rel=1e-9)
    assert cdi_mod.cdi_anual({}) == 0.0
