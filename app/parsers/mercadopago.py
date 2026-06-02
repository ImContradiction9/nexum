"""Parser de fatura Mercado Pago (Cartão de Crédito Visa)."""
import re
from datetime import date

from .helpers import executar_pdftotext


# === Regex ===

# Vencimento aparece em duas formas:
#   "Vence em\n... 14/04/2026" (página 1, layout em colunas — pode quebrar por múltiplos espaços)
#   "Vencimento: 14/04/2026" (cabeçalho das páginas seguintes — formato confiável)
_RE_VENC = re.compile(r'Vencimento:\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
# Fallback: pega qualquer DD/MM/YYYY próximo de "Vence em"
_RE_VENC_FALLBACK = re.compile(r'Vence em[\s\S]{0,300}?(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
# Período do consumo: "Consumos de 10/03 a 09/04"
_RE_PERIODO = re.compile(r'Consumos de\s*(\d{2}/\d{2})\s*a\s*(\d{2}/\d{2})', re.IGNORECASE)
# Cartão final: "Cartão Visa [************2298]" ou variações OCR ("Cartado", asteriscos virando aspas, etc)
_RE_CARTAO = re.compile(r'Cart[ãa]?[ado]+\s+\w+\s*\[[\*\"\']+(\d{4})\]')
# Total a pagar: "Total a pagar R$ 143,73" ou "R$ 143,73"
_RE_TOTAL = re.compile(r'Total a pagar\s*\n?\s*R\$\s*([\d.]+,\d{2})', re.IGNORECASE)

# Linha de transação:
#   "06/06     MERCADOLIVRE*JAPANGAMESCW           Parcela 11 de 18       R$ 143,73"
#   "10/03     Posto Shell Centro                                          R$ 50,00"
# Captura: data, descrição, parcela (opcional), valor (opcional sinal -)
_RE_TRANS_PARC = re.compile(
    r'^\s*(\d{2}/\d{2})\s+(.+?)\s+Parcela\s+(\d+)\s+de\s+(\d+)\s+R\$\s*([\d.]+,\d{2})\s*(-)?\s*$',
    re.IGNORECASE,
)
_RE_TRANS_SIMPLES = re.compile(
    r'^\s*(\d{2}/\d{2})\s+(.+?)\s+R\$\s*([\d.]+,\d{2})\s*(-)?\s*$'
)

# Linhas de cabeçalho/rodapé que devem ser ignoradas
_FRASES_IGNORAR = (
    "Data      Movimentações",
    "Data Movimentações",
    "Valor em R$",
    "Total",
    "Pagamento da fatura",
    "Detalhes de consumo",
    "Movimentações na fatura",
    "Cartão Visa",
)


def _parse_brl(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _infer_year_from_venc(mes_compra: int, venc: date) -> int:
    """
    Dado o mês da compra (sem ano) e a data de vencimento, infere o ano.
    Compra normalmente é 1-2 meses antes do vencimento. Mas parcelas podem
    ser bem antigas. Se mês > mês do vencimento → ano anterior.
    """
    venc_mes = venc.month
    venc_ano = venc.year
    # Caso normal: compra no mesmo mês ou 1-2 meses antes
    if mes_compra <= venc_mes:
        return venc_ano
    # Caso parcela antiga: mês maior que vencimento → ano anterior
    return venc_ano - 1


def parse_fatura_mercadopago(pdf_path: str, senha: str = None) -> dict:
    text = executar_pdftotext(pdf_path, senha=senha)
    return _extrair(pdf_path, text)


def _extrair(pdf_path: str, text: str) -> dict:
    """Extração principal a partir do texto extraído do PDF."""
    # === Cabeçalho ===
    venc_m = _RE_VENC.search(text) or _RE_VENC_FALLBACK.search(text)
    if not venc_m:
        raise ValueError("Não consegui achar a data de vencimento na fatura Mercado Pago.")
    venc_str = venc_m.group(1)
    dia, mes, ano = int(venc_str[:2]), int(venc_str[3:5]), int(venc_str[6:10])
    vencimento = date(ano, mes, dia)
    mes_ref = f"{mes:02d}/{ano}"

    # Período do consumo
    periodo_inicio = None
    periodo_fim = None
    p_m = _RE_PERIODO.search(text)
    if p_m:
        ini_dia, ini_mes = int(p_m.group(1)[:2]), int(p_m.group(1)[3:5])
        fim_dia, fim_mes = int(p_m.group(2)[:2]), int(p_m.group(2)[3:5])
        periodo_inicio = date(_infer_year_from_venc(ini_mes, vencimento), ini_mes, ini_dia)
        periodo_fim = date(_infer_year_from_venc(fim_mes, vencimento), fim_mes, fim_dia)

    # Cartão
    cartao_m = _RE_CARTAO.search(text)
    cartao_final4 = cartao_m.group(1) if cartao_m else None

    # === Transações ===
    transacoes = []
    em_secao_consumo = False  # só extrai depois de "Detalhes de consumo"
    pulou_movimentacoes_fatura = False

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        # Marca início da seção de consumo
        if "Detalhes de consumo" in line:
            em_secao_consumo = True
            continue
        if not em_secao_consumo:
            continue

        # A primeira tabela é "Movimentações na fatura" — pagamento da fatura anterior.
        # Ignora ela inteira até achar "Cartão Visa" / "Cartão MasterCard" / etc.
        if not pulou_movimentacoes_fatura:
            if _RE_CARTAO.search(line):
                pulou_movimentacoes_fatura = True
            # também detecta se aparece outro cabeçalho de Cartão sem o final
            elif re.search(r"Cart[ãa]o\s+\w+", line):
                pulou_movimentacoes_fatura = True
            continue

        # Pula cabeçalhos/rodapés
        if any(f.lower() in line.lower().strip() for f in _FRASES_IGNORAR):
            continue
        if line.strip().startswith("Total ") or line.strip() == "Total":
            continue

        # Tenta com parcela primeiro
        m = _RE_TRANS_PARC.match(line)
        parcela = None
        if m:
            data_str, desc, p_atual, p_total, valor_str, neg = m.groups()
            parcela = f"{int(p_atual):02d}/{int(p_total):02d}"
        else:
            m = _RE_TRANS_SIMPLES.match(line)
            if not m:
                continue
            data_str, desc, valor_str, neg = m.groups()

        try:
            valor = _parse_brl(valor_str)
        except ValueError:
            continue

        # Se vier com sinal de negativo, marca como receita (estorno/cashback)
        if neg:
            tipo = "Receita"
        else:
            tipo = "Despesa"

        c_dia, c_mes = int(data_str[:2]), int(data_str[3:5])
        try:
            c_ano = _infer_year_from_venc(c_mes, vencimento)
            t_date = date(c_ano, c_mes, c_dia)
        except (ValueError, IndexError):
            continue

        transacoes.append({
            "data_compra": t_date,
            "descricao": desc.strip(),
            "valor": valor,
            "parcela": parcela,
            "secao": "despesa",
            "cartao_final4": cartao_final4,
            "tipo": tipo,
        })

    return {
        "banco": "Mercado Pago",
        "vencimento": vencimento,
        "mes_ref": mes_ref,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "transacoes": transacoes,
    }
