"""
Regressão: o total da fatura Santander deve ser o TOTAL OFICIAL (valor a pagar),
não a soma das linhas — que não fecha 100% por causa de arredondamento do banco
e cobranças sem data (ex.: "IOF DESPESA NO EXTERIOR").
"""
from app.parsers.santander import _extrair_total_oficial


def test_extrai_saldo_desta_fatura():
    texto = "\n".join([
        "(+) Total Despesas/Débitos no Brasil                18.339,68",
        "(+) Total Despesas/Débitos no Exterior                  32,90",
        "(-) Total de créditos                                    0,10",
        "(=) Saldo Desta Fatura                              18.372,50",
    ])
    assert _extrair_total_oficial(texto) == 18372.50


def test_extrai_pagamento_total_com_rs():
    texto = "1  Pagamento Total                       R$18.372,50   blá blá"
    assert _extrair_total_oficial(texto) == 18372.50


def test_sem_total_retorna_none():
    assert _extrair_total_oficial("fatura sem linha de total aqui") is None
