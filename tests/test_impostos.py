"""Testes do módulo de impostos (IR regressivo + IOF) sobre renda fixa."""
import pytest

from app.impostos import (
    aliquota_ir, aliquota_iof, aliquota_ir_longo_prazo,
    isento_ir, calcular_liquido,
)


# ---- IR regressivo ----
@pytest.mark.parametrize("dias,esperado", [
    (1, 0.225), (180, 0.225),
    (181, 0.20), (360, 0.20),
    (361, 0.175), (720, 0.175),
    (721, 0.15), (5000, 0.15),
])
def test_ir_tabela_regressiva(dias, esperado):
    assert aliquota_ir(dias, "CDB") == esperado


def test_lci_lca_isentos_de_ir():
    assert isento_ir("LCI") and isento_ir("LCA")
    assert aliquota_ir(10, "LCI") == 0.0
    assert aliquota_ir(5000, "LCA") == 0.0
    assert aliquota_ir_longo_prazo("LCI") == 0.0
    assert aliquota_ir_longo_prazo("CDB") == 0.15


# ---- IOF ----
def test_iof_primeiros_dias_e_zera_em_30():
    assert aliquota_iof(1) == 0.96
    assert aliquota_iof(15) == 0.50
    assert aliquota_iof(29) == 0.03
    assert aliquota_iof(30) == 0.0
    assert aliquota_iof(100) == 0.0


# ---- líquido ----
def test_liquido_longo_prazo_cdb_15pct():
    # 2 anos+, sem IOF: IR 15% sobre o rendimento.
    r = calcular_liquido(saldo_bruto=11000, rendimento_bruto=1000, dias=800, tipo="CDB")
    assert r["iof_valor"] == 0.0
    assert r["ir_aliquota"] == 0.15
    assert r["ir_valor"] == pytest.approx(150.0)
    assert r["saldo_liquido"] == pytest.approx(10850.0)


def test_liquido_lci_sem_ir():
    r = calcular_liquido(saldo_bruto=11000, rendimento_bruto=1000, dias=800, tipo="LCI")
    assert r["ir_valor"] == 0.0
    assert r["saldo_liquido"] == pytest.approx(11000.0)
    assert r["isento_ir"] is True


def test_liquido_resgate_precoce_tem_iof_e_ir_curto():
    # 10 dias: IOF 66% do rendimento, IR 22,5% sobre o que sobra.
    r = calcular_liquido(saldo_bruto=1100, rendimento_bruto=100, dias=10, tipo="CDB")
    assert r["iof_valor"] == pytest.approx(66.0)
    # base IR = 100 - 66 = 34 ; IR = 34 * 0.225 = 7.65
    assert r["ir_valor"] == pytest.approx(7.65)
    assert r["saldo_liquido"] == pytest.approx(1100 - 66 - 7.65)


def test_sem_rendimento_nao_tem_imposto():
    r = calcular_liquido(saldo_bruto=1000, rendimento_bruto=0, dias=800, tipo="CDB")
    assert r["ir_valor"] == 0.0 and r["iof_valor"] == 0.0
    assert r["saldo_liquido"] == pytest.approx(1000.0)
