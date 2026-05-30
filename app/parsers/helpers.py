"""
Helper centralizado de extração de texto de PDF (com suporte a senha).

ANTES: dependia do binário `pdftotext` (Poppler), instalado no sistema.
AGORA: usa o extrator em `pdf_text.py` (pypdfium2, puro pip), para o app ser
autossuficiente — sem instalação manual de Poppler (essencial pro .exe).

A função `executar_pdftotext` mantém o nome/assinatura por compatibilidade
com os parsers; internamente apenas delega ao extrator pypdfium2.
"""
import os
from pathlib import Path

from .pdf_text import (
    extrair_texto as _extrair_texto,
    PDFProtegido,
    PDFToTextNaoEncontrado,
)

# Permite forçar o uso do binário pdftotext (Poppler), caso ainda esteja
# instalado, definindo NEXUM_USAR_POPPLER=1 — útil só para comparação/diagnóstico.
_USAR_POPPLER = os.environ.get("NEXUM_USAR_POPPLER", "") == "1"


def _executar_poppler(pdf_path, senha, layout, primeira_pagina, ultima_pagina):
    """Caminho de diagnóstico: usa o binário pdftotext se NEXUM_USAR_POPPLER=1."""
    import shutil
    import subprocess

    exe = shutil.which("pdftotext")
    if not exe:
        raise PDFToTextNaoEncontrado("pdftotext não encontrado no PATH.")
    cmd = [exe]
    if layout:
        cmd.append("-layout")
    if senha:
        cmd.extend(["-upw", senha])
    if primeira_pagina is not None:
        cmd.extend(["-f", str(primeira_pagina)])
    if ultima_pagina is not None:
        cmd.extend(["-l", str(ultima_pagina)])
    cmd.extend([pdf_path, "-"])
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        if "password" in stderr or "encrypted" in stderr:
            raise PDFProtegido(
                f"PDF protegido por senha: {Path(pdf_path).name}. "
                f"Senha {'incorreta' if senha else 'não fornecida'}."
            )
        raise RuntimeError(f"pdftotext falhou (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def executar_pdftotext(
    pdf_path: str,
    senha: str = None,
    layout: bool = True,
    primeira_pagina: int = None,
    ultima_pagina: int = None,
) -> str:
    """
    Extrai texto do PDF preservando layout (emula `pdftotext -layout`).
    Mantém o nome por compatibilidade — internamente usa pypdfium2.

    Levanta PDFProtegido se o PDF for criptografado e a senha estiver errada/ausente.
    """
    if _USAR_POPPLER:
        return _executar_poppler(pdf_path, senha, layout, primeira_pagina, ultima_pagina)
    return _extrair_texto(
        pdf_path,
        senha=senha,
        layout=layout,
        primeira_pagina=primeira_pagina,
        ultima_pagina=ultima_pagina,
    )


# ---------------------------------------------------------------------------
# Localização robusta da data de vencimento
# ---------------------------------------------------------------------------
import re as _re
from datetime import date as _date

_RE_DATA_COMPLETA = _re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')


def _str_para_data(d, m, a):
    try:
        return _date(int(a), int(m), int(d))
    except ValueError:
        return None


def _vencimento_no_texto(texto: str):
    """
    Procura a data de vencimento num bloco de texto já extraído.

    Lida com dois layouts comuns:
      - rótulo e data na mesma região, separados por espaços/quebras;
      - rótulo numa linha e a data alguns renglones abaixo (cabeçalho em colunas).
    """
    if not texto:
        return None

    # 1. Rótulo "Vencimento" seguido da data dentro de uma janela ampla.
    #    Janela de 400 chars cobre o padding do modo -layout em colunas.
    m = _re.search(
        r'(?:vencimento|vcto|venc\.?|pagar\s+at[eé])[\s\S]{0,400}?'
        r'(\d{2})/(\d{2})/(\d{4})',
        texto, _re.IGNORECASE,
    )
    if m:
        dt = _str_para_data(*m.groups())
        if dt:
            return dt

    # 2. Layout em colunas: o rótulo está numa linha e a data numa linha
    #    seguinte, mais ou menos na mesma coluna. Varremos as próximas linhas.
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        rotulo = _re.search(r'vencimento', linha, _re.IGNORECASE)
        if not rotulo:
            continue
        for j in range(i, min(i + 8, len(linhas))):
            for dm in _RE_DATA_COMPLETA.finditer(linhas[j]):
                # Na própria linha do rótulo, só aceita data depois dele.
                if j == i and dm.start() < rotulo.end():
                    continue
                dt = _str_para_data(*dm.groups())
                if dt:
                    return dt
    return None


def encontrar_vencimento(pdf_path: str, senha: str = None):
    """
    Devolve a data de vencimento (datetime.date) de uma fatura, ou None.

    Estratégia robusta a variações de layout:
      1. Texto SEM -layout: nesse modo o pdftotext reordena o cabeçalho em
         colunas, deixando o rótulo "Vencimento" colado à data — é o mais
         confiável.
      2. Texto COM -layout, como reforço.
    Só lê a primeira página (vencimento sempre fica no cabeçalho).
    """
    for usar_layout in (False, True):
        try:
            txt = executar_pdftotext(
                pdf_path, senha=senha, layout=usar_layout, ultima_pagina=1
            )
        except (PDFProtegido, PDFToTextNaoEncontrado):
            raise
        except Exception:
            continue
        dt = _vencimento_no_texto(txt)
        if dt:
            return dt
    return None


# ---------------------------------------------------------------------------
# Reflow de páginas com layout em DUAS COLUNAS
# ---------------------------------------------------------------------------
import statistics as _stats

# Início de transação: data DD/MM seguida do começo de uma descrição
# (um caractere que não seja espaço nem dígito — evita confundir com a
# parcela NN/NN, que é seguida de espaços e depois o valor numérico).
_RE_INICIO_TRANS = _re.compile(r'\d{2}/\d{2}\s+[^\s\d]')


def _reflow_pagina(pagina: str) -> str:
    """
    Se a página tiver layout de duas colunas (várias linhas com duas
    transações lado a lado), corta cada linha na coluna divisória e
    devolve a coluna esquerda inteira seguida da coluna direita.
    Caso contrário, devolve a página inalterada.
    """
    linhas = pagina.split("\n")

    # Detecta: quantas linhas têm 2+ transações?
    linhas_2col = [l for l in linhas if len(_RE_INICIO_TRANS.findall(l)) >= 2]
    if len(linhas_2col) < 6:
        return pagina  # página de coluna única

    # Coluna de corte = fim do maior espaçamento que antecede a 2ª transação.
    cortes = []
    for l in linhas_2col:
        ms = list(_RE_INICIO_TRANS.finditer(l))
        gaps = list(_re.finditer(r'\s{6,}', l[:ms[1].start()]))
        if gaps:
            cortes.append(gaps[-1].end())
    if not cortes:
        return pagina
    corte = _stats.median_low(cortes)

    esquerda = [l[:corte].rstrip() for l in linhas]
    direita = [l[corte:].rstrip() for l in linhas]
    esquerda = [l for l in esquerda if l.strip()]
    direita = [l for l in direita if l.strip()]
    return "\n".join(esquerda + direita)


def reflow_colunas(texto: str) -> str:
    """
    Reordena, página a página, qualquer layout de duas colunas para coluna
    única. Páginas de coluna única passam intactas. Mantém os separadores
    de página (\\f).
    """
    return "\f".join(_reflow_pagina(p) for p in texto.split("\f"))
