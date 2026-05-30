"""Regressão: categorização individual via PATCH /api/transacoes/{trans_id}.

Bug encontrado em 2026-05-29: a função `atualizar_transacao` ficou SEM o
decorator `@app.patch(...)`, então a rota não existia. Toda categorização
individual recebia 404 e a categoria nunca persistia ("não salva/volta").
"""
from datetime import date

from app.main import app
from app.routers.transacoes import atualizar_transacao
from app.database import Transacao, Categoria, Conta


def test_rota_patch_transacao_registrada():
    """Guarda direta do bug: a rota PATCH precisa existir."""
    metodos = set()
    for r in app.router.routes:
        if getattr(r, "path", None) == "/api/transacoes/{trans_id}":
            metodos |= set(getattr(r, "methods", set()) or set())
    assert "PATCH" in metodos


def _conta(db):
    c = Conta(nome="Carteira", tipo="Carteira")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _transacao(db, conta, **kw):
    t = Transacao(
        conta_id=conta.id, data=date.today(), descricao="MERCADO XPTO",
        descricao_normalizada="mercado xpto", valor=50.0, tipo="Despesa",
        mes_referencia=date.today().strftime("%m/%Y"),
        categoria_origem=kw.pop("categoria_origem", "nao_categorizado"), **kw,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_patch_persiste_categoria_e_marca_manual(db):
    cat = Categoria(nome="Mercado", tipo="Despesa")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    t = _transacao(db, _conta(db))

    atualizar_transacao(t.id, {"categoria_id": cat.id}, db=db)

    db.refresh(t)
    assert t.categoria_id == cat.id
    assert t.categoria_origem == "manual"


def test_patch_remove_categoria(db):
    cat = Categoria(nome="Lazer", tipo="Despesa")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    t = _transacao(db, _conta(db), categoria_id=cat.id, categoria_origem="manual")

    atualizar_transacao(t.id, {"categoria_id": None}, db=db)

    db.refresh(t)
    assert t.categoria_id is None
