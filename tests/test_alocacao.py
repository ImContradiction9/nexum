"""Alocação por classe + rebalanceamento (quanto comprar/vender pro alvo)."""
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


def test_rebalanceamento_com_alvo(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=600.0))
    db.add(Ativo(nome="B", tipo="Ação BR", moeda="BRL", ativo=True, saldo_atual=400.0))
    db.commit()
    r = salvar_alocacao_alvo({"alvo": {"CDB": 50, "Ação BR": 50}}, db=db)
    by = {l["tipo"]: l for l in r["linhas"]}
    assert r["soma_alvo"] == 100.0
    # alvo 50% de 1000 = 500 → CDB (600) vende 100; Ação (400) compra 100
    assert by["CDB"]["delta_brl"] == -100.0
    assert by["Ação BR"]["delta_brl"] == 100.0


def test_alvo_em_classe_sem_posicao(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=1000.0))
    db.commit()
    r = salvar_alocacao_alvo({"alvo": {"CDB": 80, "FII": 20}}, db=db)
    by = {l["tipo"]: l for l in r["linhas"]}
    # FII sem posição mas com alvo 20% de 1000 = 200 a comprar
    assert by["FII"]["atual_brl"] == 0.0
    assert by["FII"]["delta_brl"] == 200.0
