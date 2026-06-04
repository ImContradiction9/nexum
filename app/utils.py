"""Utilidades compartilhadas: normalização, dedup, hashing."""
import hashlib
import re
import unicodedata
from datetime import date


def normalizar_descricao(desc: str) -> str:
    """
    Normaliza descrição para matching de memória/regras.
    Remove acentos, números variáveis, *, espaços extras. Tudo lowercase.

    Exemplos:
      "UBER *TRIP-A1B2C3"             -> "uber trip"
      "IFOOD * RESTAURANTE BOM SABOR" -> "ifood restaurante bom sabor"
      "AMAZON 1234 *MKT"              -> "amazon mkt"
    """
    if not desc:
        return ""
    s = desc.lower().strip()
    # remove acentos
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    # remove asterisco e caracteres especiais (mantém letras/números/espaço)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # remove tokens que parecem códigos (mistura letra+número, 4+ chars)
    s = re.sub(r"\b[a-z0-9]{4,}\b", lambda m: m.group(0) if m.group(0).isalpha() else " ", s)
    # remove números puros longos (códigos de transação)
    s = re.sub(r"\b\d{3,}\b", " ", s)
    # colapsa espaços
    s = re.sub(r"\s+", " ", s).strip()
    return s


def hash_dedup(banco: str, data_compra: date, valor: float, descricao: str,
               parcela: str = None, cartao: str = None) -> str:
    """
    Hash determinístico para detectar duplicatas dentro do mesmo banco/data/valor.
    Não usa descrição literal — usa primeiros 30 chars normalizados.

    `parcela` (ex: "2/12") é incluído para distinguir parcelas distintas da mesma
    compra (sem ele, todas as 12 parcelas geram o mesmo hash e só a 1ª entra).

    `cartao` (final do cartão) distingue a MESMA compra feita em cartões
    diferentes da mesma fatura (titular + adicionais). Sem ele, ex.: dois
    "SEGURO 9,99" (um por cartão) colidiam e o 2º caía como falsa duplicata,
    sumindo dos totais. O segmento só entra quando há cartão, então hashes
    antigos (OFX / sem cartão) ficam idênticos — preserva o dedup contra dados
    já gravados.
    """
    desc_norm = normalizar_descricao(descricao)[:30]
    parcela_str = parcela or ""
    raw = f"{banco}|{data_compra.isoformat()}|{valor:.2f}|{desc_norm}|{parcela_str}"
    if cartao:
        raw += f"|{cartao}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ordena_pt(itens, get_key=lambda x: x.nome):
    """Ordena lista em ordem alfabética portuguesa: ignora maiúsculas e acentos.
    'água' vai pra perto de 'agua' (depois de 'A...' e antes de 'B...'),
    não pro fim da lista como faria a ordenação ASCII default."""
    def chave(x):
        s = (get_key(x) or "").lower()
        # NFD separa cada letra acentuada em letra-base + combining mark
        # 'á' → 'a' + '́' — depois removemos os combining marks (Mn)
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return sorted(itens, key=chave)


def hash_pdf(filepath: str) -> str:
    """SHA256 do conteúdo do PDF — para detectar reimport do mesmo arquivo."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
