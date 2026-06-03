"""Transações: listagem, CRUD, suspeitas de duplicata, estornos, propagação
de parcelas e divisões.

Os helpers `_eh_abatedora`/`_serializar_transacao` são reusados pelo dashboard.
Extraído de main.py (refactor por domínio).
"""
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Conta, Categoria, Transacao, Divisao
from ..categorizacao import (
    classificar, aprender_correcao, reclassificar_transacoes_pendentes,
    preview_propagacao, propagar_para_parcelas,
)
from ..utils import normalizar_descricao, hash_dedup

router = APIRouter()


@router.get("/api/transacoes")
def listar_transacoes(
    mes: Optional[str] = Query(None, description="MM/YYYY"),
    data_inicio: Optional[str] = Query(None, description="YYYY-MM-DD (sobrepõe mes)"),
    data_fim: Optional[str] = Query(None, description="YYYY-MM-DD"),
    conta_id: Optional[int] = None,
    banco_id: Optional[int] = None,
    tipo_conta: Optional[str] = None,
    categoria_id: Optional[int] = None,
    atribuicao_id: Optional[int] = None,
    busca: Optional[str] = None,
    nao_categorizado: bool = False,
    nao_atribuido: bool = False,
    incluir_transferencias: bool = False,
    incluir_suspeitas: bool = False,   # se true, lista suspeitas junto com normais
    skip: int = 0,
    limit: int = 1000,
    db: Session = Depends(get_db),
):
    from datetime import date as _d
    q = db.query(Transacao).options(
        joinedload(Transacao.categoria),
        joinedload(Transacao.atribuicao),
        joinedload(Transacao.conta),
    )

    # Filtro de data: período sobrepõe mes
    if data_inicio and data_fim:
        try:
            di = _d.fromisoformat(data_inicio)
            df = _d.fromisoformat(data_fim)
            q = q.filter(Transacao.data >= di, Transacao.data <= df)
        except (ValueError, TypeError):
            raise HTTPException(400, "data_inicio/data_fim inválidos")
    elif mes:
        q = q.filter(Transacao.mes_referencia == mes)
    if conta_id:
        q = q.filter(Transacao.conta_id == conta_id)
    if banco_id or tipo_conta:
        q = q.join(Conta, Transacao.conta_id == Conta.id)
        if banco_id:
            q = q.filter(Conta.banco_id == banco_id)
        if tipo_conta:
            q = q.filter(Conta.tipo == tipo_conta)
    if categoria_id:
        q = q.filter(Transacao.categoria_id == categoria_id)
    if atribuicao_id:
        q = q.filter(Transacao.atribuicao_id == atribuicao_id)
    if busca:
        q = q.filter(Transacao.descricao.ilike(f"%{busca}%"))

    # Por padrão esconde movimentações internas (fatura/transferência) e a
    # categoria especial Investimentos. O checkbox "incluir_transferencias" mostra tudo.
    NOMES_OCULTAS_POR_PADRAO = ["Investimentos"]
    if not incluir_transferencias and not categoria_id:
        # Esconde movimentações internas (geridas no Extrato)
        q = q.filter(Transacao.movimentacao.is_(None))
        ids_ocultas = [c.id for c in db.query(Categoria).filter(
            Categoria.nome.in_(NOMES_OCULTAS_POR_PADRAO)
        ).all()]
        if ids_ocultas:
            q = q.filter(
                ~Transacao.categoria_id.in_(ids_ocultas) | Transacao.categoria_id.is_(None)
            )
    # Filtros de pendência
    if nao_categorizado and nao_atribuido:
        q = q.filter(
            Transacao.categoria_id.is_(None) | Transacao.atribuicao_id.is_(None)
        )
    elif nao_categorizado:
        q = q.filter(Transacao.categoria_id.is_(None))
    elif nao_atribuido:
        q = q.filter(Transacao.atribuicao_id.is_(None))

    # Por padrão NÃO mostra suspeitas (ficam no banner separado pra revisão)
    if not incluir_suspeitas:
        q = q.filter(
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None)
        )

    total = q.count()
    items = q.order_by(Transacao.data.desc(), Transacao.id.desc()).offset(skip).limit(limit).all()

    # Total monetário (sobre o filtro completo, não só a página atual).
    # Considera abatedoras: receita+cat-despesa abate da despesa.
    todas_filtradas = q.options(joinedload(Transacao.categoria)).all()
    total_receitas = 0.0
    total_despesas = 0.0
    for tr in todas_filtradas:
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            total_despesas -= valor
        elif tr.tipo == "Receita":
            total_receitas += valor
        else:
            total_despesas += valor

    # Contagem de suspeitas pendentes (sempre, pra mostrar banner)
    n_suspeitas = db.query(func.count(Transacao.id)).filter(
        Transacao.suspeita_duplicata == True
    ).scalar() or 0

    return {
        "total": total,
        "total_receitas": total_receitas,
        "total_despesas": total_despesas,
        "saldo": total_receitas - total_despesas,
        "n_suspeitas": n_suspeitas,
        "items": [_serializar_transacao(t) for t in items],
    }


