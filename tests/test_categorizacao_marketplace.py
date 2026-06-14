"""Amazon/Mercado Livre não são auto-categorizados (o nome da loja não diz o
que foi comprado). Atribuição (pra quem) continua valendo. Parcela de compra já
categorizada herda da irmã — coberto em test_partes/importacao."""
from app.database import Categoria, Atribuicao, Memoria, Regra
from app.categorizacao import classificar, _eh_marketplace
from app.utils import normalizar_descricao


def test_deteccao_marketplace():
    assert _eh_marketplace("AMAZON BR SAO PAULO")
    assert _eh_marketplace("MERCADOLIVRE*COMPRA")
    assert _eh_marketplace("Mercado Livre")
    assert not _eh_marketplace("PADARIA DO ZE")
    assert not _eh_marketplace("MERCADO PAGO")  # pagamentos, não o marketplace


def _cat(db, nome):
    c = Categoria(nome=nome, tipo="Despesa"); db.add(c); db.commit(); db.refresh(c)
    return c


def test_amazon_nao_pega_categoria_da_memoria(db):
    cat = _cat(db, "Eletrônicos")
    desc = "AMAZON BR"
    db.add(Memoria(descricao_normalizada=normalizar_descricao(desc),
                   categoria_id=cat.id, contagem=5))
    db.commit()
    c = classificar(db, desc)
    assert c.categoria_id is None                 # NÃO categoriza Amazon
    assert c.categoria_origem == "nao_categorizado"


def test_amazon_mantem_atribuicao(db):
    cat = _cat(db, "Compras")
    atr = Atribuicao(nome="Micael", tipo="Pessoa"); db.add(atr); db.commit(); db.refresh(atr)
    desc = "MERCADOLIVRE*LOJA"
    db.add(Memoria(descricao_normalizada=normalizar_descricao(desc),
                   categoria_id=cat.id, atribuicao_id=atr.id, contagem=3))
    db.commit()
    c = classificar(db, desc)
    assert c.categoria_id is None                 # categoria pulada
    assert c.atribuicao_id == atr.id              # atribuição mantida


def test_loja_normal_continua_categorizando(db):
    cat = _cat(db, "Mercado")
    desc = "SUPERMERCADO BH"
    db.add(Memoria(descricao_normalizada=normalizar_descricao(desc),
                   categoria_id=cat.id, contagem=2))
    db.commit()
    c = classificar(db, desc)
    assert c.categoria_id == cat.id               # loja normal segue categorizando


def test_amazon_ignora_regra_de_categoria(db):
    cat = _cat(db, "Eletrônicos")
    db.add(Regra(palavra_chave="AMAZON", categoria_id=cat.id, ativa=True, prioridade=10))
    db.commit()
    c = classificar(db, "AMAZON BR COMPRA")
    assert c.categoria_id is None                 # regra de categoria não aplica em marketplace
