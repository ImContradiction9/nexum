"""Resgate total: encerra o título (saldo → 0); o valor é o líquido recebido."""
from datetime import date

from app.database import Ativo, OperacaoInvestimento
from app.routers.investimentos import _serializar_ativo


def test_resgate_total_zera_o_titulo(db):
    a = Ativo(nome="CDB", tipo="CDB", moeda="BRL", cdi_percentual=100.0, ativo=True)
    db.add(a); db.flush()
    ops = [
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                             valor_total=1000.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Resgate", data=date(2024, 6, 1),
                             valor_total=1050.0, resgate_total=True),
    ]
    ser = _serializar_ativo(a, ops, {})
    assert ser["saldo_atual"] == 0.0
    # ganho líquido realizado = 1050 (recebido) - 1000 (investido) = 50
    assert round(ser["rentab_moeda"], 2) == 50.0


def test_resgate_parcial_sem_flag_nao_zera(db):
    a = Ativo(nome="CDB2", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=1100.0)
    db.add(a); db.flush()
    ops = [
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                             valor_total=1000.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Resgate", data=date(2024, 6, 1),
                             valor_total=500.0, resgate_total=False),
    ]
    ser = _serializar_ativo(a, ops, {})
    assert ser["saldo_atual"] == 1100.0   # saldo manual mantém; não zera


def test_aporte_depois_do_resgate_total_nao_zera(db):
    # Se houver aporte DEPOIS do resgate total, o título voltou a ter saldo.
    a = Ativo(nome="CDB3", tipo="CDB", moeda="BRL", ativo=True)
    db.add(a); db.flush()
    ops = [
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2024, 1, 1),
                             valor_total=1000.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Resgate", data=date(2024, 6, 1),
                             valor_total=1050.0, resgate_total=True),
        OperacaoInvestimento(ativo_id=a.id, tipo="Aporte", data=date(2024, 7, 1),
                             valor_total=300.0),
    ]
    ser = _serializar_ativo(a, ops, {})
    assert ser["saldo_atual"] != 0.0   # reaberto com o novo aporte
