"""Extrato de conta: saldo corrido por período e listagem de contas com extrato.
Extraído de main.py."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Conta, Fatura, Transacao

router = APIRouter()


@router.get("/api/extrato")
def extrato_conta(
    conta_id: int,
    mes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Retorna o extrato de uma conta corrente — todas as movimentações
    em ordem cronológica com saldo acumulado linha por linha.

    Se mes for passado, filtra ao período. Saldo inicial vem da Fatura/Extrato
    daquele mês importado. Caso contrário, calcula saldo "relativo" começando
    do zero do dia mais antigo.
    """
    conta = db.query(Conta).get(conta_id)
    if not conta:
        raise HTTPException(404, "Conta não encontrada")

    # Pega transações ordenadas
    q = db.query(Transacao).options(
        joinedload(Transacao.categoria),
        joinedload(Transacao.atribuicao),
    ).filter(Transacao.conta_id == conta_id)

    if mes:
        q = q.filter(Transacao.mes_referencia == mes)

    # Ordem cronológica (mais antigo primeiro)
    transacoes = q.order_by(Transacao.data.asc(), Transacao.id.asc()).all()

    # === Decide saldo inicial seguindo essa cascata ===
    # 1. Se mês selecionado tem extrato OFX importado, usa saldo_inicial dele (preciso)
    # 2. Senão, se a conta tem saldo manual cadastrado, calcula a partir dele:
    #    saldo_no_inicio_do_periodo = saldo_manual + soma de todas transações
    #    entre data_saldo_manual e início do período
    # 3. Senão, começa em zero (modo "relativo")
    saldo_inicial = None
    saldo_final_esperado = None
    fonte_saldo = "calculado"

    # 1. Tenta OFX do mês
    if mes and transacoes:
        fatura = db.query(Fatura).filter(
            Fatura.conta_id == conta_id,
            Fatura.mes_referencia == mes,
        ).first()
        if fatura and fatura.saldo_inicial is not None:
            saldo_inicial = fatura.saldo_inicial
            saldo_final_esperado = fatura.saldo_final
            fonte_saldo = "ofx"

    # 2. Saldo manual (se ainda não encontrou e há saldo cadastrado)
    if saldo_inicial is None and conta.saldo_inicial_manual is not None and conta.saldo_inicial_data:
        # Pega todas transações entre data do saldo manual e início do período visível
        # (exclusive: a primeira transação visível ainda não foi aplicada)
        if transacoes:
            primeira_data = transacoes[0].data
            ajuste_q = db.query(Transacao).filter(
                Transacao.conta_id == conta_id,
                Transacao.data > conta.saldo_inicial_data,
                Transacao.data < primeira_data,
            ).all()
            ajuste_liquido = sum(
                (t.valor if t.tipo == "Receita" else -t.valor) for t in ajuste_q
            )
            saldo_inicial = conta.saldo_inicial_manual + ajuste_liquido
            fonte_saldo = "manual"
        else:
            # Sem transações: saldo é o próprio manual (mais recente é o vigente)
            saldo_inicial = conta.saldo_inicial_manual
            fonte_saldo = "manual"

    # 3. Fallback: assume conta iniciada em zero e ACUMULA todas as transações
    #    anteriores ao período visível. Dá continuidade real entre os meses
    #    (mês N abre onde o mês N-1 fechou), sem depender do LEDGERBAL do OFX
    #    — que em alguns bancos (Santander) é o saldo atual, não o do período.
    if saldo_inicial is None:
        if transacoes:
            primeira_data = transacoes[0].data
            anteriores = db.query(Transacao).filter(
                Transacao.conta_id == conta_id,
                Transacao.data < primeira_data,
            ).all()
            saldo_inicial = sum(
                (t.valor if t.tipo == "Receita" else -t.valor) for t in anteriores
            )
            fonte_saldo = "calculado"
        else:
            saldo_inicial = 0
            fonte_saldo = "zero"

    # Aplica saldo acumulado linha por linha
    items = []
    saldo = saldo_inicial
    for t in transacoes:
        delta = t.valor if t.tipo == "Receita" else -t.valor
        saldo += delta
        items.append({
            "id": t.id,
            "data": t.data.isoformat() if t.data else None,
            "descricao": t.descricao_personalizada or t.descricao,
            "descricao_original": t.descricao,
            "valor": t.valor,
            "tipo": t.tipo,
            "delta": delta,                           # com sinal: +/-
            "saldo_apos": saldo,                      # saldo depois desta transação
            "forma_pagamento": t.forma_pagamento,
            "categoria": t.categoria.nome if t.categoria else None,
            "categoria_icone": t.categoria.icone if t.categoria else None,
            "atribuicao": t.atribuicao.nome if t.atribuicao else None,
            "atribuicao_cor": t.atribuicao.cor if t.atribuicao else None,
            "movimentacao": t.movimentacao,
        })

    # Lista meses disponíveis pra essa conta (ordem cronológica)
    def _mes_chave(s: str) -> tuple:
        try:
            mm, yyyy = s.split("/")
            return (int(yyyy), int(mm))
        except (ValueError, AttributeError):
            return (0, 0)
    meses_raw = [r[0] for r in db.query(Transacao.mes_referencia).filter(
        Transacao.conta_id == conta_id
    ).distinct().all() if r[0]]
    meses_disp = sorted(meses_raw, key=_mes_chave, reverse=True)

    # Saldo final calculado
    saldo_final_calculado = saldo

    # Valida: saldo final calculado deve bater com o do OFX (tolerância de 1 centavo)
    saldo_bate = None
    if saldo_final_esperado is not None:
        saldo_bate = abs(saldo_final_calculado - saldo_final_esperado) < 0.01

    return {
        "conta": {
            "id": conta.id,
            "nome": conta.nome,
            "banco": conta.banco_obj.nome if conta.banco_obj else conta.banco,
            "tipo": conta.tipo,
            "titular": conta.titular,
            "saldo_inicial_manual": conta.saldo_inicial_manual,
            "saldo_inicial_data": conta.saldo_inicial_data.isoformat() if conta.saldo_inicial_data else None,
        },
        "mes": mes,
        "meses_disponiveis": meses_disp,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final_calculado,
        "saldo_final_ofx": saldo_final_esperado,
        "saldo_bate": saldo_bate,
        "fonte_saldo": fonte_saldo,         # "ofx" | "zero" | "calculado"
        "n_transacoes": len(items),
        "items": items,
    }


@router.get("/api/extrato/contas")
def listar_contas_extrato(db: Session = Depends(get_db)):
    """
    Lista contas corrente disponíveis pro extrato (que tenham transações).
    """
    contas = db.query(Conta).options(joinedload(Conta.banco_obj)).filter(
        Conta.tipo == "Conta Corrente",
        Conta.ativo == True,
    ).all()
    # Pega só as que têm pelo menos uma transação
    out = []
    for c in contas:
        n = db.query(Transacao).filter(Transacao.conta_id == c.id).count()
        if n > 0:
            out.append({
                "id": c.id,
                "nome": c.nome,
                "banco": c.banco_obj.nome if c.banco_obj else c.banco,
                "banco_cor": c.banco_obj.cor if c.banco_obj else None,
                "titular": c.titular,
                "n_transacoes": n,
            })
    out.sort(key=lambda c: (c["banco"] or "", c["titular"] or "", c["nome"]))
    return out
