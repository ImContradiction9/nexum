"""Cotação ao vivo (renda variável com ticker): mapeamento e prioridade no saldo."""
from datetime import date

from app import cotacoes
from app.database import Ativo, OperacaoInvestimento
from app.routers.investimentos import _serializar_ativo


def test_simbolo_yahoo():
    assert cotacoes.simbolo_yahoo("IVV", "USD") == "IVV"
    assert cotacoes.simbolo_yahoo("PETR4", "BRL") == "PETR4.SA"   # B3 ganha .SA
    assert cotacoes.simbolo_yahoo("VWRA.L", "EUR") == "VWRA.L"    # já tem sufixo
    assert cotacoes.simbolo_yahoo("", "USD") is None


def test_cotacao_ao_vivo_tem_prioridade_sobre_manual(db):
    a = Ativo(nome="ETF", ticker="IVV", tipo="ETF Internacional",
              moeda="USD", ativo=True, saldo_atual=999.0)
    db.add(a); db.flush()
    ops = [OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                                quantidade=2.0, valor_total=200.0, cotacao_cambio=5.0)]
    cot = {"IVV": {"preco": 150.0, "moeda": "USD", "sym": "IVV", "em": "2026-06-01T00:00:00"}}
    ser = _serializar_ativo(a, ops, {}, taxa_cambio_atual=5.0, cotacoes=cot)
    assert ser["cotacao_auto"] is True
    assert ser["saldo_atual"] == 300.0          # 2 × 150 (ignora o saldo manual 999)
    assert ser["cotacao_preco"] == 150.0


def test_cotacao_moeda_diferente_nao_aplica(db):
    a = Ativo(nome="ETF", ticker="VWRA.L", tipo="ETF Internacional",
              moeda="EUR", ativo=True, saldo_atual=888.0)
    db.add(a); db.flush()
    ops = [OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                                quantidade=1.0, valor_total=100.0, cotacao_cambio=6.0)]
    cot = {"VWRA.L": {"preco": 190.0, "moeda": "USD", "sym": "VWRA.L", "em": "x"}}
    ser = _serializar_ativo(a, ops, {}, cotacoes=cot)
    assert ser["cotacao_auto"] is False
    assert ser["saldo_atual"] == 888.0          # moeda da cotação ≠ ativo → usa manual


def test_renda_fixa_ignora_cotacao(db):
    a = Ativo(nome="CDB", ticker="X", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=100.0)
    db.add(a); db.flush()
    cot = {"X": {"preco": 5.0, "moeda": "BRL", "sym": "X.SA", "em": "x"}}
    ser = _serializar_ativo(a, [], {}, cotacoes=cot)
    assert ser["cotacao_auto"] is False         # renda fixa não usa cotação de mercado
