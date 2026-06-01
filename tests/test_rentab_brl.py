"""Rentabilidade em R$ (retorno total): considera câmbio + dividendos."""
from datetime import date

from app.database import Ativo, OperacaoInvestimento
from app.routers.investimentos import _serializar_ativo


def test_rentab_brl_inclui_dividendos_renda_variavel(db):
    a = Ativo(nome="ETF X", ticker="X", tipo="ETF Internacional",
              moeda="USD", ativo=True, saldo_atual=100.0)
    db.add(a); db.flush()
    ops = [
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                             valor_total=100.0, cotacao_cambio=5.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Rendimento", data=date(2024, 6, 1),
                             valor_total=10.0, cotacao_cambio=5.0),
    ]
    ser = _serializar_ativo(a, ops, {}, taxa_cambio_atual=5.0)
    # investido_brl=500, posição_brl=500 (sem ganho de capital), dividendos_brl=50
    # → retorno total em R$ = 0 + 50 = 50
    assert round(ser["rendimentos_brl"], 2) == 50.0
    assert round(ser["rentab_brl"], 2) == 50.0


def test_rentab_brl_reflete_cambio_atual(db):
    # Comprou a 6,0; hoje 5,0 → perda cambial mesmo sem mexer no saldo em USD.
    a = Ativo(nome="ETF Y", ticker="Y", tipo="ETF Internacional",
              moeda="USD", ativo=True, saldo_atual=100.0)
    db.add(a); db.flush()
    ops = [OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                                valor_total=100.0, cotacao_cambio=6.0)]
    ser = _serializar_ativo(a, ops, {}, taxa_cambio_atual=5.0)
    # investido_brl=600, posição_brl=500 → -100 em R$ (sem dividendos)
    assert round(ser["valor_investido_brl"], 2) == 600.0
    assert round(ser["saldo_atual_brl"], 2) == 500.0
    assert round(ser["rentab_brl"], 2) == -100.0


def test_renda_fixa_brl_nao_soma_dividendo_duas_vezes(db):
    # Renda fixa: rendimento incorpora ao saldo; rentab_brl = saldo - investido.
    a = Ativo(nome="CDB", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=110.0)
    db.add(a); db.flush()
    ops = [OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                                valor_total=100.0)]
    ser = _serializar_ativo(a, ops, {})
    assert round(ser["rentab_brl"], 2) == 10.0
