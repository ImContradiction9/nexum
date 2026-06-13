"""Acompanhamento de orçamento mensal por categoria (/api/orcamentos)."""
from datetime import date

from app.database import Categoria, Conta, Transacao
from app.routers.dashboard import orcamentos


def _conta(db):
    c = Conta(nome="Carteira", tipo="Carteira"); db.add(c); db.commit(); db.refresh(c)
    return c


def _desp(db, conta, cat, valor, mes="06/2026", tipo="Despesa"):
    db.add(Transacao(
        conta_id=conta.id, data=date(2026, 6, 10), descricao="x", descricao_normalizada="x",
        valor=valor, tipo=tipo, mes_referencia=mes, categoria_id=cat.id,
    ))


def test_orcamento_gasto_vs_teto(db):
    conta = _conta(db)
    merc = Categoria(nome="Mercado", tipo="Despesa", orcamento_mensal=1000.0, ativo=True, orcado=True)
    lazer = Categoria(nome="Lazer", tipo="Despesa", orcamento_mensal=500.0, ativo=True, orcado=True)
    # fora do orçamento (orcado=False) mesmo tendo gasto → não aparece
    fora = Categoria(nome="Outros", tipo="Despesa", orcamento_mensal=0.0, ativo=True, orcado=False)
    db.add_all([merc, lazer, fora]); db.commit()
    _desp(db, conta, merc, 600.0); _desp(db, conta, merc, 700.0)   # 1300 → estoura 1000
    _desp(db, conta, lazer, 100.0)                                  # 100 de 500
    _desp(db, conta, fora, 999.0)                                   # fora → ignorado
    db.commit()

    r = orcamentos(mes="06/2026", db=db)
    by = {i["nome"]: i for i in r["itens"]}
    assert "Outros" not in by                      # fora do orçamento não aparece
    assert by["Mercado"]["gasto"] == 1300.0
    assert by["Mercado"]["restante"] == -300.0
    assert by["Mercado"]["estourou"] is True
    assert by["Mercado"]["pct"] == 130.0
    assert by["Lazer"]["gasto"] == 100.0
    assert by["Lazer"]["estourou"] is False
    assert by["Lazer"]["pct"] == 20.0
    # ordenado por pct desc → Mercado antes de Lazer
    assert [i["nome"] for i in r["itens"]] == ["Mercado", "Lazer"]
    assert r["total_orcado"] == 1500.0
    assert r["total_gasto"] == 1400.0


def test_orcamento_no_orcamento_sem_teto(db):
    """Categoria marcada 'no orçamento' mas SEM teto: aparece, acompanha o gasto,
    não estoura (tem_teto=False)."""
    conta = _conta(db)
    cat = Categoria(nome="Esporádicos", tipo="Despesa", orcamento_mensal=0.0, ativo=True, orcado=True)
    db.add(cat); db.commit()
    _desp(db, conta, cat, 450.0); db.commit()
    r = orcamentos(mes="06/2026", db=db)
    item = next(i for i in r["itens"] if i["nome"] == "Esporádicos")
    assert item["tem_teto"] is False
    assert item["gasto"] == 450.0
    assert item["estourou"] is False
    assert item["pct"] == 0


def test_orcamento_outro_mes_nao_conta(db):
    conta = _conta(db)
    merc = Categoria(nome="Mercado", tipo="Despesa", orcamento_mensal=1000.0, ativo=True, orcado=True)
    db.add(merc); db.commit()
    _desp(db, conta, merc, 800.0, mes="05/2026")   # mês diferente
    db.commit()
    r = orcamentos(mes="06/2026", db=db)
    assert r["itens"][0]["gasto"] == 0.0           # nada gasto em 06/2026
