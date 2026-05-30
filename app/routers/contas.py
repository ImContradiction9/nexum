"""Contas (correntes/cartões/carteira): CRUD. Extraído de main.py."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Conta, Banco, Transacao, Fatura

router = APIRouter()


@router.get("/api/contas")
def listar_contas(db: Session = Depends(get_db)):
    contas = db.query(Conta).options(joinedload(Conta.banco_obj)).all()
    # Conta quantas têm cada nome — pra decidir se precisa desambiguar
    nomes_count = {}
    for c in contas:
        nomes_count[c.nome] = nomes_count.get(c.nome, 0) + 1

    def nome_amigavel(c):
        # Se o nome é único entre todas as contas, mostra direto.
        # Se repete, acrescenta titular ou tipo (o que diferenciar).
        if nomes_count.get(c.nome, 0) <= 1:
            return c.nome
        # Tem duplicatas: prioriza titular > tipo
        if c.titular:
            return f"{c.nome} ({c.titular})"
        return f"{c.nome} — {c.tipo}"

    out = [{
        "id": c.id, "nome": c.nome,
        "nome_completo": nome_amigavel(c),
        "tipo": c.tipo,
        "banco_id": c.banco_id,
        "banco": c.banco_obj.nome if c.banco_obj else (c.banco or None),
        "banco_cor": c.banco_obj.cor if c.banco_obj else None,
        "dia_fechamento": c.dia_fechamento, "dia_vencimento": c.dia_vencimento,
        "final": c.final, "ativo": c.ativo,
        "tem_senha": bool(c.senha_pdf),
        "titular": c.titular,
        "observacoes": c.observacoes,
    } for c in contas]
    # Ordenado por banco, tipo, titular pra agrupar visualmente
    out.sort(key=lambda x: (x["banco"] or "zz", x["tipo"], x["titular"] or ""))
    return out


@router.post("/api/contas")
def criar_conta(dados: dict, db: Session = Depends(get_db)):
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")

    # Se enviou banco_id usa direto; senão tenta buscar/criar pelo nome em "banco"
    banco_id = dados.get("banco_id")
    banco_nome = (dados.get("banco") or "").strip()
    if not banco_id and banco_nome:
        b = db.query(Banco).filter(Banco.nome == banco_nome).first()
        if not b:
            b = Banco(nome=banco_nome, cor="#888888")
            db.add(b)
            db.flush()
        banco_id = b.id

    tipo = dados.get("tipo", "Conta Corrente")
    titular = (dados.get("titular") or "").strip() or None

    # Uniqueness: a combinação (banco_id, tipo, titular) precisa ser única.
    # Permite duas contas Nubank Conta Corrente — uma sua, outra da Andreina.
    existente = db.query(Conta).filter(
        Conta.banco_id == banco_id,
        Conta.tipo == tipo,
        Conta.titular == titular,
    ).first()
    if existente:
        ident = f"{banco_nome or '?'} / {tipo}"
        if titular:
            ident += f" / {titular}"
        raise HTTPException(400, f"Já existe uma conta '{ident}' (id {existente.id}). "
                                  f"Use um titular diferente pra distinguir.")

    c = Conta(
        nome=nome,
        tipo=tipo,
        banco_id=banco_id,
        banco=banco_nome or None,
        dia_fechamento=dados.get("dia_fechamento"),
        dia_vencimento=dados.get("dia_vencimento"),
        final=dados.get("final", ""),
        titular=titular,
        observacoes=dados.get("observacoes", ""),
    )
    db.add(c)
    db.commit()
    return {"id": c.id, "nome": c.nome}


@router.patch("/api/contas/{conta_id}")
def atualizar_conta(conta_id: int, dados: dict, db: Session = Depends(get_db)):
    """Atualiza campos de uma conta. Suporta: senha_pdf, observacoes, ativo, etc."""
    c = db.query(Conta).get(conta_id)
    if not c:
        raise HTTPException(404, "Conta não encontrada")

    # Senha: string vazia = remover senha; null = não alterar; outra coisa = atualizar
    if "senha_pdf" in dados:
        v = dados["senha_pdf"]
        if v == "" or v is None:
            c.senha_pdf = None
        else:
            c.senha_pdf = str(v)

    if "nome" in dados and dados["nome"]:
        c.nome = dados["nome"].strip()

    # banco_id pode vir direto OU via nome (string). Se enviou banco como string, busca/cria.
    if "banco_id" in dados:
        c.banco_id = dados["banco_id"] if dados["banco_id"] else None
    elif "banco" in dados:
        v = (dados["banco"] or "").strip()
        if v:
            b = db.query(Banco).filter(Banco.nome == v).first()
            if not b:
                b = Banco(nome=v, cor="#888888")
                db.add(b)
                db.flush()
            c.banco_id = b.id
            c.banco = v
        else:
            c.banco_id = None
            c.banco = None

    for campo in ("tipo", "observacoes", "dia_fechamento", "dia_vencimento", "final", "ativo", "titular"):
        if campo in dados:
            v = dados[campo]
            if isinstance(v, str):
                v = v.strip() or None
            setattr(c, campo, v)

    # Saldo manual: aceita float ou null. Se tiver valor sem data, ignora.
    if "saldo_inicial_manual" in dados:
        v = dados["saldo_inicial_manual"]
        c.saldo_inicial_manual = float(v) if v not in (None, "") else None
    if "saldo_inicial_data" in dados:
        v = dados["saldo_inicial_data"]
        if v in (None, ""):
            c.saldo_inicial_data = None
        else:
            try:
                c.saldo_inicial_data = datetime.fromisoformat(v).date()
            except (ValueError, TypeError):
                pass

    if "data_inicio_uso" in dados:
        v = dados["data_inicio_uso"]
        if v in (None, ""):
            c.data_inicio_uso = None
        else:
            try:
                c.data_inicio_uso = datetime.fromisoformat(v).date()
            except (ValueError, TypeError):
                pass

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        msg = str(e).lower()
        if "unique" in msg and "nome" in msg:
            raise HTTPException(400,
                "A constraint antiga de nome único ainda existe no banco de dados. "
                "Reinicie o app pra rodar a migração que remove ela."
            )
        raise HTTPException(400, f"Erro ao atualizar: {e}")
    return {
        "id": c.id, "nome": c.nome, "tem_senha": bool(c.senha_pdf),
        "ok": True,
    }


@router.delete("/api/contas/{conta_id}")
def excluir_conta(conta_id: int, db: Session = Depends(get_db)):
    c = db.query(Conta).get(conta_id)
    if not c:
        raise HTTPException(404)
    n_trans = db.query(Transacao).filter(Transacao.conta_id == conta_id).count()
    n_faturas = db.query(Fatura).filter(Fatura.conta_id == conta_id).count()
    if n_trans > 0 or n_faturas > 0:
        raise HTTPException(
            400,
            f"Não posso excluir: {n_trans} transação(ões) e {n_faturas} fatura(s) "
            f"usam esta conta. Considere desativar (botão na lista) "
            f"ou excluir as faturas primeiro."
        )
    db.delete(c)
    db.commit()
    return {"ok": True}
