"""Nubank Ultravioleta: o IOF de câmbio é reembolsado 100% (cobrança "IOF de X"
+ crédito "IOF de volta de X"). O par se anula — nenhum dos dois entra."""
from datetime import date

from app.parsers.nubank import _anular_iof_reembolsado


def _t(desc, valor, tipo):
    return {"data_compra": date(2026, 5, 30), "descricao": desc, "valor": valor,
            "tipo": tipo, "parcela": None, "secao": "despesa", "cartao_final4": None}


def test_anula_par_iof_e_reembolso():
    trans = [
        _t('Preply BERLIN', 97.54, "Despesa"),
        _t('IOF de "Preply"', 13.85, "Despesa"),
        _t('IOF de volta de Preply', 13.85, "Receita"),
        _t('IOF de "Preply"', 25.48, "Despesa"),
        _t('IOF de volta de Preply', 25.48, "Receita"),
        _t('Mercado', 50.00, "Despesa"),
    ]
    out = _anular_iof_reembolsado(trans)
    descs = [t["descricao"] for t in out]
    assert not any("IOF" in d for d in descs)       # nenhum IOF sobrou
    assert "Preply BERLIN" in descs                 # a compra em si fica
    assert "Mercado" in descs
    assert len(out) == 2


def test_iof_sem_reembolso_permanece():
    # Sem "IOF de volta" correspondente, a cobrança continua (conta normal).
    trans = [
        _t('IOF de "Steam"', 5.00, "Despesa"),
        _t('Steam Games', 100.00, "Despesa"),
    ]
    out = _anular_iof_reembolsado(trans)
    assert len(out) == 2
    assert any(t["descricao"] == 'IOF de "Steam"' for t in out)


def test_lojas_diferentes_nao_se_anulam_por_acaso():
    # Mesmo valor, lojas diferentes: NÃO pareia (uma cobrança sem reembolso e um
    # reembolso de outra loja não devem se cancelar).
    trans = [
        _t('IOF de "Alpha"', 10.00, "Despesa"),
        _t('IOF de volta de Beta', 10.00, "Receita"),
    ]
    out = _anular_iof_reembolsado(trans)
    assert len(out) == 2
