"""
Parser OFX universal.

OFX (Open Financial Exchange) é um padrão usado por todos os bancos brasileiros
para exportar extratos. A estrutura é XML/SGML com transações dentro de <STMTTRN>.

Cada transação tem:
  - <TRNTYPE>     — DEBIT, CREDIT, FEE, INT, XFER, PAYMENT, etc.
  - <DTPOSTED>    — data no formato YYYYMMDDHHMMSS (com zona opcional [-3:BRT])
  - <TRNAMT>      — valor com sinal (+ entrada, - saída)
  - <FITID>       — ID único do banco (usado pra dedup confiável)
  - <MEMO>        — descrição
  - <CHECKNUM>    — opcional, número do cheque/comprovante

Quirks por banco:
  - Nubank: tags fechadas certinho, encoding UTF-8, FITID UUID
  - Bradesco: tags ABERTAS (sem </TAG>), encoding latin1/cp1252,
              FITID com formato proprietário longo
  - Padrão OFX 1.x permite ambos (SGML).

Esse parser trata os dois usando regex tolerante (não tenta validar XML).
"""
import re
import codecs
from datetime import date, datetime
from pathlib import Path


# === Detecção de encoding ===
def _ler_ofx(pdf_path: str) -> str:
    """
    OFX 1.x tem header em ASCII. Encoding pode ser UTF-8 ou cp1252.
    Lê o header pra decidir.
    """
    with open(pdf_path, "rb") as f:
        raw = f.read()

    # Header é ASCII. Detecta encoding nas primeiras linhas.
    head = raw[:500].decode("ascii", errors="ignore")
    if "ENCODING:UTF-8" in head or "ENCODING:UNICODE" in head:
        return raw.decode("utf-8", errors="replace")
    # cp1252 (latin1 estendido) é o padrão Windows brasileiro
    if "CHARSET:1252" in head or "ENCODING:USASCII" in head:
        return raw.decode("cp1252", errors="replace")
    # Fallback: tenta UTF-8 primeiro, cp1252 depois
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


# === Mapa: detecta o banco a partir do FID/ORG ===
# Códigos COMPE oficiais
BANCOS_FID = {
    "260":  "Nubank",         # NU PAGAMENTOS
    "0260": "Nubank",
    "237":  "Bradesco",
    "0237": "Bradesco",
    "33":   "Santander",
    "0033": "Santander",
    "341":  "Itaú",
    "0341": "Itaú",
    "104":  "Caixa",
    "0104": "Caixa",
    "1":    "Banco do Brasil",
    "001":  "Banco do Brasil",
    "0001": "Banco do Brasil",
    "77":   "Inter",
    "0077": "Inter",
    "323":  "Mercado Pago",
    "0323": "Mercado Pago",
}

# Mapa por nome da organização (fallback se BANKID/FID não bater)
BANCOS_ORG = [
    ("nu pagamentos",   "Nubank"),
    ("nubank",          "Nubank"),
    ("bradesco",        "Bradesco"),
    ("santander",       "Santander"),
    ("itau",            "Itaú"),
    ("itaú",            "Itaú"),
    ("caixa",           "Caixa"),
    ("banco do brasil", "Banco do Brasil"),
    ("inter",           "Inter"),
    ("mercado pago",    "Mercado Pago"),
]


def _detectar_banco_ofx(text: str) -> str:
    """Detecta o banco pelo conteúdo do OFX. Retorna nome canônico."""
    # Tenta BANKID
    m = re.search(r'<BANKID>\s*(\S+?)(?:</BANKID>|\s|$)', text, re.IGNORECASE)
    if m:
        bankid = m.group(1).strip().lstrip("0") or "0"
        if bankid in BANCOS_FID:
            return BANCOS_FID[bankid]
        # Tenta com zeros à esquerda
        for k, v in BANCOS_FID.items():
            if k.lstrip("0") == bankid:
                return v

    # Tenta FID/ORG
    m_org = re.search(r'<ORG>\s*([^<\n\r]+?)(?:</ORG>|\n|\r)', text, re.IGNORECASE)
    if m_org:
        org_lower = m_org.group(1).strip().lower()
        for substring, nome in BANCOS_ORG:
            if substring in org_lower:
                return nome

    raise ValueError("Não consegui identificar o banco pelo conteúdo do OFX.")


