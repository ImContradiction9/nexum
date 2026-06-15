"""Regressões dos fixes de bug/performance da revisão:
- /alocacao é GET puro: NÃO grava snapshot de patrimônio (efeito colateral).
- classificar() aceita regras pré-carregadas (evita query por transação no import)
  e produz o mesmo resultado que carregando do banco.
- cache_mem: memoiza leitura com invalidação explícita.
- Totais de transações agregados no SQL = mesma conta da versão em Python.
"""
from datetime import date

from app import cache_mem
from app.database import Ativo, PatrimonioSnapshot, Regra, Categoria, Conta, Transacao
from app.routers.investimentos import alocacao, resumo_investimentos
from app.routers.transacoes import listar_transacoes, _eh_abatedora
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


# ----------------------------------------------------------------------------
# cache_mem: memoização com invalidação
# ----------------------------------------------------------------------------

def test_cache_mem_memoiza_e_invalida():
    chamadas = {"n": 0}

    def produtor():
        chamadas["n"] += 1
        return chamadas["n"]

    a = cache_mem.get_or_set("k", 60, produtor)
    b = cache_mem.get_or_set("k", 60, produtor)
    assert a == b == 1            # 2ª chamada veio do cache (produtor não rodou de novo)
    assert chamadas["n"] == 1

    cache_mem.invalidar("k")
    c = cache_mem.get_or_set("k", 60, produtor)
    assert c == 2                  # após invalidar, recomputa
    assert chamadas["n"] == 2


def test_cache_mem_ttl_zero_nao_guarda():
    chamadas = {"n": 0}

    def produtor():
        chamadas["n"] += 1
        return chamadas["n"]

    cache_mem.get_or_set("z", 0, produtor)
    cache_mem.get_or_set("z", 0, produtor)
    assert chamadas["n"] == 2      # ttl=0 expira na hora, sempre recomputa


# ----------------------------------------------------------------------------
# Totais de transações: agregação SQL == lógica antiga em Python
# ----------------------------------------------------------------------------

def _conta(db):
    c = Conta(nome="Conta", tipo="Conta Corrente")
    db.add(c); db.commit(); db.refresh(c)
    return c


def _cat(db, nome, tipo):
    c = Categoria(nome=nome, tipo=tipo)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _tx(db, conta, valor, tipo, categoria_id=None):
    t = Transacao(
        conta_id=conta.id, data=date(2026, 5, 10), descricao="X",
        descricao_normalizada="x", valor=valor, tipo=tipo,
        mes_referencia="05/2026", categoria_origem="nao_categorizado",
        categoria_id=categoria_id,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def _soma_python(db):
    """Recalcula os totais pela lógica antiga (carregando tudo) p/ comparar."""
    itens = db.query(Transacao).all()
    rec = desp = 0.0
    for tr in itens:
        v = tr.valor or 0.0
        if _eh_abatedora(tr):
            desp -= v
        elif tr.tipo == "Receita":
            rec += v
        else:
            desp += v
    return rec, desp


def test_totais_transacoes_sql_bate_com_python(db):
    conta = _conta(db)
    mercado = _cat(db, "Mercado", "Despesa")
    salario = _cat(db, "Salário", "Receita")
    cashback = _cat(db, "Cashback", "Despesa")   # exceção: continua receita

    _tx(db, conta, 200.0, "Despesa", mercado.id)        # despesa normal
    _tx(db, conta, 100.0, "Despesa", None)              # despesa sem categoria
    _tx(db, conta, 1000.0, "Receita", salario.id)       # receita normal
    _tx(db, conta, 50.0, "Receita", mercado.id)         # abatedora → abate despesa
    _tx(db, conta, 30.0, "Receita", cashback.id)        # cashback → receita

    res = listar_transacoes(mes=None, data_inicio=None, data_fim=None, db=db)
    rec_py, desp_py = _soma_python(db)

    assert res["total_receitas"] == rec_py == 1030.0    # 1000 + 30
    assert res["total_despesas"] == desp_py == 250.0    # 200 + 100 - 50
    assert res["saldo"] == 780.0


def test_totais_respeitam_filtro_de_categoria(db):
    conta = _conta(db)
    mercado = _cat(db, "Mercado", "Despesa")
    outros = _cat(db, "Outros", "Despesa")
    _tx(db, conta, 200.0, "Despesa", mercado.id)
    _tx(db, conta, 70.0, "Despesa", outros.id)

    res = listar_transacoes(mes=None, data_inicio=None, data_fim=None,
                            categoria_id=mercado.id, db=db)
    assert res["total_despesas"] == 200.0    # só a categoria filtrada entra no total
    assert res["total_receitas"] == 0.0


def test_filtro_tipo_entradas_saidas(db):
    conta = _conta(db)
    salario = _cat(db, "Salário", "Receita")
    _tx(db, conta, 1000.0, "Receita", salario.id)
    _tx(db, conta, 1500.0, "Receita", salario.id)
    _tx(db, conta, 200.0, "Despesa", None)
    _tx(db, conta, 300.0, "Despesa", None)

    entradas = listar_transacoes(mes=None, data_inicio=None, data_fim=None, tipo="Receita", db=db)
    assert {i["tipo"] for i in entradas["items"]} == {"Receita"}
    assert entradas["total_receitas"] == 2500.0
    assert entradas["total_despesas"] == 0.0

    saidas = listar_transacoes(mes=None, data_inicio=None, data_fim=None, tipo="Despesa", db=db)
    assert {i["tipo"] for i in saidas["items"]} == {"Despesa"}
    assert saidas["total_despesas"] == 500.0
    assert saidas["total_receitas"] == 0.0

    tudo = listar_transacoes(mes=None, data_inicio=None, data_fim=None, db=db)
    assert len(tudo["items"]) == 4         # sem filtro = tudo
