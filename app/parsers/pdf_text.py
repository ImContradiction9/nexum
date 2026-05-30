"""
Extração de texto de PDF preservando layout, 100% em Python via pypdfium2.

Substitui a dependência do binário `pdftotext` (Poppler) — que exigia
instalação manual no sistema — por pypdfium2, que vem como wheel do pip
(binário embutido). Assim o app fica autossuficiente (importante pro .exe).

O desafio: os parsers de fatura dependem do modo `pdftotext -layout`, que
preserva o arranjo 2D em colunas inserindo espaços (os regexes detectam
colunas via `\\s{2,}`/`\\s{6,}` e há um reflow que assume alinhamento
monoespaçado). O texto padrão do pypdfium2 insere só um espaço entre
palavras e perde esses vãos. Então aqui reconstruímos o texto a partir das
caixas de cada caractere (`get_charbox`), estimando o "passo" da fonte e
posicionando cada glifo numa coluna absoluta — emulando o `-layout`.
"""
from __future__ import annotations

import statistics
from pathlib import Path

import pypdfium2 as pdfium


class PDFProtegido(Exception):
    """PDF está protegido e nenhuma senha (ou senha errada) foi fornecida."""
    pass


# Mantido por compatibilidade: antes era levantado quando o binário pdftotext
# não estava instalado. Com pypdfium2 (puro pip) isso não acontece mais, mas o
# símbolo segue exportado para não quebrar imports existentes.
class PDFToTextNaoEncontrado(Exception):
    """Mantido por compatibilidade (não é mais levantado com pypdfium2)."""
    pass


def _abrir(pdf_path: str, senha: str | None):
    """Abre o PDF, traduzindo erro de senha em PDFProtegido."""
    try:
        return pdfium.PdfDocument(pdf_path, password=senha)
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg or "0x4" in msg:
            raise PDFProtegido(
                f"PDF protegido por senha: {Path(pdf_path).name}. "
                f"Senha {'incorreta' if senha else 'não fornecida'}."
            )
        raise


def _coletar_runs(textpage):
    """
    Devolve lista de runs (segmentos de texto) como (texto, left, right, top,
    bottom). Cada run vem com o espaçamento INTERNO correto do PDFium (que
    conhece as métricas da fonte) — só precisamos recriar os vãos ENTRE runs.
    """
    n = textpage.count_rects(0, -1)
    runs = []
    for i in range(n):
        try:
            left, bottom, right, top = textpage.get_rect(i)
            t = textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top)
        except Exception:
            continue
        # remove só quebras/whitespace das pontas, preserva espaços internos
        t = t.replace("\r", " ").replace("\n", " ").rstrip()
        if not t.strip():
            continue
        if right < left:
            left, right = right, left
        if top < bottom:
            top, bottom = bottom, top
        runs.append((t, left, right, top, bottom))
    return runs


def _passo_caractere(runs) -> float:
    """
    Estima a largura média de um caractere (passo/pitch) pela mediana de
    (largura do run / nº de caracteres) entre os runs da página.
    """
    larguras = []
    for t, left, right, _top, _bottom in runs:
        n = len(t)
        if n > 0 and right > left:
            larguras.append((right - left) / n)
    if not larguras:
        return 5.0
    cw = statistics.median(larguras)
    return cw if cw > 0.5 else 5.0


def _agrupar_linhas(runs):
    """Agrupa runs em linhas pela posição vertical (centro do run)."""
    if not runs:
        return []
    alturas = [r[3] - r[4] for r in runs if r[3] - r[4] > 0]
    h_med = statistics.median(alturas) if alturas else 8.0
    tol = h_med * 0.6  # tolerância vertical pra considerar "mesma linha"

    # Ordena de cima pra baixo (top maior primeiro), desempate pela esquerda.
    ordenados = sorted(runs, key=lambda r: (-r[3], r[1]))
    linhas = []
    atual = [ordenados[0]]
    ref = (ordenados[0][3] + ordenados[0][4]) / 2  # centro vertical
    for r in ordenados[1:]:
        yc = (r[3] + r[4]) / 2
        if abs(yc - ref) <= tol:
            atual.append(r)
            ref = (ref * (len(atual) - 1) + yc) / len(atual)
        else:
            linhas.append(atual)
            atual = [r]
            ref = yc
    linhas.append(atual)
    return linhas


def _montar_texto(runs, com_layout: bool) -> str:
    """Monta o texto de uma página a partir dos runs."""
    linhas = _agrupar_linhas(runs)
    if not linhas:
        return ""

    if not com_layout:
        # Modo simples: junta os runs de cada linha com 1 espaço.
        partes = []
        for linha in linhas:
            ordenados = sorted(linha, key=lambda r: r[1])
            partes.append(" ".join(r[0].strip() for r in ordenados).rstrip())
        return "\n".join(partes)

    # Modo layout: posiciona cada run numa coluna absoluta (emula -layout).
    # O texto interno do run já tem o espaçamento certo; só preenchemos os
    # vãos entre runs com espaços proporcionais à distância.
    cw = _passo_caractere(runs)
    x0 = min(r[1] for r in runs)

    saida = []
    for linha in linhas:
        ordenados = sorted(linha, key=lambda r: r[1])
        buf: list[str] = []
        for t, left, _right, _top, _bottom in ordenados:
            col = round((left - x0) / cw)
            if col > len(buf):
                buf.extend(" " * (col - len(buf)))
            elif buf and col <= len(buf):
                # runs colados/sobrepostos: garante ao menos 1 espaço de separação
                buf.append(" ")
            buf.extend(list(t))
        saida.append("".join(buf).rstrip())
    return "\n".join(saida)


def extrair_texto(
    pdf_path: str,
    senha: str | None = None,
    layout: bool = True,
    primeira_pagina: int | None = None,
    ultima_pagina: int | None = None,
) -> str:
    """
    Extrai texto de um PDF preservando layout (emula `pdftotext -layout`).

    Args:
        pdf_path: caminho do PDF.
        senha: senha do usuário (se criptografado).
        layout: True preserva colunas (vãos com múltiplos espaços); False usa
                espaçamento simples (1 espaço entre palavras).
        primeira_pagina / ultima_pagina: faixa 1-based, inclusiva (como pdftotext
                -f/-l). None = do começo / até o fim.

    Páginas são separadas por form feed (\\f), igual ao pdftotext.

    Levanta PDFProtegido se o PDF for criptografado e a senha estiver ausente/errada.
    """
    pdf = _abrir(pdf_path, senha)
    try:
        n_paginas = len(pdf)
        ini = (primeira_pagina - 1) if primeira_pagina else 0
        fim = ultima_pagina if ultima_pagina else n_paginas
        ini = max(0, ini)
        fim = min(n_paginas, fim)

        paginas_txt = []
        for idx in range(ini, fim):
            page = pdf[idx]
            try:
                textpage = page.get_textpage()
                try:
                    runs = _coletar_runs(textpage)
                    paginas_txt.append(_montar_texto(runs, com_layout=layout))
                finally:
                    textpage.close()
            finally:
                page.close()
        return "\f".join(paginas_txt)
    finally:
        pdf.close()
