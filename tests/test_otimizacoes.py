"""Regressões dos fixes de bug/performance da revisão:
- /alocacao é GET puro: NÃO grava snapshot de patrimônio (efeito colateral).
- classificar() aceita regras pré-carregadas (evita query por transação no import)
  e produz o mesmo resultado que carregando do banco.
"""
from datetime import date

from app.database import Ativo, PatrimonioSnapshot, Regra, Categoria
from app.routers.investimentos import alocacao, resumo_investimentos
from app.categorizacao import classificar, carregar_regras_ativas


def test_alocacao_nao_grava_snapshot(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=1000.0))
    db.commit()
    assert db.query(PatrimonioSnapshot).count() == 0
    alocacao(db=db)                                   # GET puro
    assert db.query(PatrimonioSnapshot).count() == 0  # nada gravado


def test_resumo_ainda_grava_snapshot(db):
    db.add(Ativo(nome="A", tipo="CDB", moeda="BRL", ativo=True, saldo_atual=1000.0))
    db.commit()
    resumo_investimentos(db=db)                        # endpoint /resumo
    assert db.query(PatrimonioSnapshot).count() == 1   # foto do dia gravada


def test_classificar_regras_precarregadas_igual_ao_banco(db):
    cat = Categoria(nome="Mercado", tipo="Despesa")
    db.add(cat); db.flush()
    db.add(Regra(palavra_chave="SUPERMERCADO", categoria_id=cat.id, prioridade=1, ativa=True))
    db.commit()

    via_banco = classificar(db, "COMPRA SUPERMERCADO XPTO")
    regras = carregar_regras_ativas(db)
    via_cache = classificar(db, "COMPRA SUPERMERCADO XPTO", regras=regras)

    assert via_banco.categoria_id == cat.id
    assert via_cache.categoria_id == via_banco.categoria_id
    assert via_cache.categoria_origem == "regra"
