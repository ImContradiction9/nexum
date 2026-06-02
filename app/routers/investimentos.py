"""Investimentos: carteira, ativos, operações e rendimento via CDI.

Extraído de main.py (refactor por domínio). Os helpers aqui (TIPOS_ATIVO,
_serializar_ativo, _cdi_serie, _parse_date, _parse_float_ou_none, etc.) são
reutilizados pelo router de metas.
"""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Ativo, OperacaoInvestimento, CDIDiario, Configuracao, PatrimonioSnapshot
from .. import cdi as cdi_mod
from .. import impostos
from .. import cambio as cambio_mod
from .. import cotacoes as cotacoes_mod

router = APIRouter()


# ============================================================
# INVESTIMENTOS
# ============================================================

TIPOS_ATIVO = [
    "Tesouro Direto", "CDB", "RDB", "LCI", "LCA", "Fundo DI",
    "Ação BR", "FII", "ETF Nacional",
    "ETF Internacional", "Ação Internacional",
    "Cripto", "Outros",
]

# Em renda fixa o rendimento se incorpora ao saldo do título (juros acumulam
# até o resgate). Em renda variável, o "Rendimento" representa dividendo/JCP
# que cai na conta corrente — não faz parte do saldo do ativo.
TIPOS_RENDA_FIXA = {"Tesouro Direto", "CDB", "RDB", "LCI", "LCA", "Fundo DI"}

MOEDAS = ["BRL", "USD", "EUR", "GBP"]


def _prazo_medio_dias(ops: list) -> int:
    """
    Prazo decorrido (em dias) estimado da posição: média dos aportes
    (Compra/Aporte) ponderada pelo valor, medida até hoje. Usado para estimar
    a alíquota de IR/IOF do título. 0 se não há aportes.
    """
    hoje = date.today()
    total = 0.0
    soma_ponderada = 0.0
    for op in ops:
        if op.tipo in ("Compra", "Aporte") and op.data:
            v = (op.valor_total or 0) + (op.taxas or 0)
            if v > 0:
                total += v
                soma_ponderada += v * (hoje - op.data).days
    return int(round(soma_ponderada / total)) if total > 0 else 0


def _liquido_renda_fixa_cdi(ops: list, serie: dict, percentual: float,
                            tipo: str, saldo_atual: float) -> dict:
    """Líquido (IR + IOF) de renda fixa CDI-auto, calculado POR APORTE (tranche).

    Cada aporte rende desde a SUA data e sofre IOF/IR pela SUA idade. A tabela
    de IOF é muito não-linear nos primeiros 30 dias, então usar um único prazo
    médio para a posição inteira superestima o imposto (aportes antigos pagam
    IOF como se fossem recentes). Aqui cada tranche é tributada isoladamente e
    os impostos são somados — o que bate com o valor líquido real do banco.

    Resgates reduzem o imposto proporcionalmente (estimativa): o saldo bruto da
    posição (já líquido de resgates) é dividido pela soma dos brutos por tranche.
    """
    hoje = date.today()
    aportes = [(op.data, (op.valor_total or 0) + (op.taxas or 0))
               for op in ops if op.tipo in ("Compra", "Aporte") and op.data]

    soma_bruto = soma_iof = soma_ir = 0.0
    soma_rend = 0.0
    iof_aliq_pond = ir_aliq_pond = 0.0  # média ponderada pelo rendimento (p/ exibir)
    for d, v in aportes:
        if v <= 0:
            continue
        s = cdi_mod.saldo_composto([(d, v)], serie, percentual)
        r = s - v
        dias = (hoje - d).days
        L = impostos.calcular_liquido(s, r, dias, tipo)
        soma_bruto += s
        soma_iof += L["iof_valor"]
        soma_ir += L["ir_valor"]
        if r > 0:
            soma_rend += r
            iof_aliq_pond += L["iof_aliquota"] * r
            ir_aliq_pond += L["ir_aliquota"] * r

    # Resgates: o saldo bruto real (com resgates) é menor que a soma dos brutos
    # por tranche. Escala os impostos na mesma proporção.
    if soma_bruto > 0 and saldo_atual < soma_bruto:
        f = saldo_atual / soma_bruto
        soma_iof *= f
        soma_ir *= f

    saldo_liquido = max(saldo_atual - soma_iof - soma_ir, 0.0)
    iof_aliq = (iof_aliq_pond / soma_rend) if soma_rend > 0 else 0.0
    ir_aliq = (ir_aliq_pond / soma_rend) if soma_rend > 0 else 0.0
    return {
        "saldo_liquido": round(saldo_liquido, 2),
        "ir_valor": round(soma_ir, 2),
        "iof_valor": round(soma_iof, 2),
        "ir_aliquota": ir_aliq,
        "iof_aliquota": iof_aliq,
        "isento_ir": impostos.isento_ir(tipo or ""),
    }


