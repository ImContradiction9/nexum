"""Investimentos: carteira, ativos, operações e rendimento via CDI.

Extraído de main.py (refactor por domínio). Os helpers aqui (TIPOS_ATIVO,
_serializar_ativo, _cdi_serie, _parse_date, _parse_float_ou_none, etc.) são
reutilizados pelo router de metas.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Ativo, OperacaoInvestimento, CDIDiario, Configuracao
from .. import cdi as cdi_mod
from .. import impostos
from .. import cambio as cambio_mod

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


def _serializar_ativo(a: Ativo, ops: list = None, cdi_serie: dict = None) -> dict:
    """Serializa um ativo com posição calculada a partir das operações.

    Se `cdi_serie` for fornecida e o ativo for renda fixa com `cdi_percentual`
    (e sem saldo manual), o saldo é acumulado dia a dia pela série CDI."""
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

    # Saldo atual, por ordem de prioridade:
    #   1) saldo manual informado pelo usuário
    #   2) auto-cálculo via CDI (renda fixa indexada, com cdi_percentual)
    #   3) soma das operações
    cdi_auto = False
    if a.saldo_atual:
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

    return {
        "id": a.id,
        "nome": a.nome,
        "ticker": a.ticker,
        "tipo": a.tipo,
        "moeda": a.moeda,
        "instituicao": a.instituicao,
        "detalhes_taxa": a.detalhes_taxa,
        "saldo_atual": saldo_atual,
        "saldo_atualizado_em": a.saldo_atualizado_em.isoformat() if a.saldo_atualizado_em else None,
        "saldo_manual": bool(a.saldo_atual),
        "valor_investido_moeda": valor_investido_moeda,
        "valor_investido_brl": valor_investido_brl,
        "qtd_total": qtd_total,
        "rendimentos_recebidos": rendimentos_recebidos,
        "rentab_moeda": rentab_moeda,
        "rentab_pct": rentab_pct,
        "data_vencimento": a.data_vencimento.isoformat() if a.data_vencimento else None,
        "ativo": a.ativo,
        "n_operacoes": len(ops),
        "observacoes": a.observacoes,
        "rendimento_incorpora_saldo": incorpora,
        "cdi_percentual": a.cdi_percentual,
        "cdi_auto": cdi_auto,
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
    return [_serializar_ativo(a, por_ativo.get(a.id, []), serie) for a in ativos]


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
    por_tipo = {}

    serie = _cdi_serie(db)
    # Cotação ATUAL das moedas estrangeiras (BCB/manual, lazy). Assim o "valor
    # atual" em R$ reflete o dólar de hoje, não o da compra.
    try:
        cambio_mod.sincronizar(db)
    except Exception:
        pass
    for a in ativos:
        ser = _serializar_ativo(a, por_ativo.get(a.id, []), serie)
        ops = por_ativo.get(a.id, [])

        # Câmbio da compra (custo) — usado no "investido" e como fallback.
        cambio_compra = 1
        if a.moeda != "BRL" and ops:
            for op in sorted(ops, key=lambda x: x.data, reverse=True):
                if op.cotacao_cambio:
                    cambio_compra = op.cotacao_cambio
                    break

        invest_brl = ser["valor_investido_brl"]
        if a.moeda != "BRL":
            # Valor atual converte pela cotação de HOJE (cai no câmbio da compra
            # se o BCB/manual não tiver taxa pra essa moeda).
            taxa_hoje = cambio_mod.taxa_atual(db, a.moeda) or cambio_compra
            atual_brl = ser["saldo_atual"] * taxa_hoje
        else:
            atual_brl = ser["saldo_atual"]

        # Posições fechadas (totalmente resgatadas) podem ter valor_investido
        # negativo — significa que o usuário sacou mais do que aportou nominal,
        # graças aos juros. Pra somar na carteira isso vira zero (a posição
        # não está mais "investida"), e o lucro realizado não é refletido aqui.
        invest_brl_carteira = max(invest_brl, 0)
        atual_brl_carteira = max(atual_brl, 0)

        total_investido_brl += invest_brl_carteira
        total_atual_brl += atual_brl_carteira

        if ser["tipo"] not in por_tipo:
            por_tipo[ser["tipo"]] = {"investido_brl": 0, "atual_brl": 0, "n": 0}
        por_tipo[ser["tipo"]]["investido_brl"] += invest_brl_carteira
        por_tipo[ser["tipo"]]["atual_brl"] += atual_brl_carteira
        por_tipo[ser["tipo"]]["n"] += 1

    rentab_brl = total_atual_brl - total_investido_brl
    rentab_pct = (rentab_brl / total_investido_brl * 100) if total_investido_brl > 0 else 0

    return {
        "total_investido_brl": total_investido_brl,
        "total_atual_brl": total_atual_brl,
        "rentab_brl": rentab_brl,
        "rentab_pct": rentab_pct,
        "por_tipo": [
            {"tipo": k, **v} for k, v in sorted(por_tipo.items(), key=lambda x: -x[1]["atual_brl"])
        ],
        "n_ativos": len(ativos),
    }
