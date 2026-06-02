"""Evolução do patrimônio: investido acumulado (reconstruído) + snapshots."""
from datetime import date

from app.database import Ativo, OperacaoInvestimento, PatrimonioSnapshot
from app.routers.investimentos import evolucao_patrimonio, _intervalo_meses


def test_intervalo_meses():
    assert _intervalo_meses("2026-01", "2026-03") == ["2026-01", "2026-02", "2026-03"]
    assert _intervalo_meses("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_evolucao_investido_acumulado_e_snapshot(db):
    a = Ativo(nome="X", tipo="CDB", moeda="BRL", ativo=True)
    db.add(a); db.flush()
    db.add_all([
        OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2026, 1, 10), valor_total=1000.0),
        OperacaoInvestimento(ativo_id=a.id, tipo="Aporte", data=date(2026, 2, 5), valor_total=500.0),
    ])
    db.add(PatrimonioSnapshot(data=date(2026, 2, 20), total_brl=1600.0, investido_brl=1500.0))
    db.commit()
    serie = {p["mes"]: p for p in evolucao_patrimonio(db=db)["serie"]}
    assert serie["2026-01"]["investido"] == 1000.0
    assert serie["2026-02"]["investido"] == 1500.0       # acumulado
    assert serie["2026-02"]["patrimonio"] == 1600.0      # snapshot do mês
    assert serie["2026-01"]["patrimonio"] is None        # sem snapshot em jan


def test_evolucao_vazia(db):
    assert evolucao_patrimonio(db=db)["serie"] == []