def _rendimento_incorpora(a: Ativo) -> bool:
    """
    Define se 'Rendimento' deste ativo incorpora ao saldo (juros do título)
    ou sai como dividendo/JCP. Usa o override por ativo se setado; caso
    contrário, infere pelo tipo (renda fixa → incorpora).
    """
    if a.rendimento_incorpora_saldo is not None:
        return bool(a.rendimento_incorpora_saldo)
    return a.tipo in TIPOS_RENDA_FIXA


def _serializar_ativo(a: Ativo, ops: list = None, cdi_serie: dict = None,
                      taxa_cambio_atual: float = None, cotacoes: dict = None) -> dict:
    """Serializa um ativo com posição calculada a partir das operações.

    Se `cdi_serie` for fornecida e o ativo for renda fixa com `cdi_percentual`
    (e sem saldo manual), o saldo é acumulado dia a dia pela série CDI.

    `cotacoes` (cache do cotacoes.py): pra renda variável com ticker, a posição
    é qtd × cotação ao vivo (tem prioridade sobre o saldo manual), desde que a
    moeda da cotação bata com a do ativo.

    `taxa_cambio_atual` (moeda→BRL de hoje) converte a POSIÇÃO em reais; o
    INVESTIDO em reais usa o câmbio da compra (custo). Se não informada, a
    posição em R$ cai no câmbio da compra."""
    ops = ops or []

    incorpora = _rendimento_incorpora(a)

    # Totais brutos por tipo de operação (na moeda do ativo e em BRL).
    qtd_total = 0
    aportes_moeda = 0          # Compra + Aporte
    aportes_brl = 0
    resgates_moeda = 0         # Venda + Resgate
    resgates_brl = 0
    rendimentos_moeda = 0      # Rendimento
    rendimentos_brl = 0

    for op in ops:
        cambio = op.cotacao_cambio or 1
        valor_brl = op.valor_total * cambio
        if op.tipo in ("Compra", "Aporte"):
            if op.quantidade:
                qtd_total += op.quantidade
            taxas = op.taxas or 0
            aportes_moeda += op.valor_total + taxas
            aportes_brl += (op.valor_total + taxas) * cambio
        elif op.tipo in ("Venda", "Resgate"):
            if op.quantidade:
                qtd_total -= op.quantidade
            resgates_moeda += op.valor_total
            resgates_brl += valor_brl
        elif op.tipo == "Rendimento":
            rendimentos_moeda += op.valor_total
            rendimentos_brl += valor_brl

    # Saldo calculado a partir das operações.
    # Renda fixa: rendimentos incorporam ao saldo (juros do título).
    # Renda variável: rendimentos saem como dividendo/JCP — não contam.
    if incorpora:
        saldo_calculado = aportes_moeda - resgates_moeda + rendimentos_moeda
    else:
        saldo_calculado = aportes_moeda - resgates_moeda

    # Cotação ao vivo (renda variável com ticker): qtd × preço, se a moeda da
    # cotação bate com a do ativo.
    cdi_auto = False
    cotacao_auto = False
    cotacao_preco = None
    cotacao_em = None
    _q = cotacoes_mod.cotacao_de(cotacoes or {}, a.ticker) if a.ticker else None
    quote_ok = bool(
        _q and _q.get("preco") and _q.get("moeda") == a.moeda
        and a.tipo not in TIPOS_RENDA_FIXA and qtd_total > 0
    )

    # Saldo atual, por ordem de prioridade:
    #   1) cotação ao vivo (renda variável com ticker)
    #   2) saldo manual informado pelo usuário
    #   3) auto-cálculo via CDI (renda fixa indexada, com cdi_percentual)
    #   4) soma das operações
    if quote_ok:
        cotacao_preco = _q["preco"]
        cotacao_em = _q.get("em")
        saldo_atual = qtd_total * cotacao_preco
        cotacao_auto = True
    elif a.saldo_atual:
        saldo_atual = a.saldo_atual
    elif (cdi_serie and a.cdi_percentual
          and a.tipo in TIPOS_RENDA_FIXA and ops):
        # Só usa CDI quando há série em cache (cdi_serie truthy). Offline/sem
        # dados → cai no saldo_calculado abaixo (evita números errados).
        flows = []
        for op in ops:
            if op.tipo in ("Compra", "Aporte"):
                flows.append((op.data, (op.valor_total or 0) + (op.taxas or 0)))
            elif op.tipo in ("Venda", "Resgate"):
                flows.append((op.data, -(op.valor_total or 0)))
        # Renda fixa nunca fica negativa (resgate total → ~0, sem resíduo).
        saldo_atual = max(cdi_mod.saldo_composto(flows, cdi_serie, a.cdi_percentual), 0.0)
        cdi_auto = True
    else:
        saldo_atual = saldo_calculado

    # Título ENCERRADO: se houve um resgate marcado como "total" e nenhum aporte
    # depois dele, o saldo é 0. O usuário registrou o líquido recebido; o resíduo
    # bruto (IR/IOF retido pelo banco) vira custo realizado, não fica sobrando.
    if not a.saldo_atual:
        resg_totais = [op for op in ops if op.tipo in ("Resgate", "Venda")
                       and getattr(op, "resgate_total", False) and op.data]
        if resg_totais:
            ult_resg_total = max(op.data for op in resg_totais)
            aportes_datas = [op.data for op in ops if op.tipo in ("Compra", "Aporte") and op.data]
            if not aportes_datas or max(aportes_datas) <= ult_resg_total:
                saldo_atual = 0.0
                cdi_auto = False

    # Limpa -0.00 e arredonda micro-resíduos de ponto flutuante.
    saldo_atual = round(saldo_atual, 8)
    if abs(saldo_atual) < 0.005:
        saldo_atual = 0.0

    # Total aplicado líquido (independe do tipo): aportes - resgates.
    valor_investido_moeda = aportes_moeda - resgates_moeda
    valor_investido_brl = aportes_brl - resgates_brl

    # Rentabilidade: ganho de capital + rendimentos.
    # Em renda fixa rendimentos já estão no saldo, não soma de novo.
    if incorpora:
        rentab_moeda = saldo_atual - valor_investido_moeda
    else:
        rentab_moeda = saldo_atual - valor_investido_moeda + rendimentos_moeda
    rentab_pct = (rentab_moeda / valor_investido_moeda * 100) if valor_investido_moeda > 0 else 0

    # Mantém compatibilidade com clientes antigos que usam o campo legado.
    rendimentos_recebidos = rendimentos_moeda

    # --- Saldo LÍQUIDO (estimado): só renda fixa, descontando IR + IOF do
    # rendimento. Renda variável e posições sem ganho não sofrem dedução aqui.
    eh_renda_fixa = a.tipo in TIPOS_RENDA_FIXA
    prazo_dias = _prazo_medio_dias(ops) if eh_renda_fixa else 0
    # Não tributa além do saldo atual: em posições quase zeradas (resgates >
    # aportes nominais), rentab_moeda pode superar o saldo e geraria líquido
    # negativo. Capa o rendimento tributável ao saldo.
    rend_tributavel = min(rentab_moeda, saldo_atual)
    if eh_renda_fixa and rend_tributavel > 0:
        if cdi_auto:
            # CDI-auto: tributa cada aporte pela própria idade (IOF é não-linear
            # nos 1ºs 30 dias; prazo médio único superestima o imposto).
            liq = _liquido_renda_fixa_cdi(ops, cdi_serie, a.cdi_percentual, a.tipo, saldo_atual)
        else:
            liq = impostos.calcular_liquido(saldo_atual, rend_tributavel, prazo_dias, a.tipo)
    else:
        liq = {
            "saldo_liquido": saldo_atual, "ir_valor": 0.0, "iof_valor": 0.0,
            "ir_aliquota": 0.0, "iof_aliquota": 0.0,
            "isento_ir": impostos.isento_ir(a.tipo),
        }
    saldo_liquido = liq["saldo_liquido"]
    rentab_liquida_moeda = saldo_liquido - valor_investido_moeda

    # --- Conversão para BRL (por ativo) e data de aquisição ---
    # Investido em R$ = custo (câmbio da compra, já em valor_investido_brl).
    # Posição em R$ = saldo atual × cotação de HOJE (taxa_cambio_atual); se não
    # houver cotação atual, cai no câmbio do aporte mais recente.
    datas_aporte = [op.data for op in ops if op.tipo in ("Compra", "Aporte") and op.data]
    data_aquisicao = min(datas_aporte).isoformat() if datas_aporte else None
    if a.moeda == "BRL":
        cambio_atual = 1.0
        saldo_atual_brl = saldo_atual
    else:
        cambio_compra = 1.0
        for op in sorted(ops, key=lambda x: (x.data or date.min), reverse=True):
            if op.cotacao_cambio:
                cambio_compra = op.cotacao_cambio
                break
        cambio_atual = taxa_cambio_atual or cambio_compra
        saldo_atual_brl = saldo_atual * cambio_atual
    # Rentabilidade em R$ (retorno total): ganho/perda de capital — já com a
    # variação cambial — MAIS os dividendos/rendimentos recebidos (em R$). Em
    # renda fixa os rendimentos já estão no saldo, então não soma de novo.
    if incorpora:
        rentab_brl = saldo_atual_brl - valor_investido_brl
    else:
        rentab_brl = saldo_atual_brl - valor_investido_brl + rendimentos_brl
    rentab_brl_pct = (rentab_brl / valor_investido_brl * 100) if valor_investido_brl > 0 else 0

    return {
        "id": a.id,
        "nome": a.nome,
        "ticker": a.ticker,
        "tipo": a.tipo,
        "objetivo": a.objetivo or "patrimonio",
        "moeda": a.moeda,
        "instituicao": a.instituicao,
        "detalhes_taxa": a.detalhes_taxa,
        "saldo_atual": saldo_atual,
        "saldo_atualizado_em": a.saldo_atualizado_em.isoformat() if a.saldo_atualizado_em else None,
        "saldo_manual": bool(a.saldo_atual),
        "valor_investido_moeda": valor_investido_moeda,
        "valor_investido_brl": valor_investido_brl,
        "saldo_atual_brl": saldo_atual_brl,
        "rentab_brl": rentab_brl,
        "rentab_brl_pct": rentab_brl_pct,
        "cambio_atual": cambio_atual,
        "data_aquisicao": data_aquisicao,
        "qtd_total": qtd_total,
        "rendimentos_recebidos": rendimentos_recebidos,
        "rendimentos_brl": rendimentos_brl,
        "rentab_moeda": rentab_moeda,
        "rentab_pct": rentab_pct,
        "data_vencimento": a.data_vencimento.isoformat() if a.data_vencimento else None,
        "ativo": a.ativo,
        "n_operacoes": len(ops),
        "observacoes": a.observacoes,
        "rendimento_incorpora_saldo": incorpora,
        "cdi_percentual": a.cdi_percentual,
        "cdi_auto": cdi_auto,
        "cotacao_auto": cotacao_auto,
        "cotacao_preco": cotacao_preco,
        "cotacao_em": cotacao_em,
        # Líquido estimado (IR + IOF) — só renda fixa; senão = bruto.
        "saldo_liquido": saldo_liquido,
        "rentab_liquida_moeda": rentab_liquida_moeda,
        "ir_valor": liq["ir_valor"],
        "iof_valor": liq["iof_valor"],
        "ir_aliquota": liq["ir_aliquota"],
        "iof_aliquota": liq["iof_aliquota"],
        "isento_ir": liq["isento_ir"],
        "prazo_dias": prazo_dias,
        "eh_renda_fixa": eh_renda_fixa,
    }