def _eh_abatedora(t: Transacao) -> bool:
    """
    True se a transação é uma 'Receita que abate categoria de Despesa'
    (ex: ressarcimento Kotas, estorno, reembolso). Esses casos NÃO devem
    contar como Receita nos totais — devem reduzir o gasto da categoria.

    Regra:
      - tipo == "Receita"
      - tem categoria
      - categoria.tipo == "Despesa"
      - categoria.nome != "Cashback" (cashback continua receita visível)

    Retorna False se algum critério falhar.
    """
    if t.tipo != "Receita":
        return False
    if not t.categoria or not t.categoria_id:
        return False
    if t.categoria.tipo != "Despesa":
        return False
    if t.categoria.nome == "Cashback":
        return False
    return True


def _valor_efetivo(t: Transacao) -> tuple[str, float]:
    """
    Retorna (papel, valor_signed) para totalização.
      papel: "receita" | "despesa" | "abatimento"
      valor_signed: positivo na contribuição própria do papel.
        - receita: + na receita
        - despesa: + na despesa
        - abatimento: + na despesa (mas com sinal negativo no efeito)

    Pra calcular "despesa líquida" da categoria: somar todas as despesas e SUBTRAIR todas as abatedoras.
    """
    valor = t.valor or 0.0
    if _eh_abatedora(t):
        return "abatimento", valor
    if t.tipo == "Receita":
        return "receita", valor
    return "despesa", valor


def _serializar_transacao(t: Transacao) -> dict:
    banco_nome = None
    conta_nome = None
    if t.conta:
        if t.conta.banco_obj:
            banco_nome = t.conta.banco_obj.nome
        elif t.conta.banco:
            banco_nome = t.conta.banco
        conta_nome = t.conta.nome
        if t.conta.titular:
            conta_nome = f"{conta_nome} ({t.conta.titular})"
    # Essencial: usa override se setado, senão fallback pra padrão da categoria
    cat_essencial = bool(t.categoria.essencial) if (t.categoria and t.categoria.essencial is not None) else True
    if t.essencial_override is not None:
        essencial_efetivo = bool(t.essencial_override)
    else:
        essencial_efetivo = cat_essencial

    return {
        "id": t.id,
        "data": t.data.isoformat() if t.data else None,
        "descricao": t.descricao,
        "descricao_personalizada": t.descricao_personalizada,
        "valor": t.valor,
        "tipo": t.tipo,
        "eh_abatedora": _eh_abatedora(t),
        "forma_pagamento": t.forma_pagamento,
        "parcela": t.parcela,
        "mes_referencia": t.mes_referencia,
        "conta": conta_nome,
        "banco": banco_nome,
        "categoria": t.categoria.nome if t.categoria else None,
        "categoria_id": t.categoria_id,
        "categoria_origem": t.categoria_origem,
        "categoria_essencial": cat_essencial,
        "essencial_override": t.essencial_override,
        "essencial": essencial_efetivo,
        "estorno_de_id": t.estorno_de_id,
        "suspeita_duplicata": bool(t.suspeita_duplicata),
        "movimentacao": t.movimentacao,
        "atribuicao": t.atribuicao.nome if t.atribuicao else None,
        "atribuicao_id": t.atribuicao_id,
        "atribuicao_origem": t.atribuicao_origem,
        "observacoes": t.observacoes,
        "conciliada": t.conciliada,
        "duplicata_de_id": t.duplicata_de_id,
        "pagamento_de_fatura_id": t.pagamento_de_fatura_id,
    }


