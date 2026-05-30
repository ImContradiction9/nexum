"""
Engine de conciliação. Encontra vínculos entre transações:

1. PAGAMENTO DE FATURA
   No extrato aparece "Pagamento Bradescard - R$ 3.119,58" em 15/04/2026.
   Existe uma fatura Bradesco importada com vencimento 15/04 e total R$ 3.119,58.
   Conciliação: marcar a transação do extrato como pagamento_de_fatura_id.

2. DUPLICATA
   Mesma compra aparece em duas fontes (ex.: extrato e fatura). Detecta por:
   mesma data, mesmo valor (±0,01), descrições parecidas.

3. TRANSFERÊNCIA ENTRE CONTAS
   Saída em uma conta sua e entrada do mesmo valor em outra (Pix entre suas contas).
   Por enquanto não implementado — colocar na Fase 2.

Cada match recebe um SCORE de confiança (0-1):
  - 1.0  = certeza absoluta (mesmo valor, mesma data, descrição inequívoca)
  - 0.7+ = sugestão forte (apresenta para usuário confirmar)
  - <0.7 = sugestão fraca (não cria conciliação automática, só reporta)

A conciliação automática só vira "confirmada" se o score for muito alto. Senão
fica como sugestão na UI para o usuário aprovar.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from .database import Transacao, Fatura, Conciliacao, Conta
from .utils import normalizar_descricao


# Palavras que indicam que uma transação no extrato é PAGAMENTO de fatura
PALAVRAS_PAGAMENTO_FATURA = [
    "pagamento de fatura", "pgto fatura", "pgto. fatura",
    "pagto fatura", "fatura cartao", "fatura cartão",
    "bradescard", "pgto cartao", "pagto cartão",
    "pagamento cartao credito", "pagto cc",
]


@dataclass
class SugestaoConciliacao:
    transacao_id: int
    fatura_id: Optional[int] = None
    transacao_b_id: Optional[int] = None
    tipo: str = ""
    confianca: float = 0.0
    motivo: str = ""


def _eh_provavel_pagamento_fatura(desc: str) -> bool:
    desc_lower = (desc or "").lower()
    return any(p in desc_lower for p in PALAVRAS_PAGAMENTO_FATURA)


def detectar_pagamentos_fatura(session: Session) -> list[SugestaoConciliacao]:
    """
    Para cada transação do extrato (sem fatura_id) que parece pagamento,
    procura uma fatura cujo valor + data baterem.

    Tolerância padrão:
      - data: ±5 dias do vencimento
      - valor: ±0,01 (centavos)
    """
    sugestoes = []

    # Transações candidatas: tipo Despesa, sem fatura_id (não são da própria fatura),
    # ainda não conciliadas, descrição com palavra-chave de pagamento
    candidatas = session.query(Transacao).filter(
        Transacao.fatura_id.is_(None),
        Transacao.pagamento_de_fatura_id.is_(None),
        Transacao.tipo == "Despesa",
    ).all()

    for t in candidatas:
        if not _eh_provavel_pagamento_fatura(t.descricao):
            continue

        # Procura faturas com valor próximo + vencimento próximo
        faturas = session.query(Fatura).filter(
            Fatura.total.isnot(None),
        ).all()

        melhor: Optional[tuple[Fatura, float]] = None
        for f in faturas:
            if f.total is None:
                continue
            diff_valor = abs(f.total - t.valor)
            if diff_valor > 0.01:
                continue
            if not f.data_vencimento:
                # se não tem vencimento, aceita só se for o mesmo banco
                continue
            diff_dias = abs((t.data - f.data_vencimento).days)
            if diff_dias > 5:
                continue
            # Score combinado
            score = 1.0 - (diff_dias / 5) * 0.3 - (diff_valor / 1.0) * 0.1
            if melhor is None or score > melhor[1]:
                melhor = (f, score)

        if melhor:
            f, score = melhor
            sugestoes.append(SugestaoConciliacao(
                transacao_id=t.id,
                fatura_id=f.id,
                tipo="pagamento_fatura",
                confianca=score,
                motivo=(
                    f"Transação '{t.descricao[:40]}' de {t.data.strftime('%d/%m/%Y')} "
                    f"R$ {t.valor:.2f} bate com fatura {f.banco} venc. "
                    f"{f.data_vencimento.strftime('%d/%m/%Y')}"
                ),
            ))

    return sugestoes


def detectar_duplicatas(session: Session) -> list[SugestaoConciliacao]:
    """
    Detecta transações que parecem ser a mesma compra importada de fontes
    diferentes. Critério:
      - Mesmo valor (±0.01)
      - Datas próximas (±2 dias) — pois compra Pix pode aparecer dia útil seguinte
      - Mesma conta OU contas relacionadas (mesma instituição)
      - Descrições similares
    """
    sugestoes = []

    # Agrupa por valor — só compara transações de mesmo valor
    todas = session.query(Transacao).filter(
        Transacao.duplicata_de_id.is_(None),
        Transacao.tipo == "Despesa",
    ).order_by(Transacao.valor, Transacao.data).all()

    por_valor: dict[float, list[Transacao]] = {}
    for t in todas:
        key = round(t.valor, 2)
        por_valor.setdefault(key, []).append(t)

    for valor, trans_list in por_valor.items():
        if len(trans_list) < 2:
            continue
        # compara cada par
        for i in range(len(trans_list)):
            for j in range(i + 1, len(trans_list)):
                a, b = trans_list[i], trans_list[j]
                # mesma transação — pula
                if a.id == b.id:
                    continue
                # já conciliadas — pula
                if a.duplicata_de_id or b.duplicata_de_id:
                    continue
                # data próxima
                diff_dias = abs((a.data - b.data).days)
                if diff_dias > 2:
                    continue
                # descrição similar
                desc_a = normalizar_descricao(a.descricao)
                desc_b = normalizar_descricao(b.descricao)
                if not desc_a or not desc_b:
                    continue
                # similaridade simples: tokens em comum
                tokens_a = set(desc_a.split())
                tokens_b = set(desc_b.split())
                if not tokens_a or not tokens_b:
                    continue
                similarity = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
                if similarity < 0.5:
                    continue

                score = (1 - diff_dias / 2 * 0.3) * similarity
                sugestoes.append(SugestaoConciliacao(
                    transacao_id=a.id,
                    transacao_b_id=b.id,
                    tipo="duplicata",
                    confianca=score,
                    motivo=(
                        f"R$ {valor:.2f} aparece em "
                        f"{a.data.strftime('%d/%m')} ('{a.descricao[:25]}') e "
                        f"{b.data.strftime('%d/%m')} ('{b.descricao[:25]}')"
                    ),
                ))

    return sugestoes


def aplicar_conciliacao(
    session: Session,
    sugestao: SugestaoConciliacao,
    confirmar: bool = False,
):
    """
    Aplica uma sugestão de conciliação ao banco.
    Se confirmar=True, marca a relação direta na Transacao (pagamento_de_fatura_id
    ou duplicata_de_id). Caso contrário, só cria registro em Conciliacao.
    """
    conc = Conciliacao(
        tipo=sugestao.tipo,
        transacao_a_id=sugestao.transacao_id,
        transacao_b_id=sugestao.transacao_b_id,
        fatura_id=sugestao.fatura_id,
        confianca=sugestao.confianca,
        confirmada=confirmar,
        observacao=sugestao.motivo,
    )
    session.add(conc)

    if confirmar:
        t_a = session.query(Transacao).get(sugestao.transacao_id)
        if sugestao.tipo == "pagamento_fatura" and sugestao.fatura_id:
            t_a.pagamento_de_fatura_id = sugestao.fatura_id
            t_a.conciliada = True
        elif sugestao.tipo == "duplicata" and sugestao.transacao_b_id:
            # Marca a SEGUNDA como duplicata da primeira
            t_b = session.query(Transacao).get(sugestao.transacao_b_id)
            t_b.duplicata_de_id = t_a.id
            t_b.conciliada = True
            t_a.conciliada = True

    session.flush()
    return conc
