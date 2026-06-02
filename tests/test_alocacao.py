"""Alocação por classe + rebalanceamento SÓ por aporte (nunca vende)."""
from app.database import Ativo
from app.routers.investimentos import alocacao, salvar_alocacao_alvo


def test_alocacao_atual(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=600.0))
    db.add(Ativo(nome="B", tipo="Ação BR", moeda="BRL", ativo=True, saldo_atual=400.0))
    db.commit()
    r = alocacao(db=db)
    by = {l["tipo"]: l for l in r["linhas"]}
    assert r["total_brl"] == 1000.0
    assert by["CDB"]["pct_atual"] == 60.0
    assert by["Ação BR"]["pct_atual"] == 40.0
    assert by["CDB"]["delta_brl"] is None        # sem alvo definido ainda


def test_rebalanceamento_so_aporte(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=600.0))
    db.add(Ativo(nome="B", tipo="Ação BR", moeda="BRL", ativo=True, saldo_atual=400.0))
    db.commit()
    r = salvar_alocacao_alvo({"alvo": {"CDB": 50, "Ação BR": 50}}, db=db)
    by = {l["tipo"]: l for l in r["linhas"]}
    assert r["soma_alvo"] == 100.0
    # NUNCA vende: escala o total até a classe mais pesada (CDB 600 @ 50%) bater
    # no alvo → total alvo = 1200. CDB já tem 600 (50%): aporta 0; Ação precisa
    # de 600, tem 400: aporta 200. Nada negativo.
    assert by["CDB"]["aporte_brl"] == 0.0
    assert by["Ação BR"]["aporte_brl"] == 200.0
    assert all(l["aporte_brl"] is None or l["aporte_brl"] >= 0 for l in r["linhas"])
    assert r["aporte_total_brl"] == 200.0


def test_alvo_em_classe_sem_posicao(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=1000.0))
    db.commit()
    r = salvar_alocacao_alvo({"alvo": {"CDB": 80, "FII": 20}}, db=db)
    by = {l["tipo"]: l for l in r["linhas"]}
    # CDB 1000 @ 80% → total alvo = 1250. CDB aporta 0; FII precisa de 20% = 250.
    assert by["FII"]["atual_brl"] == 0.0
    assert by["FII"]["aporte_brl"] == 250.0
    assert by["CDB"]["aporte_brl"] == 0.0
