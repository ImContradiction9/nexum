"""Dashboard: quebra de despesas por parcelamento (à vista × parcelada).

- à vista  = sem parcela
- 1ª parcela (01/N) = compra deste mês
- 02/N+    = parcela de compra de ANTES
A soma dos três buckets tem que bater com o total de despesas.
"""
from datetime import date

from app.database import Conta, Categoria, Transacao
from app.routers.dashboard import dashboard, _bucket_parcelamento
from app.routers.transacoes import listar_transacoes


def _conta(db):
    c = Conta(nome="Cartão", tipo="Cartão de Crédito")
    db.add(c); db.commit(); db.refresh(c)
    return c


def _tx(db, conta, valor, tipo="Despesa", parcela=None, categoria_id=None):
    t = Transacao(
        conta_id=conta.id, data=date(2026, 5, 10), descricao="X",
        descricao_normalizada="x", valor=valor, tipo=tipo, parcela=parcela,
        mes_referencia="05/2026", categoria_origem="nao_categorizado",
        categoria_id=categoria_id,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_bucket_classifica_parcela():
    class _T:
        def __init__(self, p): self.parcela = p
    assert _bucket_parcelamento(_T(None)) == "avista"
    assert _bucket_parcelamento(_T("")) == "avista"
    assert _bucket_parcelamento(_T("01/03")) == "primeira"
    assert _bucket_parcelamento(_T("02/03")) == "anteriores"
    assert _bucket_parcelamento(_T("10/10")) == "anteriores"
    assert _bucket_parcelamento(_T("xx")) == "primeira"   # parcelada sem nº legível


def test_dashboard_por_parcelamento(db):
    conta = _conta(db)
    desp_cat = Categoria(nome="Compras", tipo="Despesa")
    db.add(desp_cat); db.commit(); db.refresh(desp_cat)

    _tx(db, conta, 100.0)                       # à vista
    _tx(db, conta, 50.0, parcela="01/03")       # 1ª parcela (deste mês)
    _tx(db, conta, 30.0, parcela="02/03")       # de antes
    _tx(db, conta, 20.0, parcela="05/10")       # de antes
    # Abatedora (Receita c/ categoria de Despesa) sem parcela → abate do à vista
    _tx(db, conta, 10.0, tipo="Receita", categoria_id=desp_cat.id)

    d = dashboard(mes="05/2026", db=db)
    p = d["por_parcelamento"]
    assert p["a_vista"] == 90.0                  # 100 - 10 (abatedora)
    assert p["parcelada_primeira"] == 50.0
    assert p["parcelada_anteriores"] == 50.0     # 30 + 20
    # Soma dos buckets = despesas líquidas
    assert round(p["a_vista"] + p["parcelada_primeira"] + p["parcelada_anteriores"], 2) \
        == round(d["despesas"], 2) == 190.0


def test_filtro_transacoes_por_parcelamento(db):
    conta = _conta(db)
    _tx(db, conta, 100.0)                       # à vista
    _tx(db, conta, 50.0, parcela="01/03")       # 1ª deste mês
    _tx(db, conta, 30.0, parcela="02/03")       # de antes
    _tx(db, conta, 20.0, parcela="05/10")       # de antes

    def _val(parc):
        r = listar_transacoes(mes=None, data_inicio=None, data_fim=None,
                              parcelamento=parc, db=db)
        return sorted(round(i["valor"], 2) for i in r["items"])

    assert _val("avista") == [100.0]
    assert _val("parcelada") == [20.0, 30.0, 50.0]
    assert _val("primeira") == [50.0]
    assert _val("anteriores") == [20.0, 30.0]
    # Sem filtro = todas
    todas = listar_transacoes(mes=None, data_inicio=None, data_fim=None, db=db)
    assert len(todas["items"]) == 4
