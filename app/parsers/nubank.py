"""Parser de fatura Nubank (cartão de crédito)."""
import re
from datetime import date

from .helpers import executar_pdftotext


_MES_PT = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

# Vencimento: "Data de vencimento: 13 ABR 2026" (com possível quebra de linha)
_RE_VENC = re.compile(
    r'Data de vencimento[:\s\xa0]*([\s\S]{0,40}?)(\d{1,2})\s+([A-Z]{3})\s+(\d{4})',
    re.IGNORECASE
)

# Linha de transação Nubank. Formatos:
#   "06 MAR  •••• 9530  Mlp *Kabum-Kabum - Parcela 2/10        R$ 46,19"
#   "13 MAR  KaBuM! - NuPay - Parcela 1/10                     R$ 72,06"  (sem cartão)
#   "19 MAR  Recarga de celular                                R$ 20,00"
#   "20 MAR  IOF de \"Blizzard Us...\"                         R$ 14,49"
# Linhas de cabeçalho da seção a ignorar: "Micael I S Salvador  R$ 6.668,16"
# Linhas de "Pagamento em..." na seção "Pagamentos e Financiamentos" - skip.
_RE_TRANS = re.compile(
    r'^\s*(\d{1,2})\s+([A-Z]{3})\s+'
    r'(?:•+\s*\d{4}\s+|nU\s+|\s+)?'  # cartão opcional, ou "nU" (NuPay), ou nada
    r'(.+?)\s+'
    r'([\u2212\-]?R\$\s*[\d.]+,\d{2})\s*$'
)
_RE_PARCELA_DESC = re.compile(r'\s*-\s*Parcela\s+(\d+/\d+)\s*$')


def _parse_brl(s: str) -> float:
    s = s.replace("R$", "").replace("\xa0", "").replace(" ", "")
    # Normaliza sinal de menos: U+2212 (minus matemático) → hyphen ASCII
    s = s.replace("\u2212", "-")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_fatura_nubank(pdf_path: str, senha: str = None) -> dict:
    text = executar_pdftotext(pdf_path, senha=senha)

    # Vencimento
    m = _RE_VENC.search(text)
    if not m:
        raise ValueError("Nubank: não encontrei data de vencimento")
    dia = int(m.group(2))
    mes = _MES_PT[m.group(3).upper()]
    ano = int(m.group(4))
    venc = date(ano, mes, dia)
    mes_ref = f"{venc.month:02d}/{venc.year}"

    # Período da fatura: "Período vigente: 06 MAR a 06 ABR"
    pm = re.search(
        r'Período vigente[:\s\xa0]*(\d{1,2})\s+([A-Z]{3})\s+a\s+(\d{1,2})\s+([A-Z]{3})',
        text, re.IGNORECASE
    )
    if pm:
        d1, mn1, d2, mn2 = pm.groups()
        m1, m2 = _MES_PT[mn1.upper()], _MES_PT[mn2.upper()]
        # ano: o fim do período tem que ser <= venc; o início pode estar no ano anterior
        per_fim = date(venc.year, m2, int(d2)) if m2 <= venc.month else date(venc.year - 1, m2, int(d2))
        per_inicio = date(per_fim.year, m1, int(d1)) if m1 <= per_fim.month else date(per_fim.year - 1, m1, int(d1))
    else:
        per_fim = venc
        per_inicio = date(venc.year, max(1, venc.month - 1), 1)

    transacoes: list[dict] = []
    in_pagamentos = False  # seção "Pagamentos e Financiamentos" - pular

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        if "Pagamentos e Financiamentos" in line:
            in_pagamentos = True
            continue
        if in_pagamentos:
            # Continua até próxima seção (não há outra na fatura Nubank, então fica skip até fim)
            continue

        m = _RE_TRANS.match(line)
        if not m:
            continue

        dia_str, mes_str, desc, valor_str = m.groups()

        try:
            valor = _parse_brl(valor_str)
        except ValueError:
            continue

        # Detecta sinal negativo (hyphen ASCII OU minus unicode U+2212).
        # Estornos e créditos vêm com sinal negativo na fatura — viram Receita
        # (entrada de dinheiro pra você, "abate" da despesa).
        valor_str_clean = valor_str.strip()
        eh_negativo = (
            valor_str_clean.startswith("-")
            or valor_str_clean.startswith("\u2212")
            or valor < 0
        )
        if eh_negativo:
            valor = abs(valor)
            tipo_trans = "Receita"
        else:
            tipo_trans = "Despesa"

        if valor <= 0:
            continue

        try:
            mes_num = _MES_PT[mes_str.upper()]
        except KeyError:
            continue

        # Inferir ano: a transação tem que cair entre per_inicio e per_fim
        if mes_num == per_fim.month and int(dia_str) <= per_fim.day:
            ano_t = per_fim.year
        elif mes_num == per_inicio.month:
            ano_t = per_inicio.year
        elif per_inicio.month < mes_num < per_fim.month:
            ano_t = per_fim.year
        else:
            # caso transações com data fora do período (ex.: estornos antigos)
            ano_t = per_fim.year if mes_num <= per_fim.month else per_fim.year - 1

        try:
            t_date = date(ano_t, mes_num, int(dia_str))
        except ValueError:
            continue

        # Extrai parcela do final da descrição
        parcela = None
        pm_p = _RE_PARCELA_DESC.search(desc)
        if pm_p:
            parcela = pm_p.group(1)
            desc = desc[:pm_p.start()].rstrip()

        # Limpa descrição
        desc_clean = re.sub(r"\s+", " ", desc).strip()
        # Pulamos linhas que não são transação real (ex.: o subtotal "Micael I S Salvador R$ X")
        if desc_clean.lower().startswith("micael"):
            continue

        transacoes.append({
            "data_compra": t_date,
            "descricao": desc_clean,
            "valor": valor,
            "tipo": tipo_trans,
            "parcela": parcela,
            "secao": "parcelamento" if parcela else "despesa",
            "cartao_final4": None,  # Nubank tem múltiplos cartões internos, não fixamos
        })

    return {
        "banco": "Nubank",
        "vencimento": venc,
        "mes_ref": mes_ref,
        "periodo_inicio": per_inicio,
        "periodo_fim": per_fim,
        "transacoes": transacoes,
    }


if __name__ == "__main__":
    import sys
    bill = parse_fatura_nubank(sys.argv[1])
    print(f"Banco: {bill['banco']} | Venc: {bill['vencimento']} | Ref: {bill['mes_ref']}")
    print(f"Período: {bill['periodo_inicio']} a {bill['periodo_fim']}")
    print(f"Transações: {len(bill['transacoes'])}")
    print()
    total = 0
    for t in bill["transacoes"]:
        total += t["valor"]
        print(f"  {t['data_compra']}  {t['descricao'][:40]:<42} {(t['parcela'] or '-'):<7} {t['valor']:>9.2f}")
    print(f"\n  TOTAL: R$ {total:,.2f}")