# === Parsing de transações ===

# Regex tolerante a tags fechadas ou abertas:
#   <TRNTYPE>DEBIT</TRNTYPE>      ← Nubank (fechada)
#   <TRNTYPE>DEBIT\n              ← Bradesco (aberta, fim de linha)
def _extrair_campo(bloco: str, tag: str) -> str:
    """
    Extrai conteúdo de uma tag OFX. Aceita:
      <TAG>valor</TAG>  ou  <TAG>valor\n  ou  <TAG>valor<NEXT_TAG>
    """
    pattern = rf'<{tag}>\s*(.+?)\s*(?:</{tag}>|<|\n|\r|$)'
    m = re.search(pattern, bloco, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def _parse_data_ofx(s: str) -> date:
    """
    Formato OFX: YYYYMMDDHHMMSS[opcional zona]
    Exemplos:
      20260105000000[-3:BRT]
      20260420000000[-03:EST]
      20260105
    """
    if not s:
        return None
    # Remove zona horária se houver
    s_clean = re.sub(r'\[.*?\]', '', s).strip()
    # Pega só os primeiros 8 chars (YYYYMMDD)
    if len(s_clean) >= 8:
        try:
            return date(int(s_clean[:4]), int(s_clean[4:6]), int(s_clean[6:8]))
        except ValueError:
            return None
    return None


# Mapeamento TRNTYPE → tipo do app
# A regra de ouro: o **sinal do TRNAMT** é a verdade.
# Valor positivo = entrada (Receita)
# Valor negativo = saída (Despesa)
# TRNTYPE só ajuda a refinar a forma_pagamento.
TRNTYPE_FORMA = {
    "CREDIT":     "Crédito em conta",
    "DEBIT":      "Débito em conta",
    "INT":        "Rendimento",         # juros recebidos
    "DIV":        "Rendimento",         # dividendos
    "FEE":        "Tarifa",
    "SRVCHG":     "Tarifa",
    "DEP":        "Depósito",
    "ATM":        "Saque",
    "POS":        "Débito",
    "XFER":       "Transferência",
    "CHECK":      "Cheque",
    "PAYMENT":    "Pagamento",
    "CASH":       "Dinheiro",
    "DIRECTDEP":  "Depósito",
    "DIRECTDEBIT":"Débito automático",
    "REPEATPMT":  "Pagamento recorrente",
    "OTHER":      "Outros",
}


def _classificar_forma_pagamento(trntype: str, memo: str, valor: float) -> str:
    """
    Refina a forma de pagamento usando memo + tipo OFX + sinal do valor.
    """
    memo_low = (memo or "").lower()

    # Padrões que dão informação mais precisa que TRNTYPE
    if "pix" in memo_low:
        return "Pix recebido" if valor > 0 else "Pix enviado"
    if "boleto" in memo_low:
        return "Boleto"
    if "fatura" in memo_low and "pagamento" in memo_low:
        return "Pagamento de fatura"
    if "ted" in memo_low:
        return "TED"
    if "doc" in memo_low and not "documento" in memo_low:
        return "DOC"
    if "rendimento" in memo_low or "juros" in memo_low:
        return "Rendimento"
    if "tarifa" in memo_low or "anuidade" in memo_low or "iof" in memo_low:
        return "Tarifa"
    if "saque" in memo_low:
        return "Saque"
    if "salario" in memo_low or "salário" in memo_low or "folha" in memo_low:
        return "Salário"

    # Fallback no TRNTYPE
    return TRNTYPE_FORMA.get(trntype.upper(), "Outros")


def parse_extrato_ofx(pdf_path: str) -> dict:
    """
    Parseia OFX de qualquer banco. Retorna estrutura:
      {
        "banco": str,
        "tipo_arquivo": "extrato",
        "conta_id_externo": str,        # ACCTID do OFX
        "periodo_inicio": date,
        "periodo_fim": date,
        "transacoes": [
          {
            "data": date,
            "descricao": str,
            "valor": float,             # SEMPRE positivo
            "tipo": "Receita" | "Despesa",
            "forma_pagamento": str,
            "fitid": str,               # ID único do banco — usar pra dedup
          }, ...
        ]
      }
    """
    text = _ler_ofx(pdf_path)
    banco = _detectar_banco_ofx(text)

    # Conta
    acctid = ""
    m_acct = re.search(r'<ACCTID>\s*(.+?)(?:</ACCTID>|\n|\r)', text, re.IGNORECASE)
    if m_acct:
        acctid = m_acct.group(1).strip()

    # Período
    dt_start = None
    dt_end = None
    m_start = re.search(r'<DTSTART>\s*(.+?)(?:</DTSTART>|\n|\r)', text, re.IGNORECASE)
    m_end = re.search(r'<DTEND>\s*(.+?)(?:</DTEND>|\n|\r)', text, re.IGNORECASE)
    if m_start:
        dt_start = _parse_data_ofx(m_start.group(1))
    if m_end:
        dt_end = _parse_data_ofx(m_end.group(1))

    # === Extrai todas as <STMTTRN> ===
    transacoes = []
    # Regex que pega bloco entre <STMTTRN> e </STMTTRN> OU próximo <STMTTRN> OU </BANKTRANLIST>
    blocos = re.findall(
        r'<STMTTRN>(.+?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))',
        text, re.DOTALL | re.IGNORECASE,
    )

    for b in blocos:
        trntype = _extrair_campo(b, "TRNTYPE")
        dtposted_raw = _extrair_campo(b, "DTPOSTED")
        trnamt_raw = _extrair_campo(b, "TRNAMT")
        fitid = _extrair_campo(b, "FITID")
        memo = _extrair_campo(b, "MEMO")
        # Limpa memo: remove quebras de linha múltiplas
        memo = re.sub(r'\s+', ' ', memo).strip()

        if not trnamt_raw or not dtposted_raw:
            continue

        try:
            valor = float(trnamt_raw)
        except ValueError:
            continue

        data_t = _parse_data_ofx(dtposted_raw)
        if not data_t:
            continue

        tipo = "Receita" if valor > 0 else "Despesa"
        forma = _classificar_forma_pagamento(trntype, memo, valor)

        transacoes.append({
            "data": data_t,
            "descricao": memo or trntype or "Transação",
            "valor": abs(valor),  # sempre positivo
            "tipo": tipo,
            "forma_pagamento": forma,
            "fitid": fitid,
            "trntype_original": trntype,
        })

    # === Saldo final (LEDGERBAL/BALAMT) ===
    # OFX: <LEDGERBAL><BALAMT>1234.56</BALAMT><DTASOF>...</DTASOF></LEDGERBAL>
    saldo_final = None
    m_bal = re.search(
        r'<LEDGERBAL>.*?<BALAMT>\s*(-?[\d.,]+)',
        text, re.IGNORECASE | re.DOTALL,
    )
    if m_bal:
        try:
            # OFX usa ponto decimal padrão
            saldo_final = float(m_bal.group(1).replace(",", "."))
        except ValueError:
            saldo_final = None

    # Saldo inicial = saldo final - soma das transações líquidas
    # (cada TRNAMT já tem sinal correto: + entrada, - saída)
    saldo_inicial = None
    if saldo_final is not None:
        soma_liquida = sum(
            (t["valor"] if t["tipo"] == "Receita" else -t["valor"])
            for t in transacoes
        )
        saldo_inicial = saldo_final - soma_liquida

    return {
        "banco": banco,
        "tipo_arquivo": "extrato",
        "conta_id_externo": acctid,
        "periodo_inicio": dt_start,
        "periodo_fim": dt_end,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final,
        "transacoes": transacoes,
    }
