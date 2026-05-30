"""
Série CDI (Banco Central / SGS série 12) — download, cache e cálculo de
rendimento de renda fixa indexada ao CDI.

A série 12 do SGS traz a taxa CDI **diária**, em % ao dia (ex: 0.053400).
O fator de um dia para "p% do CDI" é:  1 + (taxa_dia/100) * (p/100).
O saldo de um título é o capital acumulado por esses fatores, dia a dia,
desde cada aporte até hoje (juros compostos).

Tudo é cacheado na tabela cdi_diario para funcionar offline depois da 1ª
sincronização. A sincronização com a internet é incremental e tolerante a
falhas (se estiver offline, usa o que já tem em cache).
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .database import CDIDiario, Configuracao

_BCB_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"
    "?formato=json&dataInicial={ini}&dataFinal={fim}"
)
_CONFIG_SYNC = "cdi_sync_em"          # ISO datetime da última sincronização
_INTERVALO_SYNC_HORAS = 6             # não bate na rede mais que isso (sem forçar)
_DIAS_UTEIS_ANO = 252


# --------------------------------------------------------------------------
# Download / sincronização
# --------------------------------------------------------------------------
def _baixar_bcb(inicio: date, fim: date, tentativas: int = 3) -> list[tuple[date, float]]:
    """Baixa a série CDI do BCB no intervalo [inicio, fim]. Lança em erro de rede.

    O endpoint SGS é intermitente (devolve 502 esporádico); tenta algumas vezes
    antes de desistir."""
    url = _BCB_URL.format(ini=inicio.strftime("%d/%m/%Y"), fim=fim.strftime("%d/%m/%Y"))
    req = urllib.request.Request(url, headers={"User-Agent": "Nexum/1.0"})
    ctx = ssl.create_default_context()
    ultimo_erro = None
    for _ in range(max(1, tentativas)):
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            ultimo_erro = e
            dados = None
    if dados is None:
        raise ultimo_erro
    out = []
    for item in dados:
        try:
            d = datetime.strptime(item["data"], "%d/%m/%Y").date()
            taxa = float(item["valor"])
        except (KeyError, ValueError):
            continue
        out.append((d, taxa))
    return out


def _ultima_data_cache(db: Session):
    row = db.query(CDIDiario.data).order_by(CDIDiario.data.desc()).first()
    return row[0] if row else None


def _precisa_sincronizar(db: Session) -> bool:
    cfg = db.query(Configuracao).filter(Configuracao.chave == _CONFIG_SYNC).first()
    if not cfg or not cfg.valor:
        return True
    try:
        ultimo = datetime.fromisoformat(cfg.valor)
    except ValueError:
        return True
    return (datetime.now() - ultimo) > timedelta(hours=_INTERVALO_SYNC_HORAS)


def _marcar_sincronizado(db: Session):
    cfg = db.query(Configuracao).filter(Configuracao.chave == _CONFIG_SYNC).first()
    if not cfg:
        cfg = Configuracao(chave=_CONFIG_SYNC, valor="")
        db.add(cfg)
    cfg.valor = datetime.now().isoformat()


def sincronizar(db: Session, desde: date | None = None, forcar: bool = False) -> dict:
    """
    Garante que o cache CDI vai até hoje. Busca incrementalmente a partir do
    último dia em cache (ou de `desde`, o que for mais antigo que faltar).
    Tolerante a falha de rede: se offline, mantém o cache atual.

    Retorna um resumo {ok, atualizado, ultima_data, dias_baixados, erro}.
    """
    if not forcar and not _precisa_sincronizar(db):
        return {"ok": True, "atualizado": False, "ultima_data": _iso(_ultima_data_cache(db)),
                "dias_baixados": 0, "erro": None}

    hoje = date.today()
    ultima = _ultima_data_cache(db)
    if forcar and desde:
        inicio = desde
    elif ultima:
        inicio = ultima + timedelta(days=1)
    elif desde:
        inicio = desde
    else:
        inicio = hoje - timedelta(days=365 * 3)

    if inicio > hoje:
        # cache já está em dia
        _marcar_sincronizado(db)
        db.commit()
        return {"ok": True, "atualizado": False, "ultima_data": _iso(ultima),
                "dias_baixados": 0, "erro": None}

    try:
        novos = _baixar_bcb(inicio, hoje)
    except Exception as e:  # offline / timeout / API fora do ar
        return {"ok": False, "atualizado": False, "ultima_data": _iso(ultima),
                "dias_baixados": 0, "erro": str(e)}

    existentes = {r[0] for r in db.query(CDIDiario.data).all()}
    n = 0
    for d, taxa in novos:
        if d in existentes:
            continue
        db.add(CDIDiario(data=d, taxa=taxa))
        existentes.add(d)
        n += 1
    _marcar_sincronizado(db)
    db.commit()
    return {"ok": True, "atualizado": n > 0, "ultima_data": _iso(_ultima_data_cache(db)),
            "dias_baixados": n, "erro": None}


# --------------------------------------------------------------------------
# Leitura / cálculo
# --------------------------------------------------------------------------
def carregar_serie(db: Session) -> dict:
    """Carrega o cache CDI como {date: taxa_pct_dia}."""
    return {r.data: r.taxa for r in db.query(CDIDiario).all()}


def saldo_composto(flows: list, serie: dict, percentual: float, ate: date | None = None) -> float:
    """
    Capital acumulado por juros compostos diários a p% do CDI.

    flows: lista de (data, valor_assinado) — aportes positivos, resgates
           negativos. O fluxo entra no saldo na sua data e passa a render no
           dia útil seguinte (dias sem CDI publicado têm fator 1).
    serie: {date: taxa_pct_dia} (cache CDI).
    percentual: % do CDI (100 = 100%, 120 = 120%).
    ate: data final do cálculo (default = última data com CDI em cache, ou hoje).
    """
    if not flows:
        return 0.0
    p = (percentual or 0) / 100.0
    flows = sorted(flows, key=lambda x: x[0])
    inicio = flows[0][0]
    # A data final precisa cobrir: a última data com CDI publicado, hoje, e a
    # data do último fluxo (ex: resgate de hoje, ainda sem CDI do dia). Dias
    # sem CDI publicado não rendem (fator 1), mas os fluxos do dia são aplicados.
    fim_serie = max(serie.keys()) if serie else date.today()
    if ate is None:
        ate = max(fim_serie, flows[-1][0], date.today())
    if ate < inicio:
        ate = inicio

    # Mapa data -> soma dos fluxos do dia (pode haver mais de um no mesmo dia).
    por_dia: dict = {}
    for d, v in flows:
        por_dia[d] = por_dia.get(d, 0.0) + v

    saldo = 0.0
    dia = inicio
    um_dia = timedelta(days=1)
    while dia <= ate:
        if dia in por_dia:
            saldo += por_dia[dia]
        taxa = serie.get(dia)
        if taxa:
            saldo *= 1 + (taxa / 100.0) * p
        dia += um_dia
    return saldo


def cdi_anual(serie: dict) -> float:
    """Taxa CDI anualizada (fração, ex: 0.1435) a partir do último dia em cache."""
    if not serie:
        return 0.0
    ultima = max(serie.keys())
    taxa_dia = serie[ultima] / 100.0
    return (1 + taxa_dia) ** _DIAS_UTEIS_ANO - 1


def _iso(d):
    return d.isoformat() if d else None
