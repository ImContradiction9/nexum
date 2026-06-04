"""
Parser de fatura Bradesco.

Suporta dois layouts:
  - "Amazon Mastercard" / Bradescard: parcela entre parênteses no fim da
    descrição, ex. "LOJA X (04/04)".
  - "VISA Infinite" (formato compacto): colunas Data / Histórico / Cidade /
    Valor, com a parcela NN/NN inline no histórico (às vezes colada ao último
    token da descrição, ex. "EMPORIUM EBENEZER 0201/02").
"""
import re
from datetime import date

from .helpers import executar_pdftotext, encontrar_vencimento


def _parse_brl(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _dia_mes(data_str: str) -> tuple:
    """Extrai (dia, mes) de 'DD/MM' tolerando espaços ao redor da barra."""
    ds = re.sub(r"\s+", "", data_str)
    return int(ds[:2]), int(ds[3:5])


def _mk_date(d, m, a):
    try:
        return date(int(a), int(m), int(d))
    except (ValueError, TypeError):
        return None


# === Vencimento no cabeçalho (ciente de coluna) ============================
def _vencimento_header_bradesco(pdf_path: str, senha: str = None):
    """
    Lê o vencimento do cabeçalho do Bradesco respeitando a coluna "Vencimento".

    Em alguns layouts (VISA Infinite) a data fica "quebrada": o mês/ano aparece
    como '/ MM / AAAA' numa linha e o DIA isolado noutra (na linha do total),
    ambos alinhados sob o rótulo "Vencimento". Aqui localizamos a coluna do
    rótulo e remontamos a data a partir desse recorte vertical — evitando pegar
    por engano a data de "Previsão de fechamento da próxima fatura".
    """
    try:
        texto = executar_pdftotext(pdf_path, senha=senha, layout=True, ultima_pagina=1)
    except Exception:
        return None

    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        vc = linha.find("Vencimento")
        if vc < 0:
            continue
        lo = max(0, vc - 8)
        # Janela curta (i..i+5) para não alcançar a linha da "próxima fatura".
        blob = " ".join(s[lo:] for s in linhas[i:i + 6])

        # 1) data completa contígua (com ou sem espaços)
        m = re.search(r'(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{4})', blob)
        if m:
            dt = _mk_date(*m.groups())
            if dt:
                return dt

        # 2) mês/ano sem o dia ('/ MM / AAAA') + dia isolado em outra linha
        mma = re.search(r'/\s*(\d{2})\s*/\s*(\d{4})', blob)
        if mma:
            resto = blob[:mma.start()] + "  " + blob[mma.end():]
            dm = re.search(r'(?<![\d,.])(\d{2})(?![\d,.])', resto)
            if dm:
                dt = _mk_date(dm.group(1), mma.group(1), mma.group(2))
                if dt:
                    return dt
    return None


# === Vencimento (fallback via código de barras) ============================
def _vencimento_codigo_barras(text):
    """
    Último recurso: faturas digitais do Bradesco trazem o vencimento embutido
    na linha digitável como AAAAMMDD. Pega a data válida mais recente.
    """
    candidatos = []
    for m in re.finditer(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', text):
        try:
            candidatos.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    return max(candidatos) if candidatos else None


# === Formato "Amazon Mastercard" ===========================================
# Primeiro valor monetário após a data (página pode ter 2 colunas).
_RE_TRANS_AMAZON = re.compile(
    r'^\s*(\d{2}\s*/\s*\d{2})\s+(.+?)\s+([\d.]+,\d{2})(\s*-)?(?=\s{2,}|\s*$)'
)
# Parcela entre parênteses no fim da descrição, ex. "(04/04)".
_RE_PARCELA_PAREN = re.compile(r'\s*\((\d{2}/\d{2})\)\s*$')
_RE_CARTAO_AMAZON = re.compile(r'\d{4}\.\d{2}\*+\.\*+\.(\d{4})')


def _parse_amazon(text, venc, infer_year):
    transacoes = []
    cartao_final4 = None
    cm = _RE_CARTAO_AMAZON.search(text)
    if cm:
        cartao_final4 = cm.group(1)

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _RE_TRANS_AMAZON.match(line)
        if not m:
            continue
        data_str, desc, valor_str, sinal_neg = m.groups()
        if sinal_neg or "PAGAMENTO RECEBIDO" in desc.upper():
            continue
        try:
            valor = _parse_brl(valor_str)
        except ValueError:
            continue
        if valor <= 0:
            continue
        dia, mes = _dia_mes(data_str)
        try:
            t_date = date(infer_year(mes), mes, dia)
        except ValueError:
            continue

        parcela = None
        pm = _RE_PARCELA_PAREN.search(desc)
        if pm:
            parcela = pm.group(1)
            desc = desc[:pm.start()].rstrip()

        desc_clean = re.sub(r"\s+", " ", desc).strip()
        desc_clean = re.sub(r"\s+BR[AL]\s*$", "", desc_clean)

        transacoes.append({
            "data_compra": t_date,
            "descricao": desc_clean,
            "valor": valor,
            "parcela": parcela,
            "secao": "parcelamento" if parcela else "despesa",
            "cartao_final4": cartao_final4,
        })
    return transacoes


# === Formato "VISA Infinite" (compacto) ====================================
# Linha: DD/MM <histórico ...>  <valor>  [ruído da coluna ao lado]
# A descrição/parcela/cidade ficam todas no "miolo" entre data e valor.
_RE_TRANS_VISA = re.compile(
    r'^\s*(\d{2}\s*/\s*\d{2})\s+(.+?)\s{2,}([\d.]+,\d{2})(\s*-)?(?:\s{2,}.*)?$'
)
# Parcela: exatamente NN/NN. Pode vir colada ao fim de um token da descrição.
_RE_PARCELA_INLINE = re.compile(r'\d{2}/\d{2}')
_RE_CARTAO_VISA = re.compile(r'\d{4}\s+XXXX\s+XXXX\s+(\d{4})')

# Linhas que casam a regex mas não são compra.
_PALAVRAS_IGNORAR_VISA = (
    "PAGTO", "PAGAMENTO", "TOTAL PARA", "TOTAL DA FATURA",
    "TOTAL PARCELADOS", "SALDO ANTERIOR",
)


def _separar_miolo_visa(miolo: str):
    """
    Separa o miolo (entre data e valor) em (descrição, parcela).
    A cidade — última coluna — é descartada.
    """
    parcelas = list(_RE_PARCELA_INLINE.finditer(miolo))
    if parcelas:
        pm = parcelas[-1]               # parcela é o NN/NN mais à direita
        parcela = pm.group(0)
        desc = miolo[:pm.start()]       # tudo antes da parcela
    else:
        parcela = None
        # Sem parcela: o miolo é "descrição  cidade"; corta no 1º vão largo.
        desc = re.split(r'\s{3,}', miolo, maxsplit=1)[0]

    desc = re.sub(r"\s+", " ", desc).strip()
    return desc, parcela


def _parse_visa(text, venc, infer_year):
    transacoes = []
    cartao_final4 = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        # Troca de cartão (cabeçalho do portador ou "Número do Cartão").
        cm = _RE_CARTAO_VISA.search(line)
        if cm:
            cartao_final4 = cm.group(1)
            # a própria linha pode também conter "Total para..." — só atualiza
            continue

        m = _RE_TRANS_VISA.match(line)
        if not m:
            continue
        data_str, miolo, valor_str, sinal_neg = m.groups()

        # Pagamentos/estornos (valor com "-") e linhas de totais.
        if sinal_neg:
            continue
        if any(p in miolo.upper() for p in _PALAVRAS_IGNORAR_VISA):
            continue

        try:
            valor = _parse_brl(valor_str)
        except ValueError:
            continue
        if valor <= 0:
            continue

        dia, mes = _dia_mes(data_str)
        try:
            t_date = date(infer_year(mes), mes, dia)
        except ValueError:
            continue

        desc, parcela = _separar_miolo_visa(miolo)
        if not desc:
            continue

        transacoes.append({
            "data_compra": t_date,
            "descricao": desc,
            "valor": valor,
            "parcela": parcela,
            "secao": "parcelamento" if parcela else "despesa",
            "cartao_final4": cartao_final4,
        })
    return transacoes


# === Entrada principal =====================================================
def parse_fatura_bradesco(pdf_path: str, senha: str = None) -> dict:
    text = executar_pdftotext(pdf_path, senha=senha)

    if not text or len(text.strip()) < 50:
        raise ValueError(
            "O pdftotext nao conseguiu extrair texto deste PDF "
            f"(extraiu apenas {len(text.strip()) if text else 0} caracteres). "
            "Possiveis causas: PDF e imagem escaneada ou PDF protegido."
        )

    # --- Vencimento: cabeçalho ciente de coluna (lida com data "quebrada"),
    #     depois helper genérico, por fim o código de barras ---
    venc = _vencimento_header_bradesco(pdf_path, senha=senha)
    if not venc:
        venc = encontrar_vencimento(pdf_path, senha=senha)
    if not venc:
        venc = _vencimento_codigo_barras(text)
    if not venc:
        amostra = text.strip()[:300].replace(chr(10), " | ")
        raise ValueError(
            "Bradesco: nao encontrei data de vencimento. "
            f"Inicio do texto: {amostra}"
        )

    mes_ref = f"{venc.month:02d}/{venc.year}"

    # Ano de cada DD/MM: a fatura cobre ~30 dias antes do vencimento.
    # Mês posterior ao do vencimento => transação do ano anterior.
    def infer_year(month: int) -> int:
        return venc.year - 1 if month > venc.month else venc.year

    # --- Detecta o layout e despacha ---
    # O formato "VISA Infinite" mascara o cartão como "NNNN XXXX XXXX NNNN"
    # e traz o cabeçalho "Histórico de Lançamentos"; o formato "Amazon"
    # usa mascaramento com pontos/asteriscos. São mutuamente exclusivos.
    eh_visa_infinite = bool(
        _RE_CARTAO_VISA.search(text)
    ) or "Histórico de Lançamentos" in text
    if eh_visa_infinite:
        transacoes = _parse_visa(text, venc, infer_year)
    else:
        transacoes = _parse_amazon(text, venc, infer_year)

    return {
        "banco": "Bradesco",
        "vencimento": venc,
        "mes_ref": mes_ref,
        "transacoes": transacoes,
    }


if __name__ == "__main__":
    import sys
    bill = parse_fatura_bradesco(sys.argv[1])
    print(f"Banco: {bill['banco']} | Venc: {bill['vencimento']} | Ref: {bill['mes_ref']}")
    print(f"Transações: {len(bill['transacoes'])}")
    print()
    total = 0
    for t in bill["transacoes"]:
        total += t["valor"]
        print(f"  {t['data_compra']}  {t['descricao'][:40]:<42} "
              f"{(t['parcela'] or '-'):<7} {t['valor']:>9.2f}  "
              f"{t['secao']:<13} {t['cartao_final4'] or '-'}")
    print(f"\n  TOTAL: R$ {total:,.2f}")