@router.post("/api/transacoes")
def criar_transacao(dados: dict, db: Session = Depends(get_db)):
    """
    Cria transação manual (lançamento avulso, ex: dinheiro físico).

    Campos obrigatórios:
      - data: "YYYY-MM-DD"
      - descricao: string
      - valor: float positivo
      - tipo: "Despesa" | "Receita"
      - conta_id: int

    Opcionais:
      - categoria_id, atribuicao_id
      - forma_pagamento (default: "Dinheiro")
      - mes_referencia (default: deriva da data)
      - parcela ("X/N")
      - observacoes
      - descricao_personalizada
    """
    obrigatorios = ["data", "descricao", "valor", "tipo", "conta_id"]
    faltando = [c for c in obrigatorios if c not in dados or dados[c] in (None, "")]
    if faltando:
        raise HTTPException(400, f"Campos obrigatórios: {', '.join(faltando)}")

    # Parse data
    try:
        data = datetime.strptime(dados["data"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, "Data inválida (formato esperado: YYYY-MM-DD)")

    valor = abs(float(dados["valor"]))   # sempre armazena positivo, sinal vem do `tipo`
    tipo = dados["tipo"]
    if tipo not in ("Despesa", "Receita"):
        raise HTTPException(400, "Tipo precisa ser 'Despesa' ou 'Receita'")

    conta = db.query(Conta).get(int(dados["conta_id"]))
    if not conta:
        raise HTTPException(404, "Conta não encontrada")

    # Mês de referência: usa o fornecido ou deriva da data (formato MM/YYYY)
    mes_ref = dados.get("mes_referencia") or data.strftime("%m/%Y")

    # Forma de pagamento: usa explícita ou infere do tipo da conta
    forma_pagamento = dados.get("forma_pagamento")
    if not forma_pagamento:
        if conta.tipo == "Carteira":
            forma_pagamento = "Dinheiro"
        elif conta.tipo == "Cartão de Crédito":
            forma_pagamento = "Crédito"
        else:
            forma_pagamento = "Débito"

    # Hash dedup baseado em (banco_or_carteira, data, valor, descrição, parcela)
    banco_label = (conta.banco_obj.nome if conta.banco_obj else conta.banco) or "Manual"
    h_dedup = hash_dedup(banco_label, data, valor, dados["descricao"], dados.get("parcela"))

    # Auto-classifica se não veio categoria/atribuição
    categoria_id = dados.get("categoria_id")
    atribuicao_id = dados.get("atribuicao_id")
    cat_origem = "manual"
    atr_origem = "manual"
    if not categoria_id or not atribuicao_id:
        c = classificar(db, dados["descricao"])
        if not categoria_id and c.categoria_id:
            categoria_id = c.categoria_id
            cat_origem = c.categoria_origem
        if not atribuicao_id and c.atribuicao_id:
            atribuicao_id = c.atribuicao_id
            atr_origem = c.atribuicao_origem

    t = Transacao(
        conta_id=conta.id,
        data=data,
        descricao=dados["descricao"].strip(),
        descricao_normalizada=normalizar_descricao(dados["descricao"]),
        descricao_personalizada=dados.get("descricao_personalizada") or None,
        valor=valor,
        tipo=tipo,
        forma_pagamento=forma_pagamento,
        parcela=dados.get("parcela") or None,
        mes_referencia=mes_ref,
        categoria_id=int(categoria_id) if categoria_id else None,
        categoria_origem=cat_origem if categoria_id else "nao_categorizado",
        atribuicao_id=int(atribuicao_id) if atribuicao_id else None,
        atribuicao_origem=atr_origem if atribuicao_id else "nao_categorizado",
        observacoes=dados.get("observacoes") or "Lançamento manual",
        hash_dedup=h_dedup,
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    # Se for Receita, tenta detectar estorno
    if t.tipo == "Receita":
        from ..categorizacao import vincular_estorno
        vincular_estorno(db, t)
        db.commit()
        db.refresh(t)

    return _serializar_transacao(t)


@router.patch("/api/transacoes/{trans_id}")
def atualizar_transacao(
    trans_id: int,
    dados: dict,
    db: Session = Depends(get_db),
):
    """
    Atualiza campos de uma transação. Aceita:
      categoria_id, atribuicao_id, observacoes, descricao, valor, tipo, forma_pagamento.
    Se categoria_id ou atribuicao_id forem alterados, marca origem como "manual"
    e grava na memória de aprendizado.
    """
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")

    cat_changed = False
    atr_changed = False

    # Movimentação interna (fatura / transferência): não é categoria.
    # Setar não-nulo tira a transação da lista/totais; setar None devolve.
    if "movimentacao" in dados:
        mov = dados["movimentacao"]
        if mov in ("", None):
            t.movimentacao = None
            # Volta a poder ser categorizada automaticamente/manual
            if t.categoria_origem == "movimentacao":
                t.categoria_origem = "nao_categorizado"
            if t.atribuicao_origem == "movimentacao":
                t.atribuicao_origem = "nao_categorizado"
        elif mov in ("fatura", "transferencia"):
            t.movimentacao = mov
            t.categoria_id = None
            t.categoria_origem = "movimentacao"
            t.atribuicao_id = None
            t.atribuicao_origem = "movimentacao"
        else:
            raise HTTPException(400, "movimentacao inválida (use 'fatura', 'transferencia' ou null)")

    if "categoria_id" in dados:
        novo = dados["categoria_id"]
        if novo != t.categoria_id:
            t.categoria_id = novo
            t.categoria_origem = "manual"
            cat_changed = True

    if "atribuicao_id" in dados:
        novo = dados["atribuicao_id"]
        if novo != t.atribuicao_id:
            t.atribuicao_id = novo
            t.atribuicao_origem = "manual"
            atr_changed = True

    for campo in ("observacoes", "descricao_personalizada", "tipo", "forma_pagamento"):
        if campo in dados:
            v = dados[campo]
            # string vazia em descricao_personalizada → null (volta a mostrar a original)
            if campo == "descricao_personalizada" and v == "":
                v = None
            setattr(t, campo, v)

    if "valor" in dados:
        t.valor = float(dados["valor"])

    if "essencial_override" in dados:
        v = dados["essencial_override"]
        # null = volta a usar padrão da categoria; true/false = força
        t.essencial_override = None if v is None else bool(v)

    # Aprendizado
    if cat_changed or atr_changed:
        aprender_correcao(
            db, t.descricao,
            categoria_id=t.categoria_id if cat_changed else None,
            atribuicao_id=t.atribuicao_id if atr_changed else None,
        )

    db.commit()
    db.refresh(t)
    return _serializar_transacao(t)


@router.post("/api/transacoes/reclassificar")
def reclassificar(db: Session = Depends(get_db)):
    """Roda reclassificação de transações pendentes (após nova memória/regra)."""
    n = reclassificar_transacoes_pendentes(db)
    db.commit()
    return {"reclassificadas": n}


@router.get("/api/transacoes/suspeitas")
def listar_suspeitas(db: Session = Depends(get_db)):
    """
    Lista todas as transações marcadas como suspeitas de duplicata, com a
    transação 'gêmea' (que tem hash igual) ao lado pra comparação visual.
    """
    suspeitas = db.query(Transacao).filter(
        Transacao.suspeita_duplicata == True
    ).order_by(Transacao.data.desc()).all()

    resultado = []
    for s in suspeitas:
        # Busca a "gêmea": outra transação com o mesmo hash, mesma conta,
        # que NÃO seja suspeita (essa é a "original" que entrou primeiro)
        gemea = db.query(Transacao).filter(
            Transacao.id != s.id,
            Transacao.hash_dedup == s.hash_dedup,
            Transacao.conta_id == s.conta_id,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
        ).first()

        item = {
            "suspeita": _serializar_transacao(s),
            "gemea": _serializar_transacao(gemea) if gemea else None,
        }
        resultado.append(item)

    return {"total": len(resultado), "items": resultado}


@router.post("/api/transacoes/{trans_id}/aceitar-suspeita")
def aceitar_suspeita(trans_id: int, db: Session = Depends(get_db)):
    """Aceita transação suspeita: tira a flag, ela vira normal."""
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")
    t.suspeita_duplicata = False
    db.commit()
    return {"ok": True, "id": t.id}


@router.post("/api/transacoes/{trans_id}/descartar-suspeita")
def descartar_suspeita(trans_id: int, db: Session = Depends(get_db)):
    """Descarta suspeita: exclui a transação."""
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")
    if not t.suspeita_duplicata:
        raise HTTPException(400, "Transação não está marcada como suspeita")
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/api/transacoes/aceitar-todas-suspeitas")
def aceitar_todas_suspeitas(db: Session = Depends(get_db)):
    """Aceita todas as suspeitas de uma vez (caso usuário esteja confiante)."""
    n = db.query(Transacao).filter(
        Transacao.suspeita_duplicata == True
    ).update({"suspeita_duplicata": False}, synchronize_session=False)
    db.commit()
    return {"aceitas": n}


@router.post("/api/transacoes/descartar-todas-suspeitas")
def descartar_todas_suspeitas(db: Session = Depends(get_db)):
    """Descarta todas as suspeitas (caso usuário queira manter o comportamento legado)."""
    n = db.query(Transacao).filter(
        Transacao.suspeita_duplicata == True
    ).delete(synchronize_session=False)
    db.commit()
    return {"descartadas": n}


@router.post("/api/transacoes/detectar-estornos")
def detectar_estornos_endpoint(db: Session = Depends(get_db)):
    """
    Roda detecção de estornos em todas as Receitas que ainda não têm vínculo.
    Útil pra rodar uma vez sobre transações importadas antes da feature existir.
    """
    from ..categorizacao import vincular_estorno
    receitas = db.query(Transacao).filter(
        Transacao.tipo == "Receita",
        Transacao.estorno_de_id.is_(None),
    ).all()

    n_vinculadas = 0
    for r in receitas:
        if vincular_estorno(db, r):
            n_vinculadas += 1
    db.commit()
    return {"receitas_analisadas": len(receitas), "vinculadas": n_vinculadas}


@router.post("/api/transacoes/atualizar-em-massa")
def atualizar_em_massa(dados: dict, db: Session = Depends(get_db)):
    """
    Atualiza categoria e/ou atribuição de várias transações de uma vez.

    Body:
      ids: list[int] — transações a atualizar (pelo menos 1)
      categoria_id: int | None — opcional. Se presente (mesmo que None), aplica.
      atribuicao_id: int | None — opcional. Idem.

    Pelo menos um dos dois (categoria_id ou atribuicao_id) precisa estar presente
    nas chaves do body. Origem fica "manual".
    Não grava memória de aprendizado em massa (seria barulhento).
    """
    ids = dados.get("ids") or []
    if not ids or not isinstance(ids, list):
        raise HTTPException(400, "Forneça uma lista de ids no campo 'ids'")

    aplicar_categoria = "categoria_id" in dados
    aplicar_atribuicao = "atribuicao_id" in dados
    if not aplicar_categoria and not aplicar_atribuicao:
        raise HTTPException(400, "Forneça pelo menos categoria_id ou atribuicao_id")

    nova_cat = dados.get("categoria_id")  # pode ser None (limpa) ou int
    nova_atr = dados.get("atribuicao_id")

    transacoes = db.query(Transacao).filter(Transacao.id.in_(ids)).all()
    n_atualizadas = 0
    for t in transacoes:
        mudou = False
        if aplicar_categoria and t.categoria_id != nova_cat:
            t.categoria_id = nova_cat
            t.categoria_origem = "manual"
            mudou = True
        if aplicar_atribuicao and t.atribuicao_id != nova_atr:
            t.atribuicao_id = nova_atr
            t.atribuicao_origem = "manual"
            mudou = True
        if mudou:
            n_atualizadas += 1

    db.commit()
    return {
        "ok": True,
        "ids_solicitados": len(ids),
        "atualizadas": n_atualizadas,
    }


@router.get("/api/transacoes/{trans_id}/preview-propagacao")
def preview_propagacao_endpoint(trans_id: int, db: Session = Depends(get_db)):
    """
    Verifica quantas parcelas irmãs existem e o que aconteceria se propagar.
    Não altera nada. Usado pra UI decidir se mostra confirm.
    """
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")
    return preview_propagacao(db, t)


@router.post("/api/transacoes/{trans_id}/propagar")
def propagar_endpoint(
    trans_id: int,
    forcar: bool = False,
    db: Session = Depends(get_db),
):
    """
    Propaga categoria, atribuição e descrição_personalizada da transação
    pras parcelas irmãs.

    forcar=False: só preenche campos NULL ou já iguais (não sobrescreve divergências)
    forcar=True:  sobrescreve TUDO (use com confirm do usuário)
    """
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")
    resultado = propagar_para_parcelas(db, t, forcar=forcar)
    db.commit()
    return resultado


@router.delete("/api/transacoes/{trans_id}")
def excluir_transacao(trans_id: int, db: Session = Depends(get_db)):
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.put("/api/transacoes/{trans_id}/divisoes")
def definir_divisoes(
    trans_id: int,
    divisoes: list[dict],  # [{atribuicao_id, percentual}]
    db: Session = Depends(get_db),
):
    """Substitui as divisões da transação. Soma deve dar 100%."""
    t = db.query(Transacao).get(trans_id)
    if not t:
        raise HTTPException(404, "Transação não encontrada")

    total_pct = sum(d.get("percentual", 0) for d in divisoes)
    if abs(total_pct - 100) > 0.01:
        raise HTTPException(400, f"Soma dos percentuais precisa ser 100% (recebido: {total_pct}%)")

    # Limpa anteriores
    db.query(Divisao).filter(Divisao.transacao_id == trans_id).delete()

    for d in divisoes:
        db.add(Divisao(
            transacao_id=trans_id,
            atribuicao_id=d["atribuicao_id"],
            percentual=d["percentual"],
        ))

    db.commit()
    return {"ok": True}