def _cdi_serie(db: Session) -> dict:
    """Sincroniza o cache CDI (lazy/tolerante a offline) e devolve {date: taxa}.

    A sincronização só vai à rede quando o cache está velho (>6h) ou vazio;
    fora isso usa o que já está no banco. Erros de rede são silenciosos."""
    primeira = db.query(func.min(OperacaoInvestimento.data)).scalar()
    try:
        cdi_mod.sincronizar(db, desde=primeira)
    except Exception:
        pass
    return cdi_mod.carregar_serie(db)


@router.get("/api/investimentos/tipos")
def listar_tipos_ativo():
    return {"tipos": TIPOS_ATIVO, "moedas": MOEDAS}


def _cdi_status_dict(db: Session) -> dict:
    ultima = db.query(func.max(CDIDiario.data)).scalar()
    n = db.query(func.count(CDIDiario.data)).scalar() or 0
    serie = cdi_mod.carregar_serie(db)
    cfg = db.query(Configuracao).filter(Configuracao.chave == "cdi_sync_em").first()
    return {
        "ultima_data": ultima.isoformat() if ultima else None,
        "n_dias": n,
        "cdi_anual": round(cdi_mod.cdi_anual(serie) * 100, 2) if serie else None,
        "sincronizado_em": cfg.valor if cfg else None,
    }


