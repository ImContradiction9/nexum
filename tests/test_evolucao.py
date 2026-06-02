"""Evolução do patrimônio: investido acumulado (reconstruído) + snapshots."""
from datetime import date, timedelta

from app.database import Ativo, OperacaoInvestimento, PatrimonioSnapshot, CDIDiario
from app.routers.investimentos import evolucao_patrimonio, _intervalo_meses


def test_intervalo_meses():
    assert _intervalo_meses("2026-01", "2026-03") == ["2026-01", "2026-02", "2026-03"]
    assert _intervalo_meses("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_evolucao_investido_acumulado_e_snapshot(db):
    a = Ativo(nome="X", tipo="CDB", moeda="BRL", ativo=True)   # sem cdi_percentual → custo
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
    # Patrimônio agora é reconstruído mês a mês (não mais um ponto só):
    assert serie["2026-01"]["patrimonio"] == 1000.0      # jan: custo acumulado (sem cotação histórica)
    assert serie["2026-02"]["patrimonio"] == 1600.0      # fev: snapshot real vence a reconstrução


def test_evolucao_reconstroi_renda_fixa_cdi(db):
    """Renda fixa CDI rende no histórico reconstruído: o patrimônio do mês
    seguinte ao aporte fica acima do custo (sem precisar de snapshot)."""
    a = Ativo(nome="CDB CDI", tipo="CDB", moeda="BRL", ativo=True, cdi_percentual=100.0)
    db.add(a); db.flush()
    db.add(OperacaoInvestimento(ativo_id=a.id, tipo="Compra", data=date(2026, 1, 5), valor_total=1000.0))
    # Série CDI ~0.05%/dia útil em jan e fev (preenche todos os dias do período).
    d = date(2026, 1, 1)
    while d <= date(2026, 2, 28):
        if d.weekday() < 5:
            db.add(CDIDiario(data=d, taxa=0.05))
        d += timedelta(days=1)
    db.commit()
    serie = {p["mes"]: p for p in evolucao_patrimonio(db=db)["serie"]}
    assert serie["2026-01"]["investido"] == 1000.0
    # Reconstrução CDI: rendeu acima do custo em jan e mais ainda em fev.
    assert serie["2026-01"]["patrimonio"] > 1000.0
    assert serie["2026-02"]["patrimonio"] > serie["2026-01"]["patrimonio"]


def test_evolucao_vazia(db):
    assert evolucao_patrimonio(db=db)["serie"] == []
