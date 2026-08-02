"""Faturas/extratos importados: listagem, mapa de cobertura, exclusão.
Extraído de main.py."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Fatura, Conta, Transacao
from ..conciliacao import recalcular_data_pagamento

router = APIRouter()


def _pagamento_efetivo(db: Session, f: Fatura) -> tuple:
    """(data_iso, origem) da data de pagamento efetiva da fatura.
    origem: 'manual' | 'vinculada' | 'vencimento' | None."""
    if f.data_pagamento_manual:
        return f.data_pagamento_manual.isoformat(), "manual"
    pago = db.query(func.min(Transacao.data)).filter(
        Transacao.pagamento_de_fatura_id == f.id
    ).scalar()
    if pago:
        return pago.isoformat(), "vinculada"
    if f.data_vencimento:
        return f.data_vencimento.isoformat(), "vencimento"
    return None, None


@router.get("/api/faturas")
def listar_faturas(db: Session = Depends(get_db)):
    items = db.query(Fatura).options(
        joinedload(Fatura.conta).joinedload(Conta.banco_obj)
    ).order_by(
        Fatura.data_vencimento.desc()
    ).all()
    out = []
    for f in items:
        eh_cartao = bool(f.conta and f.conta.tipo == "Cartão de Crédito")
        pag_iso, pag_origem = _pagamento_efetivo(db, f) if eh_cartao else (None, None)
        out.append({
            "id": f.id, "banco": f.banco,
            "conta_id": f.conta_id,
            "conta": f.conta.nome if f.conta else None,
            "tipo_conta": f.conta.tipo if f.conta else None,
            "titular": (f.conta.titular if f.conta else None) or "(você)",
            "mes_referencia": f.mes_referencia,
            "data_vencimento": f.data_vencimento.isoformat() if f.data_vencimento else None,
            "data_pagamento_manual": f.data_pagamento_manual.isoformat() if f.data_pagamento_manual else None,
            "data_pagamento_efetiva": pag_iso,
            "data_pagamento_origem": pag_origem,
            "total": f.total, "pdf_filename": f.pdf_filename,
            "importada_em": f.importada_em.isoformat() if f.importada_em else None,
        })
    return out


@router.patch("/api/faturas/{fid}")
def atualizar_fatura(fid: int, dados: dict, db: Session = Depends(get_db)):
    """Edita a fatura. Hoje aceita `data_pagamento_manual` ("YYYY-MM-DD" ou null/""
    pra limpar). Recalcula a data de pagamento das transações da fatura."""
    f = db.query(Fatura).get(fid)
    if not f:
        raise HTTPException(404, "Fatura não encontrada")
    if "data_pagamento_manual" in dados:
        v = dados["data_pagamento_manual"]
        if v in (None, ""):
            f.data_pagamento_manual = None
        else:
            try:
                f.data_pagamento_manual = datetime.strptime(v, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                raise HTTPException(400, "data_pagamento_manual inválida (use YYYY-MM-DD)")
        db.flush()
        recalcular_data_pagamento(db, f)
    db.commit()
    pag_iso, pag_origem = _pagamento_efetivo(db, f)
    return {"ok": True, "data_pagamento_efetiva": pag_iso, "data_pagamento_origem": pag_origem}


@router.get("/api/faturas/cobertura")
def cobertura_arquivos(meses: int = 12, db: Session = Depends(get_db)):
    """
    Retorna mapa de cobertura: para cada conta importável (cartão de crédito
    ou conta corrente), mostra os últimos N meses e quais têm arquivo importado.

    Útil pra detectar buracos na sequência de importações.
    """
    # 1. Lista contas que aceitam importação (CC e cartão)
    contas = db.query(Conta).options(joinedload(Conta.banco_obj)).filter(
        Conta.ativo == True,
        Conta.tipo.in_(["Cartão de Crédito", "Conta Corrente"]),
    ).all()

    # 2. Eixo de meses: últimos N CONTÍNUOS terminando no mês mais recente com
    # transações. (Antes o eixo vinha só dos meses existentes — um mês sem
    # transação em conta NENHUMA sumia do eixo e nunca aparecia como buraco.)
    todos_meses = [r[0] for r in db.query(Transacao.mes_referencia).distinct().all()]

    # Ordena meses (formato MM/YYYY)
    def mes_to_int(m):
        try:
            mm, yy = m.split("/")
            return int(yy) * 12 + int(mm)
        except:
            return 0

    ints_validos = [v for v in (mes_to_int(m) for m in todos_meses if m) if v > 0]
    if not ints_validos:
        return {"meses": [], "contas": []}
    fim = max(ints_validos)
    meses_recentes = []
    for v in range(fim - meses + 1, fim + 1):
        if v <= 0:
            continue
        yy, mm = (v - 1) // 12, (v - 1) % 12 + 1
        meses_recentes.append(f"{mm:02d}/{yy}")

    # 3. Mapa de faturas por (conta_id, mes_referencia)
    faturas_existentes = set()
    fatura_por_chave = {}
    for f in db.query(Fatura).all():
        chave = (f.conta_id, f.mes_referencia)
        faturas_existentes.add(chave)
        fatura_por_chave[chave] = f.id

    # 3b. Meses que TÊM transações por (conta_id, mes_referencia). Um extrato OFX
    # de conta corrente cobre vários meses num arquivo só, então a Fatura fica
    # rotulada num mês (ex.: 06) mas contém transações de outros (ex.: 05). O mês
    # está coberto se há transações dele — não só se existe Fatura com aquele
    # mes_referencia. Guarda um fatura_id representativo pra abrir/excluir o arquivo.
    # Só transações vindas de ARQUIVO (fatura_id preenchido): um lançamento manual
    # avulso não pode marcar o mês como coberto — mascararia o buraco de importação
    # que o mapa existe pra detectar.
    meses_com_tx = set()
    fatura_por_tx = {}
    ids_contas = [c.id for c in contas]
    if ids_contas:
        for conta_id, mes_ref, fatura_id in db.query(
            Transacao.conta_id, Transacao.mes_referencia, Transacao.fatura_id
        ).filter(
            Transacao.conta_id.in_(ids_contas),
            Transacao.fatura_id.isnot(None),
        ).distinct().all():
            if not mes_ref:
                continue
            chave = (conta_id, mes_ref)
            meses_com_tx.add(chave)
            if chave not in fatura_por_tx:
                fatura_por_tx[chave] = fatura_id

    # 4. Monta resultado
    resultado_contas = []
    for c in contas:
        nome_completo = c.nome
        if c.titular:
            nome_completo = f"{c.nome} ({c.titular})"

        # Primeiro passe: identifica quais meses têm arquivo
        cobertura = []
        for m in meses_recentes:
            # Coberto se há Fatura rotulada nesse mês OU transações desse mês
            # (extrato OFX multi-mês rotula a fatura num mês só).
            tem = (c.id, m) in faturas_existentes or (c.id, m) in meses_com_tx
            cobertura.append({
                "mes": m,
                "tem": tem,
                "fatura_id": (fatura_por_chave.get((c.id, m))
                              or fatura_por_tx.get((c.id, m))) if tem else None,
            })

        # Segundo passe: identifica buracos (mês sem arquivo entre dois meses com arquivo)
        primeiro_idx = next((i for i, x in enumerate(cobertura) if x["tem"]), None)
        ultimo_idx = next((i for i, x in enumerate(reversed(cobertura)) if x["tem"]), None)
        if ultimo_idx is not None:
            ultimo_idx = len(cobertura) - 1 - ultimo_idx

        # Mês de início de uso da conta — antes disso, status = "nao_se_aplica"
        # data_inicio_uso é uma date; comparamos com o mês "MM/YYYY"
        mes_inicio_uso_int = None
        if c.data_inicio_uso:
            mes_inicio_uso_int = c.data_inicio_uso.year * 12 + c.data_inicio_uso.month

        for i, x in enumerate(cobertura):
            mes_atual_int = mes_to_int(x["mes"])
            antes_do_inicio = (
                mes_inicio_uso_int is not None
                and mes_atual_int < mes_inicio_uso_int
            )

            if antes_do_inicio and not x["tem"]:
                x["status"] = "nao_se_aplica"
            elif x["tem"]:
                x["status"] = "tem"
            elif primeiro_idx is not None and ultimo_idx is not None and primeiro_idx < i < ultimo_idx:
                x["status"] = "buraco"
            else:
                x["status"] = "vazio"

        # Conta total e identifica buracos (gaps no meio da sequência)
        total = sum(1 for x in cobertura if x["tem"])
        buracos = sum(1 for x in cobertura if x["status"] == "buraco")
        # Total esperado descarta meses "não se aplica"
        total_esperado = sum(1 for x in cobertura if x["status"] != "nao_se_aplica")

        resultado_contas.append({
            "id": c.id,
            "nome": c.nome,
            "nome_completo": nome_completo,
            "tipo": c.tipo,
            "banco": c.banco_obj.nome if c.banco_obj else c.banco,
            "banco_cor": c.banco_obj.cor if c.banco_obj else None,
            "titular": c.titular,
            "data_inicio_uso": c.data_inicio_uso.isoformat() if c.data_inicio_uso else None,
            "cobertura": cobertura,
            "total_arquivos": total,
            "total_esperado": total_esperado,
            "buracos": buracos,
        })

    # Ordena: primeiro contas com buracos (chamam atenção), depois por banco/titular
    resultado_contas.sort(key=lambda c: (-c["buracos"], c["banco"] or "", c["titular"] or "", c["tipo"]))

    return {
        "meses": meses_recentes,
        "contas": resultado_contas,
    }


@router.delete("/api/faturas/{fid}")
def excluir_fatura(fid: int, db: Session = Depends(get_db)):
    """Exclui uma fatura E todas suas transações (incluindo partes de divisão,
    que nascem sem fatura_id), limpando referências que apontariam pra linhas
    inexistentes — SQLite não aplica FK, então órfãos seguiriam nos totais."""
    f = db.query(Fatura).get(fid)
    if not f:
        raise HTTPException(404)
    ids = [r[0] for r in db.query(Transacao.id).filter(Transacao.fatura_id == fid).all()]
    if ids:
        db.query(Transacao).filter(Transacao.parte_de_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(Transacao).filter(Transacao.estorno_de_id.in_(ids)).update(
            {"estorno_de_id": None}, synchronize_session=False)
        db.query(Transacao).filter(Transacao.duplicata_de_id.in_(ids)).update(
            {"duplicata_de_id": None}, synchronize_session=False)
    db.query(Transacao).filter(Transacao.pagamento_de_fatura_id == fid).update(
        {"pagamento_de_fatura_id": None, "conciliada": False}, synchronize_session=False)
    db.query(Transacao).filter(Transacao.fatura_id == fid).delete(synchronize_session=False)
    db.delete(f)
    db.commit()
    return {"ok": True}