@router.get("/api/investimentos/cdi/status")
def cdi_status(db: Session = Depends(get_db)):
    """Estado do cache CDI: até quando está atualizado e o CDI anual atual."""
    return _cdi_status_dict(db)


@router.post("/api/investimentos/cdi/sincronizar")
def cdi_sincronizar(db: Session = Depends(get_db)):
    """Força a sincronização do cache CDI com o Banco Central."""
    primeira = db.query(func.min(OperacaoInvestimento.data)).scalar()
    res = cdi_mod.sincronizar(db, desde=primeira, forcar=True)
    res["status"] = _cdi_status_dict(db)
    return res


@router.get("/api/investimentos/cotacoes/status")
def cotacoes_status(db: Session = Depends(get_db)):
    return cotacoes_mod.status(db)


@router.post("/api/investimentos/cotacoes/sincronizar")
def cotacoes_sincronizar(db: Session = Depends(get_db)):
    """Busca a cotação ao vivo (Yahoo) dos ativos de renda variável com ticker."""
    ativos = db.query(Ativo).filter(
        Ativo.ativo == True, Ativo.ticker.isnot(None),
        ~Ativo.tipo.in_(list(TIPOS_RENDA_FIXA)),
    ).all()
    alvos = [(a.ticker, a.moeda) for a in ativos if (a.ticker or "").strip()]
    res = cotacoes_mod.sincronizar(db, alvos, forcar=True)
    res["status"] = cotacoes_mod.status(db)
    return res


