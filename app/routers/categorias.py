"""Categorias: CRUD + reset de classificação. Extraído de main.py."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Categoria, Transacao, Regra, Memoria, Atribuicao
from ..seed import CATEGORIAS_PADRAO, REGRAS_PADRAO
from ..categorizacao import reclassificar_transacoes_pendentes
from ..utils import ordena_pt

router = APIRouter()


@router.get("/api/categorias")
def listar_categorias(db: Session = Depends(get_db)):
    cats = db.query(Categoria).filter(Categoria.ativo == True).all()
    return [{"id": c.id, "nome": c.nome, "tipo": c.tipo, "icone": c.icone,
             "orcamento_mensal": c.orcamento_mensal,
             "orcado": bool(c.orcado),
             "essencial": bool(c.essencial) if c.essencial is not None else True}
            for c in ordena_pt(cats)]


@router.post("/api/categorias")
def criar_categoria(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    if db.query(Categoria).filter(Categoria.nome == nome).first():
        raise HTTPException(400, f"Já existe uma categoria '{nome}'")
    c = Categoria(
        nome=nome,
        tipo=dados.get("tipo", "Despesa"),
        icone=dados.get("icone", ""),
        orcamento_mensal=float(dados.get("orcamento_mensal") or 0),
        essencial=bool(dados.get("essencial", True)),
    )
    db.add(c)
    db.commit()
    return {"id": c.id, "nome": c.nome}


@router.patch("/api/categorias/{cid}")
def atualizar_categoria(cid: int, dados: dict, db: Session = Depends(get_db)):
    c = db.query(Categoria).get(cid)
    if not c:
        raise HTTPException(404)
    if "nome" in dados and dados["nome"]:
        c.nome = dados["nome"].strip()
    for campo in ("tipo", "icone", "ativo", "essencial"):
        if campo in dados:
            setattr(c, campo, dados[campo])
    if "orcado" in dados:
        c.orcado = bool(dados["orcado"])
    if "orcamento_mensal" in dados:
        c.orcamento_mensal = float(dados["orcamento_mensal"] or 0)
    db.commit()
    return {"id": c.id, "ok": True}


@router.delete("/api/categorias/{cid}")
def excluir_categoria(cid: int, db: Session = Depends(get_db)):
    c = db.query(Categoria).get(cid)
    if not c:
        raise HTTPException(404)
    n_trans = db.query(Transacao).filter(Transacao.categoria_id == cid).count()
    n_regras = db.query(Regra).filter(Regra.categoria_id == cid).count()
    if n_trans > 0 or n_regras > 0:
        raise HTTPException(
            400,
            f"Não posso excluir: {n_trans} transação(ões) e {n_regras} regra(s) "
            f"usam esta categoria. Considere desativar (PATCH ativo=false) "
            f"ou reatribuir antes."
        )
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/api/categorias/reset-classificacao")
def resetar_classificacao(db: Session = Depends(get_db)):
    """
    Operação destrutiva mas reversível pelo usuário:
      1) Limpa categoria_id e categoria_origem de TODAS as transações
      2) Apaga toda a Memoria (palavras-chave aprendidas)
      3) Apaga Regras antigas, recria as REGRAS_PADRAO atuais
      4) Cria/atualiza Categorias da nova estrutura
      5) Aplica as regras novas em todas as transações
      6) Apaga categorias ÓRFÃS (não estão na lista padrão E não têm
         transações nem regras nem atribuições associadas após a reorganização)
    Atribuições NÃO são tocadas (decisão do usuário).
    """
    # === 1. Limpa classificação atual ===
    n_trans_total = db.query(Transacao).count()
    db.query(Transacao).update({
        Transacao.categoria_id: None,
        Transacao.categoria_origem: "nao_categorizado",
    }, synchronize_session=False)

    # === 2. Limpa memória ===
    n_memorias = db.query(Memoria).count()
    db.query(Memoria).delete(synchronize_session=False)

    # === 3. Apaga regras (TODAS — incluindo as que o usuário criou).
    # O usuário foi avisado na UI. Sem isso, regras antigas continuariam
    # apontando pra categorias que talvez serão renomeadas/excluídas.
    n_regras_antigas = db.query(Regra).count()
    db.query(Regra).delete(synchronize_session=False)

    # === 4. Garante que todas as categorias da nova estrutura existem ===
    nomes_padrao = {nome for nome, *_ in CATEGORIAS_PADRAO}
    n_cats_criadas = 0
    for nome, tipo, orc, icone, essencial in CATEGORIAS_PADRAO:
        existente = db.query(Categoria).filter(Categoria.nome == nome).first()
        if existente:
            existente.icone = icone
            existente.ativo = True
            existente.essencial = essencial
        else:
            db.add(Categoria(
                nome=nome, tipo=tipo, orcamento_mensal=orc,
                icone=icone, ativo=True, essencial=essencial,
            ))
            n_cats_criadas += 1
    db.flush()

    # === 5. Recria regras padrão ===
    cat_map = {c.nome: c.id for c in db.query(Categoria).all()}
    atr_map = {a.nome: a.id for a in db.query(Atribuicao).all()}

    n_regras_novas = 0
    for kw, cat_nome, atr_nome, prio, com in REGRAS_PADRAO:
        if cat_nome not in cat_map:
            continue
        db.add(Regra(
            palavra_chave=kw,
            categoria_id=cat_map[cat_nome],
            atribuicao_id=atr_map.get(atr_nome) if atr_nome else None,
            prioridade=prio,
            comentario=com,
        ))
        n_regras_novas += 1
    db.flush()

    # === 6. Aplica regras novas em todas as transações ===
    n_reclassificadas = reclassificar_transacoes_pendentes(db)
    db.flush()

    # === 7. Apaga categorias órfãs (não estão na lista E não são usadas) ===
    # Após reclassificação, alguma transação pode ter caído numa categoria
    # antiga (memória manual). Só apago as que ficaram realmente sem uso.
    todas_cats = db.query(Categoria).all()
    n_cats_apagadas = 0
    cats_apagadas_nomes = []
    for cat in todas_cats:
        if cat.nome in nomes_padrao:
            continue  # categoria padrão, mantém
        n_trans = db.query(Transacao).filter(Transacao.categoria_id == cat.id).count()
        n_regras_uso = db.query(Regra).filter(Regra.categoria_id == cat.id).count()
        if n_trans == 0 and n_regras_uso == 0:
            cats_apagadas_nomes.append(cat.nome)
            db.delete(cat)
            n_cats_apagadas += 1

    db.commit()
    return {
        "ok": True,
        "transacoes_total": n_trans_total,
        "transacoes_reclassificadas": n_reclassificadas,
        "memorias_apagadas": n_memorias,
        "regras_antigas_apagadas": n_regras_antigas,
        "regras_novas_criadas": n_regras_novas,
        "categorias_criadas": n_cats_criadas,
        "categorias_apagadas": n_cats_apagadas,
        "categorias_apagadas_nomes": cats_apagadas_nomes,
    }
