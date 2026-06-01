"""
Câmbio de moeda estrangeira → BRL (cotação atual), com cache e override manual.

Usado para converter ativos em USD/EUR/GBP para reais pela cotação de HOJE
(em vez do câmbio da compra), deixando a visão em R$ mais fiel.

Fonte: Banco Central (série SGS, mesma API do CDI) — taxa de câmbio de venda.
Sem dependências externas (urllib puro), tolerante a offline (usa o cache).

Prioridade da taxa usada: override manual → cache do BCB → None (o chamador
cai no câmbio da compra como fallback).
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import Configuracao

# Séries SGS do BCB (taxa de câmbio de venda, diária). Extensível.
_SERIES = {"USD": 1}  # USD/BRL. (EUR/GBP podem ser adicionados com seus códigos.)

_BCB_ULTIMO = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/1?formato=json"
_CONFIG_SYNC = "cambio_sync_em"
_INTERVALO_SYNC_HORAS = 6


# --------------------------------------------------------------------------
# Config helpers (tabela chave/valor)
# --------------------------------------------------------------------------
def _cfg_get(db: Session, chave: str):
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    return c.valor if c else None


def _cfg_set(db: Session, chave: str, valor):
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    if not c:
        c = Configuracao(chave=chave, valor="")
        db.add(c)
    c.valor = "" if valor is None else str(valor)


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        f = float(str(v).replace(",", "."))
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# Download / sincronização
# --------------------------------------------------------------------------
def _baixar_ultimo(serie: int, tentativas: int = 3):
    """Última cotação publicada da série SGS. (valor, data_str) ou (None, None)."""
    url = _BCB_ULTIMO.format(serie=serie)
    req = urllib.request.Request(url, headers={"User-Agent": "Nexum/1.0"})
    ctx = ssl.create_default_context()
    ultimo_erro = None
    for _ in range(max(1, tentativas)):
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
            if dados:
                item = dados[-1]
                return _to_float(item.get("valor")), item.get("data")
            return None, None
        except Exception as e:
            ultimo_erro = e
    if ultimo_erro:
        raise ultimo_erro
    return None, None


def _precisa_sincronizar(db: Session) -> bool:
    em = _cfg_get(db, _CONFIG_SYNC)
    if not em:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(em)) > timedelta(hours=_INTERVALO_SYNC_HORAS)
    except ValueError:
        return True


def sincronizar(db: Session, forcar: bool = False) -> dict:
    """Atualiza o cache das cotações no BCB. Tolerante a offline.

    Só vai à rede se o cache estiver velho (>6h) ou se `forcar`. Nunca levanta:
    em erro de rede, mantém o que já tem em cache.
    """
    if not forcar and not _precisa_sincronizar(db):
        return {"ok": True, "atualizado": False, "erro": None}

    atualizou = False
    erro = None
    for moeda, serie in _SERIES.items():
        try:
            taxa, data_ref = _baixar_ultimo(serie)
        except Exception as e:  # offline / API fora do ar
            erro = str(e)
            continue
        if taxa:
            _cfg_set(db, f"cambio_{moeda.lower()}", taxa)
            _cfg_set(db, f"cambio_{moeda.lower()}_data", data_ref or "")
            atualizou = True

    _cfg_set(db, _CONFIG_SYNC, datetime.now().isoformat())
    # Tolerante a corrida: a página de investimentos dispara /resumo e
    # /cambio/status em paralelo (sessões separadas); os dois podem tentar
    # inserir 'cambio_usd' ao mesmo tempo (UNIQUE em configuracoes). Em conflito,
    # rollback em vez de envenenar a sessão (o outro request já gravou).
    try:
        db.commit()
    except Exception:
        db.rollback()
        return {"ok": True, "atualizado": False, "erro": "conflito_concorrente"}
    return {"ok": erro is None, "atualizado": atualizou, "erro": erro}


# --------------------------------------------------------------------------
# Leitura / override manual
# --------------------------------------------------------------------------
def set_manual(db: Session, moeda: str, valor) -> None:
    """Define (ou limpa, se valor vazio) o override manual da cotação da moeda."""
    chave = f"cambio_{(moeda or '').lower()}_manual"
    _cfg_set(db, chave, _to_float(valor) if valor not in (None, "") else "")
    db.commit()


def taxa_atual(db: Session, moeda: str):
    """Taxa moeda→BRL atual. Prioridade: manual → cache BCB → None. BRL=1.0."""
    if not moeda or moeda.upper() == "BRL":
        return 1.0
    m = moeda.lower()
    manual = _to_float(_cfg_get(db, f"cambio_{m}_manual"))
    if manual:
        return manual
    return _to_float(_cfg_get(db, f"cambio_{m}"))


def status(db: Session) -> dict:
    """Estado do câmbio: valor automático (BCB), override manual e o usado."""
    moedas = {}
    for moeda in _SERIES:
        m = moeda.lower()
        moedas[moeda] = {
            "auto": _to_float(_cfg_get(db, f"cambio_{m}")),
            "manual": _to_float(_cfg_get(db, f"cambio_{m}_manual")),
            "data_bcb": _cfg_get(db, f"cambio_{m}_data") or None,
            "usado": taxa_atual(db, moeda),
        }
    return {"sincronizado_em": _cfg_get(db, _CONFIG_SYNC), "moedas": moedas}
