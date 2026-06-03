"""Movimentação interna: pagamento de fatura e transferência deixam de ser
categorias e viram a flag transacoes.movimentacao.

Cobre:
  - heurística de detecção (fatura; transferência só p/ pessoa física com nome
    de titular; PJ/CNPJ não vira transferência);
  - PATCH marcando/desmarcando a flag;
  - listagem esconde movimentações por padrão e mostra com incluir_transferencias;
  - dashboard não soma movimentações nos totais.
"""
from datetime import date

from app.importacao import (
    _eh_pagamento_fatura,
    _eh_transferencia_interconta,
    _parece_pessoa_fisica,
)
from app.routers.transacoes import atualizar_transacao, listar_transacoes
from app.routers.dashboard import dashboard
from app.database import Transacao, Categoria, Conta


# ----------------------------------------------------------------------------
# Heurística de detecção (funções puras usadas na importação OFX)
# ----------------------------------------------------------------------------

def test_detecta_pagamento_de_fatura():
    assert _eh_pagamento_fatura("PAGAMENTO DE FATURA CARTAO", "")
    assert _eh_pagamento_fatura("PGTO FATURA", "")
    assert _eh_pagamento_fatura("Compra mercado", "Pagamento de Fatura")
    assert not _eh_pagamento_fatura("IFOOD DELIVERY", "Débito")


def test_parece_pessoa_fisica_vs_pj():
    # CPF (mascarado ou não) → pessoa física
    assert _parece_pessoa_fisica("Pix enviado - Micael Italo - ***.123.456-**")
    assert _parece_pessoa_fisica("Transferência - Andreina Souza - 123.456.789-00")
    # CNPJ → PJ
    assert not _parece_pessoa_fisica("Pix - Micael Italo Comercio LTDA - 12.345.678/0001-90")


def test_transferencia_so_com_nome_titular_e_pf():
    nomes = ["Micael Italo Xavier", "Andreina Souza Lima"]
    # Nome de titular + CPF → transferência
    assert _eh_transferencia_interconta(
        "Pix enviado - Micael Italo Xavier - ***.123.456-**", nomes
    )
    # Mesmo nome de titular, mas contraparte é PJ (CNPJ) → NÃO é transferência
    assert not _eh_transferencia_interconta(
        "Pix - Micael Italo Comercio - 12.345.678/0001-90", nomes
    )
    # Só o primeiro nome em comum (loja) → NÃO bate (exige 2 partes)
    assert not _eh_transferencia_interconta("Compra na Micael Calçados", nomes)
    # Sem nome de titular → NÃO é transferência
    assert not _eh_transferencia_interconta("Pix - Joao da Silva - ***.999.888-**", nomes)


# ----------------------------------------------------------------------------
# Fixtures locais
# ----------------------------------------------------------------------------

def _conta(db):
    c = Conta(nome="Nubank Conta", tipo="Conta Corrente")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _trans(db, conta, **kw):
    t = Transacao(
        conta_id=conta.id,
        data=kw.pop("data", date(2026, 5, 10)),
        descricao=kw.pop("descricao", "LANCAMENTO"),
        descricao_normalizada="lancamento",
        valor=kw.pop("valor", 100.0),
        tipo=kw.pop("tipo", "Despesa"),
        mes_referencia=kw.pop("mes_referencia", "05/2026"),
        categoria_origem=kw.pop("categoria_origem", "nao_categorizado"),
        **kw,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ----------------------------------------------------------------------------
# PATCH: marca/desmarca movimentação
# ----------------------------------------------------------------------------

def test_patch_marca_movimentacao_limpa_categoria(db):
    cat = Categoria(nome="Mercado", tipo="Despesa")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    conta = _conta(db)
    t = _trans(db, conta, categoria_id=cat.id, categoria_origem="manual")

    out = atualizar_transacao(t.id, {"movimentacao": "fatura"}, db=db)
    db.refresh(t)
    assert t.movimentacao == "fatura"
    assert t.categoria_id is None
    assert t.categoria_origem == "movimentacao"
    assert out["movimentacao"] == "fatura"


def test_patch_desmarca_movimentacao(db):
    conta = _conta(db)
    t = _trans(db, conta, movimentacao="transferencia", categoria_origem="movimentacao")

    atualizar_transacao(t.id, {"movimentacao": None}, db=db)
    db.refresh(t)
    assert t.movimentacao is None
    assert t.categoria_origem == "nao_categorizado"


# ----------------------------------------------------------------------------
# Listagem: esconde por padrão, mostra com incluir_transferencias
# ----------------------------------------------------------------------------

def test_listagem_esconde_movimentacao_por_padrao(db):
    conta = _conta(db)
    _trans(db, conta, descricao="COMPRA NORMAL", valor=50.0)
    _trans(db, conta, descricao="PGTO FATURA", valor=900.0,
           movimentacao="fatura", categoria_origem="movimentacao")

    # mes/data_inicio/data_fim usam Query(None) — passa explícito ao chamar direto.
    padrao = listar_transacoes(mes=None, data_inicio=None, data_fim=None, db=db)
    descricoes = [i["descricao"] for i in padrao["items"]]
    assert "COMPRA NORMAL" in descricoes
    assert "PGTO FATURA" not in descricoes

    com_tudo = listar_transacoes(
        mes=None, data_inicio=None, data_fim=None, incluir_transferencias=True, db=db
    )
    descricoes_tudo = [i["descricao"] for i in com_tudo["items"]]
    assert "PGTO FATURA" in descricoes_tudo


# ----------------------------------------------------------------------------
# Dashboard: movimentação não entra nos totais
# ----------------------------------------------------------------------------

def test_dashboard_ignora_movimentacao_nos_totais(db):
    cat = Categoria(nome="Mercado", tipo="Despesa")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    conta = _conta(db)
    _trans(db, conta, descricao="MERCADO", valor=200.0, categoria_id=cat.id)
    _trans(db, conta, descricao="PGTO FATURA", valor=5000.0,
           movimentacao="fatura", categoria_origem="movimentacao")

    out = dashboard(mes="05/2026", db=db)
    # Só a despesa normal entra; a fatura (5000) fica fora.
    assert out["despesas"] == 200.0
    assert out["totais_especiais"].get("Pagamento de Fatura") == 5000.0