@router.get("/api/investimentos/ativos")
def listar_ativos(incluir_inativos: bool = False, db: Session = Depends(get_db)):
    """Lista todos os ativos com posição calculada."""
    q = db.query(Ativo)
    if not incluir_inativos:
        q = q.filter(Ativo.ativo == True)
    ativos = q.order_by(Ativo.nome).all()

    # Pega operações de cada um (uma query só, mais eficiente)
    todas_ops = db.query(OperacaoInvestimento).filter(
        OperacaoInvestimento.ativo_id.in_([a.id for a in ativos])
    ).all()
    por_ativo = {}
    for op in todas_ops:
        por_ativo.setdefault(op.ativo_id, []).append(op)

    serie = _cdi_serie(db)
    # Cotação atual das moedas estrangeiras (BCB/manual, lazy) para a posição em R$.
    try:
        cambio_mod.sincronizar(db)
    except Exception:
        pass
    _taxas: dict = {}
    def _taxa(moeda):
        if moeda not in _taxas:
            _taxas[moeda] = cambio_mod.taxa_atual(db, moeda)
        return _taxas[moeda]
    # Cotações ao vivo (cache; a rede só roda no botão "Atualizar" pra não travar a tela).
    cot = cotacoes_mod.carregar_cache(db)
    return [_serializar_ativo(a, por_ativo.get(a.id, []), serie, _taxa(a.moeda), cot) for a in ativos]


