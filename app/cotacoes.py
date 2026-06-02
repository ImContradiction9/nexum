"""
Cotação de renda variável (ações/ETFs/FIIs) via Yahoo Finance.

Busca o preço atual pelo ticker, com cache e atualização preguiçosa (lazy),
tolerante a offline — mesmo padrão do CDI/câmbio. Sem chave de API.

Mapeamento de símbolo:
  - ticker já com sufixo de bolsa (ex: "VWRA.L") → usado como está
  - ativo em BRL sem sufixo (ex: "PETR4", "BOVA11") → vira "PETR4.SA" (B3)
  - demais (USD/EUR sem sufixo, ex: "IVV") → usado como está (EUA)

O cache fica num JSON na tabela Configuracao: {TICKER: {preco, moeda, sym, em}}.
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import Configuracao

_CACHE_KEY = "cotacoes_cache"
_SYNC_KEY = "cotacoes_sync_em"
_INTERVALO_HORAS = 3
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _cfg_get(db: Session, chave: str):
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    return c.valor if c else None


def _cfg_set(db: Session, chave: str, valor: str):
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    if not c:
        c = Configuracao(chave=chave, valor="")
        db.add(c)
    c.valor = valor


def simbolo_yahoo(ticker: str, moeda: str) -> str | None:
    t = (ticker or "").strip().upper()
    if not t:
        return None
    if "." in t:
        return t
    if (moeda or "BRL").upper() == "BRL":
        return t + ".SA"
    return t


def _buscar(sym: str, tentativas: int = 2):
    url = _YAHOO.format(sym=sym)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    ctx = ssl.create_default_context()
    erro = None
    for _ in range(max(1, tentativas)):
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                d = json.loads(r.read().decode("utf-8"))
            m = d["chart"]["result"][0]["meta"]
            preco = m.get("regularMarketPrice")
            moeda = m.get("currency")
            if preco:
                return float(preco), moeda
            return None, None
        except Exception as e:
            erro = e
    if erro:
        raise erro
    return None, None


def carregar_cache(db: Session) -> dict:
    """{TICKER: {preco, moeda, sym, em}} do cache."""
    raw = _cfg_get(db, _CACHE_KEY)
    try:
        return json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}


def _precisa(db: Session) -> bool:
    em = _cfg_get(db, _SYNC_KEY)
    if not em:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(em)) > timedelta(hours=_INTERVALO_HORAS)
    except ValueError:
        return True


def sincronizar(db: Session, ativos, forcar: bool = False) -> dict:
    """Atualiza o cache de cotações dos `ativos` (lista de (ticker, moeda)).

    Lazy: só vai à rede se o cache estiver velho (>3h) ou `forcar`. Tolerante a
    offline — em erro, mantém o que já tem.
    """
    if not forcar and not _precisa(db):
        return {"ok": True, "atualizado": False, "n": 0, "erro": None}

    cache = carregar_cache(db)
    erro = None
    n = 0
    vistos = set()
    for ticker, moeda in ativos:
        sym = simbolo_yahoo(ticker, moeda)
        if not sym or sym in vistos:
            continue
        vistos.add(sym)
        try:
            preco, cur = _buscar(sym)
        except Exception as e:  # offline / símbolo inválido / rate limit
            erro = str(e)
            continue
        if preco:
            cache[(ticker or "").strip().upper()] = {
                "preco": preco, "moeda": cur, "sym": sym,
                "em": datetime.now().isoformat(),
            }
            n += 1

    _cfg_set(db, _CACHE_KEY, json.dumps(cache))
    _cfg_set(db, _SYNC_KEY, datetime.now().isoformat())
    try:
        db.commit()
    except Exception:
        db.rollback()
    # Sucesso parcial conta como ok (ex: 1 ticker inválido entre vários).
    return {"ok": (n > 0 or erro is None), "atualizado": n > 0, "n": n, "erro": erro}


def cotacao_de(cache: dict, ticker: str):
    """Devolve o dict {preco, moeda, sym, em} do ticker no cache, ou None."""
    if not ticker:
        return None
    return cache.get(ticker.strip().upper())


def status(db: Session) -> dict:
    cache = carregar_cache(db)
    return {
        "sincronizado_em": _cfg_get(db, _SYNC_KEY),
        "n_tickers": len(cache),
        "cotacoes": cache,
    }
