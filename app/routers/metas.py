"""Metas de patrimônio: progresso, projeção composta e escopos.

Extraído de main.py (refactor por domínio). Reutiliza helpers de investimentos.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Ativo, OperacaoInvestimento, Meta
from .. import cdi as cdi_mod
from .. import cambio as cambio_mod
from .. import impostos

# Moedas aceitas no alvo de uma meta (as que temos cotação BRL via BCB).
MOEDAS_META = ["BRL", "USD", "EUR"]
from .investimentos import (
    _serializar_ativo, _cdi_serie, _parse_float_ou_none,
    TIPOS_ATIVO, TIPOS_RENDA_FIXA,
)

router = APIRouter()


# ============================================================
# METAS DE PATRIMÔNIO
# ============================================================

import json as _json


def _calcular_saldos_brl(db: Session):
    """
    Calcula, em BRL, o saldo atual de cada ativo da carteira e devolve:
      total_brl        — soma de tudo
      por_tipo         — {tipo: saldo_brl}
      ritmo_mensal_brl — média mensal de aportes desde o 1º aporte (em BRL)
      ritmo_por_tipo   — {tipo: aporte_mensal_brl} desde o 1º aporte do tipo
    Reaproveita a lógica de /api/investimentos/resumo (último câmbio registrado).

    Também devolve a taxa de retorno anual esperada (fração) ponderada pelo
    saldo, usada na projeção composta das metas:
      taxa_anual_total      — média ponderada de toda a carteira
      taxa_anual_por_tipo   — {tipo: taxa_anual}
      cdi_anual             — CDI anualizado atual (referência)
    Renda fixa indexada (cdi_percentual) usa CDI×%; demais ativos entram com 0
    (sem taxa determinística) — a meta pode sobrepor com taxa_retorno_anual.
    """
    ativos = db.query(Ativo).filter(Ativo.ativo == True).all()
    todas_ops = db.query(OperacaoInvestimento).all()
    por_ativo_ops = {}
    for op in todas_ops:
        por_ativo_ops.setdefault(op.ativo_id, []).append(op)

    serie = _cdi_serie(db)
    cdi_aa = cdi_mod.cdi_anual(serie)

    # Sincroniza as cotações UMA vez antes do loop, pra valorizar os ativos em
    # moeda estrangeira pela taxa de HOJE (mesma da carteira).
    try:
        cambio_mod.sincronizar(db)
    except Exception:
        pass

    total_brl = 0.0
    por_tipo = {}
    por_ativo = {}        # {ativo_id: saldo_brl}
    # Versões LÍQUIDAS (IR + IOF estimados) — usadas nas projeções de meta.
    total_liquido_brl = 0.0
    por_tipo_liquido = {}
    por_ativo_liquido = {}
    ativo_por_id = {}
    # Acumuladores para a taxa de retorno ponderada pelo saldo (bruta e líquida).
    peso_por_tipo = {}
    retorno_pond_por_tipo = {}
    retorno_pond_liq_por_tipo = {}
    taxa_anual_por_ativo = {}        # {ativo_id: taxa_anual bruta}
    taxa_anual_liq_por_ativo = {}    # {ativo_id: taxa_anual líquida}
    peso_total = 0.0
    retorno_pond_total = 0.0
    retorno_pond_liq_total = 0.0
    for a in ativos:
        ativo_por_id[a.id] = a
        ops = por_ativo_ops.get(a.id, [])
        ultimo_cambio = 1.0
        if a.moeda != "BRL":
            # Câmbio de HOJE (mesma cotação da carteira/patrimônio) — mantém metas
            # e patrimônio consistentes. Só cai pro câmbio da última operação se
            # não houver cotação atual disponível.
            ultimo_cambio = cambio_mod.taxa_atual(db, a.moeda)
            if not ultimo_cambio:
                ultimo_cambio = 1.0
                for op in sorted(ops, key=lambda x: x.data, reverse=True):
                    if op.cotacao_cambio:
                        ultimo_cambio = op.cotacao_cambio
                        break
        # Usa o mesmo saldo da carteira (_serializar_ativo): saldo manual se
        # informado, senão CDI (renda fixa indexada), senão soma de operações.
        ser = _serializar_ativo(a, ops, serie)
        cambio = ultimo_cambio if a.moeda != "BRL" else 1
        atual_brl = max(ser["saldo_atual"] * cambio, 0)
        atual_liq_brl = max(ser["saldo_liquido"] * cambio, 0)
        total_brl += atual_brl
        total_liquido_brl += atual_liq_brl
        por_tipo[a.tipo] = por_tipo.get(a.tipo, 0.0) + atual_brl
        por_tipo_liquido[a.tipo] = por_tipo_liquido.get(a.tipo, 0.0) + atual_liq_brl
        por_ativo[a.id] = atual_brl
        por_ativo_liquido[a.id] = atual_liq_brl

        # Taxa esperada do ativo: CDI×% para renda fixa indexada, senão 0.
        if a.cdi_percentual and a.tipo in TIPOS_RENDA_FIXA:
            taxa_ativo = cdi_aa * (a.cdi_percentual / 100.0)
        else:
            taxa_ativo = 0.0
        # Taxa líquida de longo prazo: desconta o IR (15%, ou 0 se isento).
        taxa_ativo_liq = taxa_ativo * (1 - impostos.aliquota_ir_longo_prazo(a.tipo))
        taxa_anual_por_ativo[a.id] = taxa_ativo
        taxa_anual_liq_por_ativo[a.id] = taxa_ativo_liq
        peso_por_tipo[a.tipo] = peso_por_tipo.get(a.tipo, 0.0) + atual_brl
        retorno_pond_por_tipo[a.tipo] = retorno_pond_por_tipo.get(a.tipo, 0.0) + atual_brl * taxa_ativo
        retorno_pond_liq_por_tipo[a.tipo] = retorno_pond_liq_por_tipo.get(a.tipo, 0.0) + atual_brl * taxa_ativo_liq
        peso_total += atual_brl
        retorno_pond_total += atual_brl * taxa_ativo
        retorno_pond_liq_total += atual_brl * taxa_ativo_liq

    # Ritmo de aporte: média mensal desde o PRIMEIRO aporte de cada escopo
    # (não uma janela fixa de 90 dias). Assim o "ritmo atual" reflete o
    # histórico real: total de compras+aportes ÷ meses desde o 1º aporte.
    hoje = date.today()
    soma_total = 0.0
    soma_por_tipo = {}
    soma_por_ativo = {}
    primeira_total = None
    primeira_por_tipo = {}
    primeira_por_ativo = {}
    for op in todas_ops:
        if op.tipo not in ("Compra", "Aporte") or not op.data:
            continue
        a = ativo_por_id.get(op.ativo_id)
        if not a:
            continue
        cambio = op.cotacao_cambio if op.cotacao_cambio else 1.0
        valor_brl = (op.valor_total or 0) * (cambio if a.moeda != "BRL" else 1)
        soma_total += valor_brl
        soma_por_tipo[a.tipo] = soma_por_tipo.get(a.tipo, 0.0) + valor_brl
        soma_por_ativo[op.ativo_id] = soma_por_ativo.get(op.ativo_id, 0.0) + valor_brl
        if primeira_total is None or op.data < primeira_total:
            primeira_total = op.data
        if a.tipo not in primeira_por_tipo or op.data < primeira_por_tipo[a.tipo]:
            primeira_por_tipo[a.tipo] = op.data
        if op.ativo_id not in primeira_por_ativo or op.data < primeira_por_ativo[op.ativo_id]:
            primeira_por_ativo[op.ativo_id] = op.data

    def _meses_desde(d):
        # Meses decorridos desde a data (mínimo 1 mês, p/ início recente não estourar).
        return max((hoje - d).days / 30.44, 1.0) if d else 1.0

    ritmo_mensal_brl = (soma_total / _meses_desde(primeira_total)) if primeira_total else 0.0
    ritmo_por_tipo_mensal = {t: v / _meses_desde(primeira_por_tipo.get(t)) for t, v in soma_por_tipo.items()}
    ritmo_por_ativo_mensal = {i: v / _meses_desde(primeira_por_ativo.get(i)) for i, v in soma_por_ativo.items()}

    taxa_anual_por_tipo = {
        t: (retorno_pond_por_tipo[t] / peso_por_tipo[t]) if peso_por_tipo.get(t) else 0.0
        for t in por_tipo
    }
    taxa_anual_liq_por_tipo = {
        t: (retorno_pond_liq_por_tipo[t] / peso_por_tipo[t]) if peso_por_tipo.get(t) else 0.0
        for t in por_tipo
    }
    taxa_anual_total = (retorno_pond_total / peso_total) if peso_total > 0 else 0.0
    taxa_anual_liq_total = (retorno_pond_liq_total / peso_total) if peso_total > 0 else 0.0

    # Cotações atuais (moeda→BRL) pra metas com alvo em moeda estrangeira.
    # (já sincronizado no início da função)
    cambio_metas = {"BRL": 1.0}
    for _m in ("USD", "EUR"):
        try:
            cambio_metas[_m] = cambio_mod.taxa_atual(db, _m) or None
        except Exception:
            cambio_metas[_m] = None

    return {
        "total_brl": total_brl,
        "cambio": cambio_metas,
        "por_tipo": por_tipo,
        "por_ativo": por_ativo,
        # Líquidos (IR+IOF) — base das projeções de meta.
        "total_liquido_brl": total_liquido_brl,
        "por_tipo_liquido": por_tipo_liquido,
        "por_ativo_liquido": por_ativo_liquido,
        "ritmo_mensal_brl": ritmo_mensal_brl,
        "ritmo_por_tipo_mensal": ritmo_por_tipo_mensal,
        "ritmo_por_ativo_mensal": ritmo_por_ativo_mensal,
        "tipo_por_ativo": {aid: a.tipo for aid, a in ativo_por_id.items()},
        "objetivo_por_ativo": {aid: (a.objetivo or "patrimonio") for aid, a in ativo_por_id.items()},
        "taxa_anual_por_tipo": taxa_anual_por_tipo,
        "taxa_anual_por_ativo": taxa_anual_por_ativo,
        "taxa_anual_total": taxa_anual_total,
        # Taxas líquidas de longo prazo (desconta IR 15%).
        "taxa_anual_liq_por_tipo": taxa_anual_liq_por_tipo,
        "taxa_anual_liq_por_ativo": taxa_anual_liq_por_ativo,
        "taxa_anual_liq_total": taxa_anual_liq_total,
        "cdi_anual": cdi_aa,
    }


def _taxa_anual_meta(meta: Meta, saldos: dict) -> float:
    """Taxa de retorno anual LÍQUIDA (fração) usada na projeção composta da meta.

    Prioridade: override manual da meta (taxa_retorno_anual, usado como já
    líquido) → taxa líquida derivada do CDI dos ativos no escopo (ponderada
    pelo saldo, descontando IR de longo prazo) → 0.
    As chaves líquidas têm fallback para as brutas (compat com saldos sintéticos)."""
    if meta.taxa_retorno_anual is not None:
        return meta.taxa_retorno_anual / 100.0
    taxa_total = saldos.get("taxa_anual_liq_total", saldos.get("taxa_anual_total", 0.0))
    taxa_por_tipo = saldos.get("taxa_anual_liq_por_tipo", saldos.get("taxa_anual_por_tipo", {}))
    taxa_por_ativo = saldos.get("taxa_anual_liq_por_ativo", saldos.get("taxa_anual_por_ativo", {}))
    if meta.escopo == "patrimonio_total":
        return taxa_total
    if meta.escopo == "tipos_ativo":
        try:
            tipos = _json.loads(meta.escopo_tipos or "[]")
        except Exception:
            tipos = []
        pesos = sum(saldos["por_tipo"].get(t, 0) for t in tipos)
        if pesos <= 0:
            return 0.0
        pond = sum(saldos["por_tipo"].get(t, 0) * taxa_por_tipo.get(t, 0.0) for t in tipos)
        return pond / pesos
    if meta.escopo == "ativos":
        try:
            ids = _json.loads(meta.escopo_ativos or "[]")
        except Exception:
            ids = []
        pesos = sum(saldos.get("por_ativo", {}).get(i, 0) for i in ids)
        if pesos <= 0:
            return 0.0
        pond = sum(saldos.get("por_ativo", {}).get(i, 0) * taxa_por_ativo.get(i, 0.0) for i in ids)
        return pond / pesos
    return 0.0


def _meses_ate_meta(atual: float, alvo: float, aporte_mensal: float, r_mensal: float, teto=1200):
    """Quantos meses até o saldo atingir o alvo, com aportes mensais e juros
    compostos mensais. None se nunca atinge dentro do teto."""
    if atual >= alvo:
        return 0
    if aporte_mensal <= 0 and r_mensal <= 0:
        return None
    saldo = atual
    for m in range(1, teto + 1):
        saldo = saldo * (1 + r_mensal) + aporte_mensal
        if saldo >= alvo:
            return m
    return None


def _calcular_progresso_meta(meta: Meta, saldos: dict) -> dict:
    """
    Dado o resultado de _calcular_saldos_brl, devolve as métricas
    calculadas da meta: valor_atual, percentual, aporte_mensal_necessario,
    projecao_data_atingimento. A projeção é composta: o capital atual rende
    à taxa esperada e os aportes mensais também rendem ao longo do tempo.
    """
    # Projeções usam o saldo LÍQUIDO (IR+IOF); guardamos o bruto p/ referência.
    # Chaves líquidas têm fallback para as brutas (compat com saldos sintéticos).
    por_tipo_liq = saldos.get("por_tipo_liquido", saldos.get("por_tipo", {}))
    por_ativo_liq = saldos.get("por_ativo_liquido", saldos.get("por_ativo", {}))
    por_ativo_brt = saldos.get("por_ativo", {})
    ritmo_por_ativo = saldos.get("ritmo_por_ativo_mensal", {})
    tipo_por_ativo = saldos.get("tipo_por_ativo", {})
    objetivo_por_ativo = saldos.get("objetivo_por_ativo", {})

    # Ativos a IGNORAR nesta meta (ex: reservas pra carro/casa fora do "patrimônio").
    try:
        excluir = {int(i) for i in _json.loads(meta.escopo_excluir_ativos or "[]")}
    except Exception:
        excluir = set()

    if meta.escopo == "patrimonio_total":
        # Patrimônio = só ativos com objetivo='patrimonio' (exclui reservas de
        # aquisição de bens, ex: carro/casa). Ignorados manuais saem por cima.
        ids_pat = [i for i, o in objetivo_por_ativo.items()
                   if o == "patrimonio" and i not in excluir]
        # Sem o mapa (saldos sintéticos de teste), cai no total geral.
        if objetivo_por_ativo:
            valor_atual = sum(por_ativo_liq.get(i, 0) for i in ids_pat)
            valor_atual_bruto = sum(por_ativo_brt.get(i, 0) for i in ids_pat)
            ritmo = sum(ritmo_por_ativo.get(i, 0) for i in ids_pat)
        else:
            valor_atual = saldos.get("total_liquido_brl", saldos["total_brl"])
            valor_atual_bruto = saldos["total_brl"]
            ritmo = saldos["ritmo_mensal_brl"]
            for i in excluir:
                valor_atual -= por_ativo_liq.get(i, 0)
                valor_atual_bruto -= por_ativo_brt.get(i, 0)
                ritmo -= ritmo_por_ativo.get(i, 0)
    elif meta.escopo == "tipos_ativo":
        try:
            tipos = _json.loads(meta.escopo_tipos or "[]")
        except Exception:
            tipos = []
        valor_atual = sum(por_tipo_liq.get(t, 0) for t in tipos)
        valor_atual_bruto = sum(saldos["por_tipo"].get(t, 0) for t in tipos)
        ritmo = sum(saldos["ritmo_por_tipo_mensal"].get(t, 0) for t in tipos)
        for i in excluir:                       # só os que estão dentro dos tipos do escopo
            if tipo_por_ativo.get(i) in tipos:
                valor_atual -= por_ativo_liq.get(i, 0)
                valor_atual_bruto -= por_ativo_brt.get(i, 0)
                ritmo -= ritmo_por_ativo.get(i, 0)
    elif meta.escopo == "ativos":
        try:
            ids = _json.loads(meta.escopo_ativos or "[]")
        except Exception:
            ids = []
        ids = [i for i in ids if i not in excluir]
        valor_atual = sum(por_ativo_liq.get(i, 0) for i in ids)
        valor_atual_bruto = sum(por_ativo_brt.get(i, 0) for i in ids)
        ritmo = sum(ritmo_por_ativo.get(i, 0) for i in ids)
    else:  # manual
        valor_atual = meta.valor_atual_manual or 0
        valor_atual_bruto = valor_atual
        ritmo = 0

    # Clamp (exclusões/líquido podem gerar resíduo negativo).
    valor_atual = max(valor_atual, 0.0)
    valor_atual_bruto = max(valor_atual_bruto, 0.0)
    ritmo = max(ritmo, 0.0)

    # Alvo convertido pra BRL pela cotação atual (ajusta sozinho conforme o câmbio).
    # Tudo abaixo (percentual, falta, projeção, aporte) usa o alvo EM BRL, porque
    # os saldos da carteira já estão em BRL.
    moeda_meta = (meta.moeda or "BRL").upper()
    taxa_cambio = (saldos.get("cambio", {}) or {}).get(moeda_meta)
    if not taxa_cambio:
        taxa_cambio = 1.0   # sem cotação (BRL ou ainda não sincronizado) → 1:1
    valor_alvo_brl = (meta.valor_alvo or 0) * taxa_cambio

    percentual = (valor_atual / valor_alvo_brl * 100) if valor_alvo_brl > 0 else 0
    falta = max(valor_alvo_brl - valor_atual, 0)

    # Taxa de retorno: anual (fração) → mensal equivalente.
    r_anual = _taxa_anual_meta(meta, saldos)
    r_mensal = (1 + r_anual) ** (1 / 12) - 1 if r_anual > 0 else 0.0

    aporte_mensal_necessario = None
    meses_restantes = None
    if meta.data_alvo:
        hoje = date.today()
        delta_dias = (meta.data_alvo - hoje).days
        meses_restantes = max(delta_dias / 30.4375, 0)
        if meses_restantes > 0 and falta > 0:
            t = meses_restantes
            if r_mensal > 0:
                # FV = atual*(1+r)^t + aporte * ((1+r)^t - 1)/r  ==>  resolve aporte
                cresc = (1 + r_mensal) ** t
                fator = (cresc - 1) / r_mensal
                fv_sem_aporte = valor_atual * cresc
                aporte = (valor_alvo_brl - fv_sem_aporte) / fator if fator > 0 else 0
                aporte_mensal_necessario = max(aporte, 0)
            else:
                aporte_mensal_necessario = falta / t
        elif falta == 0:
            aporte_mensal_necessario = 0

    # Prazo já passou e a meta não foi atingida → "pra bater no prazo" é inviável.
    prazo_vencido = bool(meta.data_alvo and meta.data_alvo < date.today() and falta > 0)

    projecao_data = None
    meses_projetados = None
    if falta == 0:
        projecao_data = "atingida"
    else:
        m = _meses_ate_meta(valor_atual, valor_alvo_brl, ritmo, r_mensal)
        if m is not None:
            meses_projetados = m
            dias = int(round(m * 30.4375))
            projecao_data = (date.today() + timedelta(days=dias)).isoformat()

    return {
        "valor_atual": round(valor_atual, 2),
        "valor_atual_bruto": round(valor_atual_bruto, 2),
        "valor_alvo_brl": round(valor_alvo_brl, 2),   # alvo convertido pra BRL (câmbio atual)
        "cambio_usado": round(taxa_cambio, 4) if moeda_meta != "BRL" else None,
        "percentual": round(percentual, 2),
        "falta": round(falta, 2),
        "ritmo_mensal_estimado": round(ritmo, 2),
        "taxa_retorno_anual": round(r_anual * 100, 2),
        "meses_restantes": round(meses_restantes, 1) if meses_restantes is not None else None,
        "prazo_vencido": prazo_vencido,
        "aporte_mensal_necessario": round(aporte_mensal_necessario, 2) if aporte_mensal_necessario is not None else None,
        "meses_projetados": round(meses_projetados, 1) if meses_projetados is not None else None,
        "projecao_data_atingimento": projecao_data,
    }


def _serializar_meta(meta: Meta, saldos: dict) -> dict:
    prog = _calcular_progresso_meta(meta, saldos)
    try:
        tipos = _json.loads(meta.escopo_tipos or "[]")
    except Exception:
        tipos = []
    try:
        ativos_ids = _json.loads(meta.escopo_ativos or "[]")
    except Exception:
        ativos_ids = []
    try:
        excluir_ids = _json.loads(meta.escopo_excluir_ativos or "[]")
    except Exception:
        excluir_ids = []
    return {
        "id": meta.id,
        "nome": meta.nome,
        "descricao": meta.descricao,
        "meta_pai_id": meta.meta_pai_id,
        "escopo": meta.escopo,
        "escopo_tipos": tipos,
        "escopo_ativos": ativos_ids,
        "escopo_excluir_ativos": excluir_ids,
        "objetivo": meta.objetivo or "patrimonio",
        "valor_atual_manual": meta.valor_atual_manual or 0,
        "valor_alvo": meta.valor_alvo,                 # no valor da moeda da meta
        "moeda": (meta.moeda or "BRL"),
        "data_alvo": meta.data_alvo.isoformat() if meta.data_alvo else None,
        # Override manual da taxa (None = usa a derivada do CDI). O valor
        # efetivamente usado vem em prog["taxa_retorno_anual"].
        "taxa_retorno_anual_override": meta.taxa_retorno_anual,
        "ordem": meta.ordem or 0,
        "cor": meta.cor,
        "ativa": meta.ativa,
        "atingida_em": meta.atingida_em.isoformat() if meta.atingida_em else None,
        "criada_em": meta.criada_em.isoformat() if meta.criada_em else None,
        **prog,
    }


@router.get("/api/metas")
def listar_metas(incluir_inativas: bool = False, db: Session = Depends(get_db)):
    """Lista todas as metas com progresso calculado e em formato de árvore (níveis)."""
    q = db.query(Meta)
    if not incluir_inativas:
        q = q.filter(Meta.ativa == True)
    metas = q.order_by(Meta.ordem, Meta.id).all()

    saldos = _calcular_saldos_brl(db)
    serializadas = [_serializar_meta(m, saldos) for m in metas]

    # Marca atingida_em automaticamente quando bate 100% (uma vez).
    mudou = False
    for m, s in zip(metas, serializadas):
        if s["percentual"] >= 100 and not m.atingida_em:
            m.atingida_em = date.today()
            s["atingida_em"] = m.atingida_em.isoformat()
            mudou = True
    if mudou:
        db.commit()

    # Monta árvore (níveis) — cada meta-raiz carrega `sub_metas` recursivamente.
    por_id = {s["id"]: {**s, "sub_metas": []} for s in serializadas}
    raizes = []
    for s in serializadas:
        node = por_id[s["id"]]
        if s["meta_pai_id"] and s["meta_pai_id"] in por_id:
            por_id[s["meta_pai_id"]]["sub_metas"].append(node)
        else:
            raizes.append(node)

    return {
        "metas": raizes,
        "flat": serializadas,
        "tipos_disponiveis": TIPOS_ATIVO,
    }


def _validar_escopo_ativos(db: Session, ids) -> list:
    """Valida uma lista de ids de ativo para escopo=ativos. Lança 400 se inválida."""
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "escopo_ativos deve ser uma lista não-vazia quando escopo=ativos")
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise HTTPException(400, "escopo_ativos deve conter ids numéricos")
    existentes = {row[0] for row in db.query(Ativo.id).all()}
    faltando = [i for i in ids if i not in existentes]
    if faltando:
        raise HTTPException(400, f"ativos inexistentes: {faltando}")
    return ids


def _parse_ids(valor) -> list:
    """Lista de ids de ativo a ignorar (pode ser vazia). Lança 400 se não-numérica."""
    if not valor:
        return []
    if not isinstance(valor, list):
        raise HTTPException(400, "escopo_excluir_ativos deve ser uma lista")
    try:
        return [int(i) for i in valor]
    except (TypeError, ValueError):
        raise HTTPException(400, "escopo_excluir_ativos deve conter ids numéricos")


@router.post("/api/metas")
def criar_meta(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")

    escopo = dados.get("escopo")
    if escopo not in ("patrimonio_total", "tipos_ativo", "ativos", "manual"):
        raise HTTPException(400, "escopo inválido (use patrimonio_total, tipos_ativo, ativos ou manual)")

    try:
        valor_alvo = float(dados.get("valor_alvo") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "valor_alvo inválido")
    if valor_alvo <= 0:
        raise HTTPException(400, "valor_alvo precisa ser maior que zero")

    moeda = (dados.get("moeda") or "BRL").upper()
    if moeda not in MOEDAS_META:
        raise HTTPException(400, f"moeda inválida (use {', '.join(MOEDAS_META)})")

    tipos = dados.get("escopo_tipos") or []
    if escopo == "tipos_ativo":
        if not isinstance(tipos, list) or not tipos:
            raise HTTPException(400, "escopo_tipos deve ser uma lista não-vazia quando escopo=tipos_ativo")
        invalidos = [t for t in tipos if t not in TIPOS_ATIVO]
        if invalidos:
            raise HTTPException(400, f"tipos inválidos: {invalidos}")

    ativos_ids = []
    if escopo == "ativos":
        ativos_ids = _validar_escopo_ativos(db, dados.get("escopo_ativos") or [])

    excluir_ids = _parse_ids(dados.get("escopo_excluir_ativos"))

    data_alvo = None
    if dados.get("data_alvo"):
        try:
            data_alvo = datetime.strptime(dados["data_alvo"], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "data_alvo inválida (use YYYY-MM-DD)")

    meta_pai_id = dados.get("meta_pai_id") or None
    if meta_pai_id:
        pai = db.query(Meta).filter(Meta.id == meta_pai_id).first()
        if not pai:
            raise HTTPException(400, "meta_pai_id não existe")

    m = Meta(
        nome=nome,
        descricao=(dados.get("descricao") or "").strip() or None,
        meta_pai_id=meta_pai_id,
        escopo=escopo,
        escopo_tipos=_json.dumps(tipos) if escopo == "tipos_ativo" else None,
        escopo_ativos=_json.dumps(ativos_ids) if escopo == "ativos" else None,
        escopo_excluir_ativos=_json.dumps(excluir_ids) if excluir_ids else None,
        objetivo=("aquisicao" if dados.get("objetivo") == "aquisicao" else "patrimonio"),
        valor_atual_manual=float(dados.get("valor_atual_manual") or 0) if escopo == "manual" else 0,
        valor_alvo=valor_alvo,
        moeda=moeda,
        data_alvo=data_alvo,
        taxa_retorno_anual=_parse_float_ou_none(dados.get("taxa_retorno_anual")),
        ordem=int(dados.get("ordem") or 0),
        cor=(dados.get("cor") or "").strip() or None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serializar_meta(m, _calcular_saldos_brl(db))


@router.patch("/api/metas/{meta_id}")
def atualizar_meta(meta_id: int, dados: dict, db: Session = Depends(get_db)):
    m = db.query(Meta).filter(Meta.id == meta_id).first()
    if not m:
        raise HTTPException(404, "Meta não encontrada")

    if "nome" in dados:
        nome = (dados.get("nome") or "").strip()
        if not nome:
            raise HTTPException(400, "Nome não pode ficar vazio")
        m.nome = nome
    if "descricao" in dados:
        m.descricao = (dados.get("descricao") or "").strip() or None
    if "valor_alvo" in dados:
        try:
            v = float(dados["valor_alvo"])
        except (TypeError, ValueError):
            raise HTTPException(400, "valor_alvo inválido")
        if v <= 0:
            raise HTTPException(400, "valor_alvo precisa ser maior que zero")
        m.valor_alvo = v
    if "moeda" in dados:
        moeda = (dados.get("moeda") or "BRL").upper()
        if moeda not in MOEDAS_META:
            raise HTTPException(400, f"moeda inválida (use {', '.join(MOEDAS_META)})")
        m.moeda = moeda
    if "data_alvo" in dados:
        if dados["data_alvo"]:
            try:
                m.data_alvo = datetime.strptime(dados["data_alvo"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "data_alvo inválida (use YYYY-MM-DD)")
        else:
            m.data_alvo = None
    if "escopo" in dados:
        novo_escopo = dados["escopo"]
        if novo_escopo not in ("patrimonio_total", "tipos_ativo", "ativos", "manual"):
            raise HTTPException(400, "escopo inválido")
        m.escopo = novo_escopo
    if "escopo_tipos" in dados:
        tipos = dados["escopo_tipos"] or []
        if not isinstance(tipos, list):
            raise HTTPException(400, "escopo_tipos precisa ser lista")
        invalidos = [t for t in tipos if t not in TIPOS_ATIVO]
        if invalidos:
            raise HTTPException(400, f"tipos inválidos: {invalidos}")
        m.escopo_tipos = _json.dumps(tipos)
    if "escopo_ativos" in dados:
        lista = dados["escopo_ativos"] or []
        # Lista vazia = limpar (meta deixou de ser escopo=ativos). Só valida
        # quando há ids de fato.
        m.escopo_ativos = _json.dumps(_validar_escopo_ativos(db, lista)) if lista else None
    if "escopo_excluir_ativos" in dados:
        ex = _parse_ids(dados["escopo_excluir_ativos"])
        m.escopo_excluir_ativos = _json.dumps(ex) if ex else None
    if "objetivo" in dados:
        m.objetivo = "aquisicao" if dados["objetivo"] == "aquisicao" else "patrimonio"
    if "valor_atual_manual" in dados:
        try:
            m.valor_atual_manual = float(dados["valor_atual_manual"])
        except (TypeError, ValueError):
            raise HTTPException(400, "valor_atual_manual inválido")
    if "taxa_retorno_anual" in dados:
        m.taxa_retorno_anual = _parse_float_ou_none(dados["taxa_retorno_anual"])
    if "meta_pai_id" in dados:
        novo_pai = dados["meta_pai_id"] or None
        if novo_pai:
            if novo_pai == m.id:
                raise HTTPException(400, "Meta não pode ser pai de si mesma")
            pai = db.query(Meta).filter(Meta.id == novo_pai).first()
            if not pai:
                raise HTTPException(400, "meta_pai_id não existe")
            # evita ciclos
            atual = pai
            while atual:
                if atual.id == m.id:
                    raise HTTPException(400, "Hierarquia inválida (ciclo)")
                atual = atual.meta_pai
        m.meta_pai_id = novo_pai
    if "ordem" in dados:
        m.ordem = int(dados["ordem"] or 0)
    if "cor" in dados:
        m.cor = (dados.get("cor") or "").strip() or None
    if "ativa" in dados:
        m.ativa = bool(dados["ativa"])

    db.commit()
    db.refresh(m)
    return _serializar_meta(m, _calcular_saldos_brl(db))


@router.delete("/api/metas/{meta_id}")
def deletar_meta(meta_id: int, db: Session = Depends(get_db)):
    m = db.query(Meta).filter(Meta.id == meta_id).first()
    if not m:
        raise HTTPException(404, "Meta não encontrada")
    # Sub-metas órfãs sobem um nível (passam a apontar pro avô).
    avo = m.meta_pai_id
    for sub in db.query(Meta).filter(Meta.meta_pai_id == m.id).all():
        sub.meta_pai_id = avo
    db.delete(m)
    db.commit()
    return {"ok": True}

