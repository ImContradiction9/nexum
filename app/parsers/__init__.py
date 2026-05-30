"""Detecta o banco a partir do PDF e chama o parser correto."""
from pathlib import Path

from .helpers import executar_pdftotext, PDFProtegido, PDFToTextNaoEncontrado
from .santander import parse_fatura_santander
from .bradesco import parse_fatura_bradesco
from .nubank import parse_fatura_nubank
from .mercadopago import parse_fatura_mercadopago


def _ler_inicio_pdf(pdf_path: str, senha: str = None, primeiras_paginas: int = 2) -> str:
    """Lê só as primeiras páginas — suficiente para detectar o banco."""
    return executar_pdftotext(
        pdf_path, senha=senha, ultima_pagina=primeiras_paginas
    ).lower()


def detectar_banco(pdf_path: str, senha: str = None) -> str:
    """
    Retorna "Nubank" | "Bradesco" | "Santander" | "Mercado Pago", ou levanta ValueError.
    Pode levantar PDFProtegido se o PDF estiver criptografado e a senha
    estiver errada/ausente.
    """
    txt = _ler_inicio_pdf(pdf_path, senha=senha)

    # Mercado Pago: tem "mercado pago" e "fatura"/"vencimento" na primeira página
    if "mercado pago" in txt or "mercadopago" in txt:
        return "Mercado Pago"
    # Nubank: tem "Nubank" no rodapé, "fatura de" no título
    if "nubank" in txt or "olá," in txt and "fatura de" in txt:
        return "Nubank"
    # Bradesco/Bradescard
    if "bradescard" in txt or ("bradesco" in txt and "fatura mensal" in txt):
        return "Bradesco"
    # Santander
    if "santander" in txt:
        return "Santander"

    raise ValueError(f"Não consegui detectar o banco do PDF: {Path(pdf_path).name}")


def parse_fatura(pdf_path: str, senha: str = None) -> dict:
    """
    Detecta automaticamente e retorna estrutura uniforme.

    Pode levantar:
      - PDFProtegido: PDF criptografado e senha ausente/errada
      - PDFToTextNaoEncontrado: poppler não instalado
      - ValueError: banco não detectado ou erro de parsing
    """
    banco = detectar_banco(pdf_path, senha=senha)
    if banco == "Nubank":
        return parse_fatura_nubank(pdf_path, senha=senha)
    if banco == "Bradesco":
        return parse_fatura_bradesco(pdf_path, senha=senha)
    if banco == "Santander":
        return parse_fatura_santander(pdf_path, senha=senha)
    if banco == "Mercado Pago":
        return parse_fatura_mercadopago(pdf_path, senha=senha)
    raise ValueError(f"Banco não suportado: {banco}")

