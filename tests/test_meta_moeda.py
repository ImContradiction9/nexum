"""Meta com alvo em moeda estrangeira: o valor_alvo é convertido pra BRL pela
cotação atual (ajusta sozinho)."""
from app.database import Meta, Configuracao
from app.routers.metas import _calcular_saldos_brl, _serializar_meta


def test_meta_usd_converte_alvo_pela_cotacao(db):
    db.add(Configuracao(chave="cambio_usd", valor="5.00"))
    db.commit()
    saldos = _calcular_saldos_brl(db)
    m = Meta(nome="Reserva em dólar", escopo="manual",
             valor_atual_manual=2500.0, valor_alvo=1000.0, moeda="USD")
    d = _serializar_meta(m, saldos)
    assert d["moeda"] == "USD"
    assert d["valor_alvo_brl"] == 5000.0     # 1000 USD * 5,00
    assert d["cambio_usado"] == 5.0
    assert d["percentual"] == 50.0           # 2500 BRL / 5000 BRL
    assert d["falta"] == 2500.0


def test_meta_brl_nao_muda(db):
    saldos = _calcular_saldos_brl(db)
    m = Meta(nome="Meta BRL", escopo="manual",
             valor_atual_manual=500.0, valor_alvo=1000.0, moeda="BRL")
    d = _serializar_meta(m, saldos)
    assert d["valor_alvo_brl"] == 1000.0
    assert d["percentual"] == 50.0
    assert d["cambio_usado"] is None


def test_meta_usd_sobe_quando_dolar_sobe(db):
    """Mesma meta em USD: alvo em BRL acompanha a alta do dólar."""
    db.add(Configuracao(chave="cambio_usd", valor="6.00"))
    db.commit()
    saldos = _calcular_saldos_brl(db)
    m = Meta(nome="USD", escopo="manual", valor_atual_manual=0, valor_alvo=1000.0, moeda="USD")
    d = _serializar_meta(m, saldos)
    assert d["valor_alvo_brl"] == 6000.0     # subiu junto com o dólar
