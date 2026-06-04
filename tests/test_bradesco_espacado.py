"""
Regressão: fatura Bradesco "VISA Infinite" cuja extração de texto traz as datas
com espaços ao redor da barra (ex.: '15 / 01' em vez de '15/01') e o vencimento
"quebrado" no cabeçalho (mês/ano numa linha, dia isolado noutra).

Antes da correção esse layout produzia 0 transações e o vencimento caía na data
da "Previsão de fechamento da próxima fatura".
"""
from datetime import date

from app.parsers.bradesco import _parse_visa, _dia_mes


def test_dia_mes_tolera_espacos():
    assert _dia_mes("15/01") == (15, 1)
    assert _dia_mes("15 / 01") == (15, 1)
    assert _dia_mes(" 10 /04 ") == (10, 4)


def test_parse_visa_datas_espacadas():
    # Cabeçalho do portador + lançamentos com data 'DD / MM' espaçada.
    texto = "\n".join([
        "  Data  Histórico de Lançamentos                  Cidade        R$",
        "  15 / 01 PAGTO. POR DEB EM C/C                                                     3.237,80  -",
        "  JOANA D ARC COSTA DA SILVA SAL                   Cartão 4066 XXXX XXXX 2028",
        "  10 / 04 MP*CLIMARIO 10/10                       OSASCO                             1.552,27",
        "  29 / 01 LINDT SPRUNGLI 01/02                    Salvador                             147,63",
        "  03 / 02 SEGURO SUPERPROTEGIDO                                                         9,99",
        "  Total para JOANA D ARC COSTA DA SILVA",
        "  SAL                                                                               1.709,89",
    ])
    venc = date(2026, 2, 15)

    def infer_year(mes):
        return venc.year - 1 if mes > venc.month else venc.year

    txs = _parse_visa(texto, venc, infer_year)

    # 3 compras (o PAGTO com '-' e a linha de total são ignorados).
    assert len(txs) == 3
    soma = round(sum(t["valor"] for t in txs), 2)
    assert soma == 1709.89

    by_desc = {t["descricao"]: t for t in txs}
    assert "MP*CLIMARIO" in by_desc
    assert by_desc["MP*CLIMARIO"]["parcela"] == "10/10"
    # Mês posterior ao vencimento (04 > 02) => ano anterior.
    assert by_desc["MP*CLIMARIO"]["data_compra"] == date(2025, 4, 10)
    # Cartão do portador atribuído.
    assert by_desc["MP*CLIMARIO"]["cartao_final4"] == "2028"
    # Mês <= vencimento fica no ano do vencimento.
    assert by_desc["LINDT SPRUNGLI"]["data_compra"] == date(2026, 1, 29)


def test_parse_visa_ignora_pagamento_e_totais():
    texto = "\n".join([
        "  15 / 01 PAGTO. POR DEB EM C/C                                                     3.237,80  -",
        "  Total da fatura em real                                                           4.462,46",
    ])
    venc = date(2026, 2, 15)
    txs = _parse_visa(texto, venc, lambda m: 2026)
    assert txs == []
