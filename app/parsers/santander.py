"""
Parser de fatura Santander (cartão de crédito).
Extrai transações de Despesas + Parcelamentos. Ignora Pagamento de Fatura.

Uso:
    from parser_santander import parse_fatura_santander
    bill = parse_fatura_santander("/path/to/fatura.pdf")
    # bill = {
    #   "banco": "Santander",
    #   "vencimento": date(2026, 5, 5),
    #   "mes_ref": "05/2026",
    #   "periodo_inicio": date(2026, 3, 28),
    #   "periodo_fim":    date(2026, 4, 27),
    #   "transacoes": [ { ... }, ... ]
    # }
"""
import re
from datetime import date, datetime
from pathlib import Path

from .helpers import executar_pdftotext, encontrar_vencimento, reflow_colunas


def _extract_text(pdf_path: str, senha: str = None) -> str:
    """
    Extrai texto preservando layout via pdftotext e, em seguida, reordena
    eventuais páginas em duas colunas (o detalhamento do Santander imprime
    parte das despesas numa segunda coluna lado a lado).
    """
    return reflow_colunas(executar_pdftotext(pdf_path, senha=senha))


def _parse_brl(value_str: str) -> float:
    return float(value_str.replace(".", "").replace(",", "."))


# Regex para uma linha de transação. Permite "lixo" depois do valor por causa
# do layout em duas colunas do PDF.
_RE_TRANS_PARC = re.compile(
    r'(\d{2}/\d{2})\s+(.+?)\s+(\d{2}/\d{2})\s+(-?[\d.]+,\d{2})(?=\s{2,}|\s*$)'
)
_RE_TRANS_SIMPLE = re.compile(
    r'(\d{2}/\d{2})\s+(.+?)\s+(-?[\d.]+,\d{2})(?=\s{2,}|\s*$)'
)
_RE_VENC = re.compile(r'Vencimento[\s\S]{0,200}?(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
_RE_PERIODO = re.compile(r'(\d{2})/(\d{2})/(\d{2})\s*a\s*(\d{2})/(\d{2})/(\d{2})')
_RE_CARTAO = re.compile(r'(\d{4})\s+XXXX\s+XXXX\s+(\d{4})')
# Total OFICIAL da fatura (o valor a pagar). Preferimos isto à soma das linhas:
# o banco arredonda e cobra IOF/encargos sem data, então as linhas nunca fecham
# 100% com o total. "Saldo Desta Fatura" é o resumo; "Pagamento Total" é o boleto.
_RE_TOTAL_OFICIAL = (
    re.compile(r'Saldo\s+Desta\s+Fatura\s+R?\$?\s*([\d.]+,\d{2})', re.IGNORECASE),
    re.compile(r'Pagamento\s+Total\s+R?\$?\s*([\d.]+,\d{2})', re.IGNORECASE),
)


def _extrair_total_oficial(text: str):
    """Lê o total a pagar da fatura (não a soma das linhas). None se não achar."""
    for rgx in _RE_TOTAL_OFICIAL:
        m = rgx.search(text)
        if m:
            try:
                return _parse_brl(m.group(1))
            except ValueError:
                continue
    return None


# Linhas a ignorar mesmo se "parecerem" transação
_LINHAS_IGNORAR = (
    "VALOR TOTAL", "Saldo", "Resumo da", "Total de", "Compras parceladas",
    "Histórico de Faturas", "Esta Fatura", "Fatura Aberta",
    "Período das compras", "Pagamento Total", "Pagamento Mínimo",
)


def parse_fatura_santander(pdf_path: str, senha: str = None) -> dict:
    text = _extract_text(pdf_path, senha=senha)

    # Detecta extração vazia/falha — dá mensagem útil em vez de "não achei vencimento"
    if not text or len(text.strip()) < 50:
        raise ValueError(
            "O pdftotext nao conseguiu extrair texto deste PDF "
            f"(extraiu apenas {len(text.strip()) if text else 0} caracteres). "
            "Possiveis causas: PDF e uma imagem escaneada, versao do Poppler "
            "incompativel, ou PDF protegido. Tente reinstalar o Poppler."
        )

    # === Cabeçalho ===
    # O rótulo "Vencimento" e a data ficam em colunas separadas; o helper
    # lida com isso (tenta texto sem -layout, onde rótulo e data ficam juntos).
    venc_date = encontrar_vencimento(pdf_path, senha=senha)
    if not venc_date:
        amostra = text.strip()[:200].replace(chr(10), " | ")
        raise ValueError(
            "Santander: nao encontrei data de vencimento na fatura. "
            f"Inicio do texto extraido: {amostra}"
        )
    mes_ref = f"{venc_date.month:02d}/{venc_date.year}"

    # Período de compras desta fatura. O PDF lista vários (faturas anteriores
    # e atual). O período correto é aquele cujo fim é o mais próximo (mas anterior
    # ou igual) ao vencimento.
    periodos = []
    for d1, m1, y1, d2, m2, y2 in _RE_PERIODO.findall(text):
        try:
            ini = date(2000 + int(y1), int(m1), int(d1))
            fim = date(2000 + int(y2), int(m2), int(d2))
            periodos.append((ini, fim))
        except ValueError:
            continue
    # Filtra os que terminam até o vencimento (faturas até esta)
    candidatos = [p for p in periodos if p[1] <= venc_date]
    if candidatos:
        per_inicio, per_fim = max(candidatos, key=lambda p: p[1])
    else:
        per_fim = venc_date
        per_inicio = date(per_fim.year, max(1, per_fim.month - 1), per_fim.day)

    # Heurística para inferir o ano de cada transação (DD/MM apenas no PDF)
    def infer_year(month: int) -> int:
        # Se o mês é "futuro" relativo ao período, é do ano anterior
        if month > per_fim.month + 1:
            return per_fim.year - 1
        return per_fim.year

    # === Varredura linha a linha mantendo seção e cartão atuais ===
    secao = None  # "credito" | "parcelamento" | "despesa"
    cartao_final4 = None
    transacoes: list[dict] = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        # Mudança de cartão
        cm = _RE_CARTAO.search(line)
        if cm:
            cartao_final4 = cm.group(2)
            continue

        # Mudança de seção
        if "Pagamento e Demais Créditos" in line:
            secao = "credito"
            continue
        if "Parcelamentos" in line and "Detalhamento" not in line:
            secao = "parcelamento"
            continue
        if line.lstrip().startswith("Despesas"):
            secao = "despesa"
            continue

        if not secao:
            continue

        # Pulamos a maior parte da seção "credito" — são pagamentos da fatura anterior.
        # MAS extraímos cashback/bônus que vão virar receita.
        if secao == "credito":
            # Tenta capturar a transação para verificar se é cashback
            m_cb = _RE_TRANS_PARC.search(line) or _RE_TRANS_SIMPLE.search(line)
            if not m_cb:
                continue
            grupos = m_cb.groups()
            data_str_cb = grupos[0]
            desc_cb = grupos[1]
            valor_str_cb = grupos[-1]
            desc_upper_cb = desc_cb.upper()
            # Filtros: pula totais, pagamentos, estornos genéricos
            if any(k in desc_upper_cb for k in (
                "PAGAMENTO", "PGTO", "ESTORNO",
                "TOTAL DE CRÉDITOS", "TOTAL DE PAGAMENTOS",
                "VALOR TOTAL", "SALDO ANTERIOR",
            )):
                continue
            # Detecta cashback / bônus
            eh_cashback = any(k in desc_upper_cb for k in (
                "CASHBACK", "CASH BACK", "BONUS", "BÔNUS",
                "CRÉDITO POR USO", "CREDITO POR USO",
                "PROGRAMA ESFERA", "ESFERA", "PONTOS",
                "CRÉDITO REWARDS", "REWARDS", "RECOMPENSA",
            ))
            if not eh_cashback:
                continue
            try:
                valor_cb = _parse_brl(valor_str_cb.replace("-", "").strip())
            except ValueError:
                continue
            try:
                dia_cb, mes_cb = int(data_str_cb[:2]), int(data_str_cb[3:5])
                ano_cb = infer_year(mes_cb)
                t_date_cb = date(ano_cb, mes_cb, dia_cb)
            except (ValueError, IndexError):
                continue
            transacoes.append({
                "data_compra": t_date_cb,
                "descricao": desc_cb.strip(),
                "valor": valor_cb,
                "parcela": None,
                "secao": "cashback",
                "cartao_final4": cartao_final4,
                "tipo": "Receita",          # marca como receita
            })
            continue

        # Linha de cabeçalho de tabela
        if "Compra" in line and "Data" in line and "Descrição" in line:
            continue

        # Tenta com parcela primeiro, senão sem.
        # IMPORTANTE: tentamos match ANTES de filtros de skip, porque o PDF tem
        # layout em duas colunas e a linha de transação pode conter texto da
        # coluna ao lado (ex.: "Saldo total consolidado de obrigações futuras").
        m = _RE_TRANS_PARC.search(line)
        parcela = None
        if m:
            data_str, desc, parcela, valor_str = m.groups()
        else:
            m = _RE_TRANS_SIMPLE.search(line)
            if not m:
                continue
            data_str, desc, valor_str = m.groups()

        # Linhas que parecem transação mas são metadados (ex.: somatórios, vencimento)
        # Detectamos pela descrição.
        desc_upper = desc.upper()
        if any(k.upper() in desc_upper for k in (
            "VALOR TOTAL", "SALDO ANTERIOR", "TOTAL DESPESAS",
            "TOTAL DE PAGAMENTOS", "TOTAL DE CRÉDITOS", "SALDO DESTA FATURA",
            "ESTA FATURA", "FATURA ABERTA",
        )):
            continue

        try:
            valor = _parse_brl(valor_str)
        except ValueError:
            continue

        # ignora valores negativos restantes (não deveria haver fora de "credito")
        if valor <= 0:
            continue

        dia, mes = int(data_str[:2]), int(data_str[3:5])
        ano = infer_year(mes)
        try:
            t_date = date(ano, mes, dia)
        except ValueError:
            continue

        # Limpa descrição
        desc = re.sub(r"\s+", " ", desc).strip()

        transacoes.append({
            "data_compra": t_date,
            "descricao": desc,
            "valor": valor,
            "parcela": parcela,        # ex: "02/04" ou None
            "secao": secao,            # "parcelamento" ou "despesa"
            "cartao_final4": cartao_final4,
        })

    return {
        "banco": "Santander",
        "vencimento": venc_date,
        "mes_ref": mes_ref,
        "periodo_inicio": per_inicio,
        "periodo_fim": per_fim,
        "transacoes": transacoes,
        "total": _extrair_total_oficial(text),   # total a pagar (oficial), pode ser None
    }


if __name__ == "__main__":
    import sys
    bill = parse_fatura_santander(sys.argv[1])
    print(f"Banco:          {bill['banco']}")
    print(f"Vencimento:     {bill['vencimento']}")
    print(f"Mês Referência: {bill['mes_ref']}")
    print(f"Período:        {bill['periodo_inicio']} a {bill['periodo_fim']}")
    print(f"Transações:     {len(bill['transacoes'])}")
    print()
    print(f"{'Data':<12}{'Descrição':<35}{'Parc':<7}{'Valor':>10}  {'Seção':<13}{'Cartão':<6}")
    print("-" * 90)
    for t in bill["transacoes"]:
        print(f"{t['data_compra'].strftime('%d/%m/%Y'):<12}"
              f"{t['descricao'][:33]:<35}"
              f"{(t['parcela'] or '-'):<7}"
              f"{t['valor']:>10.2f}  "
              f"{t['secao']:<13}"
              f"{t['cartao_final4'] or '-':<6}")
    total = sum(t["valor"] for t in bill["transacoes"])
    print("-" * 90)
    print(f"{'TOTAL':<46}{'':>7}{total:>10.2f}")