@router.post("/api/investimentos/ativos")
def criar_ativo(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    a = Ativo(
        nome=nome,
        ticker=(dados.get("ticker") or "").strip() or None,
        tipo=dados.get("tipo", "Outros"),
        moeda=dados.get("moeda", "BRL"),
        instituicao=(dados.get("instituicao") or "").strip() or None,
        detalhes_taxa=(dados.get("detalhes_taxa") or "").strip() or None,
        observacoes=(dados.get("observacoes") or "").strip() or None,
        data_vencimento=_parse_date(dados.get("data_vencimento")),
        rendimento_incorpora_saldo=(
            bool(dados["rendimento_incorpora_saldo"])
            if "rendimento_incorpora_saldo" in dados and dados["rendimento_incorpora_saldo"] is not None
            else None
        ),
        cdi_percentual=_parse_float_ou_none(dados.get("cdi_percentual")),
        objetivo=("aquisicao" if dados.get("objetivo") == "aquisicao" else "patrimonio"),
    )
    db.add(a)
    db.commit()
    return _serializar_ativo(a, [], _cdi_serie(db))


@router.patch("/api/investimentos/ativos/{ativo_id}")
def atualizar_ativo(ativo_id: int, dados: dict, db: Session = Depends(get_db)):
    a = db.query(Ativo).get(ativo_id)
    if not a:
        raise HTTPException(404)

    for campo in ("nome", "ticker", "tipo", "moeda", "instituicao", "detalhes_taxa", "observacoes", "ativo"):
        if campo in dados:
            v = dados[campo]
            if isinstance(v, str):
                v = v.strip() or None
            setattr(a, campo, v)

    if "data_vencimento" in dados:
        a.data_vencimento = _parse_date(dados["data_vencimento"])

    if "rendimento_incorpora_saldo" in dados:
        v = dados["rendimento_incorpora_saldo"]
        a.rendimento_incorpora_saldo = None if v is None else bool(v)

    if "cdi_percentual" in dados:
        a.cdi_percentual = _parse_float_ou_none(dados["cdi_percentual"])
    if "objetivo" in dados:
        a.objetivo = "aquisicao" if dados["objetivo"] == "aquisicao" else "patrimonio"

    # Atualização manual de saldo
    if "saldo_atual" in dados:
        a.saldo_atual = float(dados["saldo_atual"]) if dados["saldo_atual"] else 0
        a.saldo_atualizado_em = datetime.now().date()

    db.commit()

    ops = db.query(OperacaoInvestimento).filter(
        OperacaoInvestimento.ativo_id == a.id
    ).all()
    return _serializar_ativo(a, ops, _cdi_serie(db))


@router.delete("/api/investimentos/ativos/{ativo_id}")
def excluir_ativo(ativo_id: int, db: Session = Depends(get_db)):
    a = db.query(Ativo).get(ativo_id)
    if not a:
        raise HTTPException(404)
    n_ops = db.query(OperacaoInvestimento).filter(
        OperacaoInvestimento.ativo_id == ativo_id
    ).count()
    if n_ops > 0:
        # Soft delete: marca como inativo em vez de apagar (preserva histórico)
        a.ativo = False
        db.commit()
        return {"ok": True, "soft_delete": True, "n_operacoes": n_ops}
    db.delete(a)
    db.commit()
    return {"ok": True, "soft_delete": False}


def _parse_date(s):
    if not s:
        return None
    if hasattr(s, "isoformat"):
        return s
    try:
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        return None


def _parse_float_ou_none(v):
    """Converte para float; '', None ou inválido viram None (não 0)."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


@router.get("/api/investimentos/operacoes")
def listar_operacoes(ativo_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Lista operações. Se ativo_id passado, filtra. Senão retorna todas."""
    q = db.query(OperacaoInvestimento).options(joinedload(OperacaoInvestimento.ativo_obj))
    if ativo_id:
        q = q.filter(OperacaoInvestimento.ativo_id == ativo_id)
    ops = q.order_by(OperacaoInvestimento.data.desc(), OperacaoInvestimento.id.desc()).all()
    return [{
        "id": op.id,
        "ativo_id": op.ativo_id,
        "ativo_nome": op.ativo_obj.nome if op.ativo_obj else None,
        "ativo_ticker": op.ativo_obj.ticker if op.ativo_obj else None,
        "ativo_moeda": op.ativo_obj.moeda if op.ativo_obj else "BRL",
        "tipo": op.tipo,
        "data": op.data.isoformat() if op.data else None,
        "quantidade": op.quantidade,
        "preco_unitario": op.preco_unitario,
        "valor_total": op.valor_total,
        "moeda_operacao": op.moeda_operacao,
        "cotacao_cambio": op.cotacao_cambio,
        "taxas": op.taxas,
        "resgate_total": bool(op.resgate_total),
        "valor_total_brl": op.valor_total * (op.cotacao_cambio or 1),
        "observacoes": op.observacoes,
    } for op in ops]


@router.post("/api/investimentos/operacoes")
def criar_operacao(dados: dict, db: Session = Depends(get_db)):
    ativo_id = dados.get("ativo_id")
    if not ativo_id:
        raise HTTPException(400, "ativo_id obrigatório")
    a = db.query(Ativo).get(ativo_id)
    if not a:
        raise HTTPException(404, "Ativo não encontrado")

    tipo = dados.get("tipo", "Compra")
    if tipo not in ("Compra", "Venda", "Aporte", "Resgate", "Rendimento"):
        raise HTTPException(400, f"Tipo inválido: {tipo}")

    data_op = _parse_date(dados.get("data"))
    if not data_op:
        raise HTTPException(400, "Data obrigatória (formato YYYY-MM-DD)")

    qtd = dados.get("quantidade")
    preco = dados.get("preco_unitario")
    valor_total = dados.get("valor_total")

    # Se forneceu qtd + preco, calcula valor_total. Se forneceu só valor_total, usa direto.
    if qtd and preco and not valor_total:
        valor_total = float(qtd) * float(preco)
    if not valor_total:
        raise HTTPException(400, "valor_total obrigatório (ou quantidade + preco_unitario)")

    op = OperacaoInvestimento(
        ativo_id=ativo_id,
        tipo=tipo,
        data=data_op,
        quantidade=float(qtd) if qtd else None,
        preco_unitario=float(preco) if preco else None,
        valor_total=float(valor_total),
        moeda_operacao=dados.get("moeda_operacao", a.moeda),
        cotacao_cambio=float(dados["cotacao_cambio"]) if dados.get("cotacao_cambio") else None,
        taxas=float(dados.get("taxas", 0)) or 0,
        resgate_total=(bool(dados.get("resgate_total")) if tipo in ("Resgate", "Venda") else False),
        observacoes=(dados.get("observacoes") or "").strip() or None,
    )
    db.add(op)
    db.commit()
    return {"id": op.id, "ok": True}


@router.delete("/api/investimentos/operacoes/{op_id}")
def excluir_operacao(op_id: int, db: Session = Depends(get_db)):
    op = db.query(OperacaoInvestimento).get(op_id)
    if not op:
        raise HTTPException(404)
    db.delete(op)
    db.commit()
    return {"ok": True}


@router.get("/api/investimentos/resumo")
def resumo_investimentos(db: Session = Depends(get_db)):
    """Resumo da carteira: total investido em BRL + breakdown por tipo."""
    ativos = db.query(Ativo).filter(Ativo.ativo == True).all()
    todas_ops = db.query(OperacaoInvestimento).all()
    por_ativo = {}
    for op in todas_ops:
        por_ativo.setdefault(op.ativo_id, []).append(op)

    total_investido_brl = 0
    total_atual_brl = 0
    total_rentab_brl = 0       # retorno TOTAL em R$ (capital + câmbio + dividendos)
    total_rendimentos_brl = 0  # só os proventos, p/ exibir "inclui R$ X em proventos"
    total_patrimonio_brl = 0   # só ativos objetivo="patrimonio" (p/ o gráfico)
    por_tipo = {}

    serie = _cdi_serie(db)
    # Cotação ATUAL das moedas estrangeiras (BCB/manual, lazy). Assim a posição
    # em R$ reflete o dólar de hoje, não o da compra.
    try:
        cambio_mod.sincronizar(db)
    except Exception:
        pass
    _taxas: dict = {}
    def _taxa(moeda):
        if moeda not in _taxas:
            _taxas[moeda] = cambio_mod.taxa_atual(db, moeda)
        return _taxas[moeda]
    cot = cotacoes_mod.carregar_cache(db)

    for a in ativos:
        ser = _serializar_ativo(a, por_ativo.get(a.id, []), serie, _taxa(a.moeda), cot)

        # Posições fechadas (resgatadas) podem ter investido negativo → 0 na
        # carteira. A rentabilidade usa o retorno do próprio ativo (já em R$,
        # já com câmbio e dividendos).
        invest_brl = max(ser["valor_investido_brl"], 0)
        atual_brl = max(ser["saldo_atual_brl"], 0)
        rentab_ativo_brl = ser["rentab_brl"]

        total_investido_brl += invest_brl
        total_atual_brl += atual_brl
        total_rentab_brl += rentab_ativo_brl
        total_rendimentos_brl += ser["rendimentos_brl"]
        if (a.objetivo or "patrimonio") == "patrimonio":
            total_patrimonio_brl += atual_brl

        if ser["tipo"] not in por_tipo:
            por_tipo[ser["tipo"]] = {"investido_brl": 0, "atual_brl": 0, "rentab_brl": 0, "n": 0}
        por_tipo[ser["tipo"]]["investido_brl"] += invest_brl
        por_tipo[ser["tipo"]]["atual_brl"] += atual_brl
        por_tipo[ser["tipo"]]["rentab_brl"] += rentab_ativo_brl
        por_tipo[ser["tipo"]]["n"] += 1

    rentab_brl = total_rentab_brl
    rentab_pct = (rentab_brl / total_investido_brl * 100) if total_investido_brl > 0 else 0

    # Foto de hoje pro gráfico de evolução (upsert por dia, best-effort).
    _registrar_snapshot(db, total_atual_brl, total_investido_brl, total_patrimonio_brl)

    return {
        "total_investido_brl": total_investido_brl,
        "total_atual_brl": total_atual_brl,
        "rentab_brl": rentab_brl,
        "rentab_pct": rentab_pct,
        "rendimentos_brl": total_rendimentos_brl,
        "por_tipo": [
            {"tipo": k, **v} for k, v in sorted(por_tipo.items(), key=lambda x: -x[1]["atual_brl"])
        ],
        "n_ativos": len(ativos),
    }


def _registrar_snapshot(db: Session, total_brl: float, investido_brl: float,
                        patrimonio_brl: float = None):
    """Upsert da foto de patrimônio de HOJE (best-effort, tolerante a corrida)."""
    try:
        hoje = date.today()
        pat = round(patrimonio_brl, 2) if patrimonio_brl is not None else None
        snap = db.query(PatrimonioSnapshot).filter(PatrimonioSnapshot.data == hoje).first()
        if snap:
            snap.total_brl = round(total_brl, 2)
            snap.investido_brl = round(investido_brl, 2)
            snap.patrimonio_brl = pat
        else:
            db.add(PatrimonioSnapshot(data=hoje, total_brl=round(total_brl, 2),
                                      investido_brl=round(investido_brl, 2), patrimonio_brl=pat))
        db.commit()
    except Exception:
        db.rollback()


def _intervalo_meses(ini: str, fim: str):
    """Lista 'YYYY-MM' de ini até fim (inclusive)."""
    yi, mi = map(int, ini.split("-"))
    yf, mf = map(int, fim.split("-"))
    out = []
    y, m = yi, mi
    while (y, m) <= (yf, mf):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _alocacao_alvo(db: Session) -> dict:
    c = db.query(Configuracao).filter(Configuracao.chave == "alocacao_alvo").first()
    try:
        return json.loads(c.valor) if (c and c.valor) else {}
    except (ValueError, TypeError):
        return {}


@router.get("/api/investimentos/alocacao")
def alocacao(db: Session = Depends(get_db)):
    """Alocação atual por classe (% da carteira) + alvo + quanto APORTAR (só
    compra) pra chegar no alvo. Rebalanceamento por aporte: nunca sugere vender.

    Em vez de comparar com o total atual (o que pediria venda das classes acima
    do alvo), escalamos o total pra cima até a classe mais sobre-alocada bater no
    alvo. Assim toda classe só recebe aporte ≥ 0.
    """
    res = resumo_investimentos(db)
    total = res["total_atual_brl"] or 0
    alvo = _alocacao_alvo(db)
    atual_por_tipo = {t["tipo"]: t["atual_brl"] for t in res["por_tipo"]}
    tipos = set(atual_por_tipo) | set(alvo)

    # Percentuais-alvo válidos por tipo.
    pct_alvo_por_tipo = {}
    for t in tipos:
        pa = alvo.get(t)
        try:
            pv = float(pa) if pa is not None else None
        except (TypeError, ValueError):
            pv = None
        pct_alvo_por_tipo[t] = pv

    # Total mínimo da carteira (após aporte) em que nenhuma classe precisa vender:
    # para cada classe com alvo>0, total >= atual / (alvo/100). Pega o maior.
    total_alvo = total
    for t, pv in pct_alvo_por_tipo.items():
        if pv and pv > 0:
            necessario = atual_por_tipo.get(t, 0.0) * 100.0 / pv
            if necessario > total_alvo:
                total_alvo = necessario

    linhas = []
    for t in tipos:
        atual_brl = atual_por_tipo.get(t, 0.0)
        pct_atual = (atual_brl / total * 100) if total else 0
        pct_alvo = pct_alvo_por_tipo.get(t)
        if pct_alvo is not None:
            destino_brl = total_alvo * pct_alvo / 100
            aporte = max(destino_brl - atual_brl, 0.0)   # só compra, nunca vende
        else:
            aporte = None
        linhas.append({
            "tipo": t, "atual_brl": round(atual_brl, 2), "pct_atual": round(pct_atual, 1),
            "pct_alvo": pct_alvo,
            "aporte_brl": round(aporte, 2) if aporte is not None else None,
            # Compat: delta agora é sempre o aporte (≥0); clientes antigos não veem venda.
            "delta_brl": round(aporte, 2) if aporte is not None else None,
        })
    linhas.sort(key=lambda x: -x["atual_brl"])
    aporte_total = sum(l["aporte_brl"] for l in linhas if l["aporte_brl"])
    return {
        "total_brl": round(total, 2), "linhas": linhas, "tem_alvo": bool(alvo),
        "aporte_total_brl": round(aporte_total, 2),
        "soma_alvo": round(sum(float(v) for v in alvo.values()), 1) if alvo else 0,
    }


@router.post("/api/investimentos/alocacao/alvo")
def salvar_alocacao_alvo(dados: dict, db: Session = Depends(get_db)):
    """Define o alvo de alocação {tipo: percentual}. Percentuais <=0 ou inválidos
    são descartados (limpa o tipo)."""
    bruto = dados.get("alvo") or {}
    limpo = {}
    for t, v in bruto.items():
        try:
            pv = float(v)
        except (TypeError, ValueError):
            continue
        if pv > 0:
            limpo[t] = round(pv, 2)
    c = db.query(Configuracao).filter(Configuracao.chave == "alocacao_alvo").first()
    if not c:
        c = Configuracao(chave="alocacao_alvo", valor="")
        db.add(c)
    c.valor = json.dumps(limpo)
    db.commit()
    return alocacao(db)


@router.get("/api/investimentos/evolucao")
def evolucao_patrimonio(db: Session = Depends(get_db)):
    """Série mensal: 'investido' (custo acumulado, reconstruído das operações,
    histórico completo) + 'patrimonio' (snapshots; preenche de quando começou a
    gravar). Só considera ativos com objetivo='patrimonio' (exclui reservas de
    aquisição de bens, ex: carro/casa)."""
    # Objetivo por ativo: só 'patrimonio' entra no gráfico.
    objetivo_por_ativo = {a.id: (a.objetivo or "patrimonio")
                          for a in db.query(Ativo.id, Ativo.objetivo).all()}
    ops = db.query(OperacaoInvestimento).order_by(OperacaoInvestimento.data).all()
    delta_mes = {}
    for op in ops:
        if not op.data:
            continue
        if objetivo_por_ativo.get(op.ativo_id, "patrimonio") != "patrimonio":
            continue
        if op.tipo in ("Compra", "Aporte"):
            sinal = 1
        elif op.tipo in ("Venda", "Resgate"):
            sinal = -1
        else:
            continue
        v = (op.valor_total or 0) * (op.cotacao_cambio or 1)
        mes = op.data.strftime("%Y-%m")
        delta_mes[mes] = delta_mes.get(mes, 0.0) + sinal * v

    snaps = db.query(PatrimonioSnapshot).order_by(PatrimonioSnapshot.data).all()
    # patrimonio_brl (objetivo=patrimonio); snapshots antigos sem a coluna caem no total_brl.
    patr_mes = {s.data.strftime("%Y-%m"): (s.patrimonio_brl if s.patrimonio_brl is not None else s.total_brl)
                for s in snaps}

    if not delta_mes and not patr_mes:
        return {"serie": []}

    todos = sorted(set(delta_mes) | set(patr_mes))
    meses = _intervalo_meses(todos[0], max(date.today().strftime("%Y-%m"), todos[-1]))

    serie = []
    acc = 0.0
    for m in meses:
        acc += delta_mes.get(m, 0.0)
        serie.append({
            "mes": m,
            "investido": round(max(acc, 0.0), 2),
            "patrimonio": round(patr_mes[m], 2) if m in patr_mes else None,
        })
    return {"serie": serie}
