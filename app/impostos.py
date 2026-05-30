"""
Impostos sobre renda fixa (estimativa de saldo/rendimento LÍQUIDO).

Regras (Brasil):

**IR (Imposto de Renda)** — tabela regressiva por prazo, incide sobre o
rendimento no resgate:
    até 180 dias .............. 22,5%
    181 a 360 dias ............ 20,0%
    361 a 720 dias ............ 17,5%
    acima de 720 dias ......... 15,0%
LCI e LCA são ISENTAS de IR para pessoa física.

**IOF** — tabela regressiva só nos primeiros 30 dias, incide sobre o
rendimento (resgate antes de 30 dias). A partir do 30º dia, IOF = 0.

Ordem de incidência: IOF primeiro (sobre o rendimento), depois IR sobre o
rendimento já líquido de IOF. Tudo aqui é ESTIMATIVA — o app não substitui o
informe de rendimentos da corretora.
"""
from __future__ import annotations

# Tipos de renda fixa isentos de IR para pessoa física.
TIPOS_ISENTOS_IR = {"LCI", "LCA"}

# IOF regressivo: percentual do rendimento retido conforme o nº de dias
# corridos. Índice 0 não é usado; dias 1..29 abaixo; 30+ = 0.
_IOF_TABELA = {
    1: 0.96, 2: 0.93, 3: 0.90, 4: 0.86, 5: 0.83, 6: 0.80, 7: 0.76,
    8: 0.73, 9: 0.70, 10: 0.66, 11: 0.63, 12: 0.60, 13: 0.56, 14: 0.53,
    15: 0.50, 16: 0.46, 17: 0.43, 18: 0.40, 19: 0.36, 20: 0.33, 21: 0.30,
    22: 0.26, 23: 0.23, 24: 0.20, 25: 0.16, 26: 0.13, 27: 0.10, 28: 0.06,
    29: 0.03,
}


def isento_ir(tipo: str) -> bool:
    """True se o tipo de ativo é isento de IR (LCI/LCA)."""
    return tipo in TIPOS_ISENTOS_IR


def aliquota_ir(dias: int, tipo: str | None = None) -> float:
    """Alíquota de IR (fração) pela tabela regressiva. Isentos → 0."""
    if tipo is not None and isento_ir(tipo):
        return 0.0
    if dias <= 180:
        return 0.225
    if dias <= 360:
        return 0.20
    if dias <= 720:
        return 0.175
    return 0.15


def aliquota_ir_longo_prazo(tipo: str | None = None) -> float:
    """
    Alíquota de IR para projeções de longo prazo (acima de 720 dias): 15%,
    ou 0 se isento. Usada pra estimar o retorno líquido futuro das metas.
    """
    return 0.0 if (tipo is not None and isento_ir(tipo)) else 0.15


def aliquota_iof(dias: int) -> float:
    """Fração do rendimento retida em IOF conforme os dias corridos (0 após 29)."""
    if dias < 1:
        return 0.0
    return _IOF_TABELA.get(dias, 0.0)


def calcular_liquido(saldo_bruto: float, rendimento_bruto: float,
                     dias: int, tipo: str | None = None) -> dict:
    """
    Estima o saldo líquido de IR + IOF de um título de renda fixa.

    Args:
        saldo_bruto: saldo atual bruto do título.
        rendimento_bruto: ganho acumulado (saldo - principal aplicado).
        dias: prazo decorrido (estimado, p.ex. média ponderada dos aportes).
        tipo: tipo do ativo (define isenção de IR).

    Retorna dict com saldo_liquido, ir_valor, iof_valor, ir_aliquota,
    iof_aliquota, isento_ir. Se não há rendimento positivo, não há imposto.
    """
    if rendimento_bruto <= 0:
        return {
            "saldo_liquido": round(saldo_bruto, 2),
            "ir_valor": 0.0, "iof_valor": 0.0,
            "ir_aliquota": 0.0, "iof_aliquota": 0.0,
            "isento_ir": isento_ir(tipo or ""),
        }

    iof_aliq = aliquota_iof(dias)
    iof_valor = rendimento_bruto * iof_aliq
    base_ir = rendimento_bruto - iof_valor
    ir_aliq = aliquota_ir(dias, tipo)
    ir_valor = base_ir * ir_aliq

    saldo_liquido = saldo_bruto - iof_valor - ir_valor
    return {
        "saldo_liquido": round(saldo_liquido, 2),
        "ir_valor": round(ir_valor, 2),
        "iof_valor": round(iof_valor, 2),
        "ir_aliquota": ir_aliq,
        "iof_aliquota": iof_aliq,
        "isento_ir": isento_ir(tipo or ""),
    }
