"""Dashboard: resumo mensal, evolução e previsão de parcelas futuras.
Extraído de main.py. Reusa _eh_abatedora de transacoes."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..deps import get_db
from ..database import Categoria, Conta, Transacao, OperacaoInvestimento
from .transacoes import _eh_abatedora

router = APIRouter()


@router.get("/api/orcamentos")
def orcamentos(mes: Optional[str] = None, db: Session = Depends(get_db)):
    """Acompanhamento de orçamento mensal por categoria: para cada categoria com
    teto definido (orcamento_mensal > 0), quanto já foi gasto no mês vs o teto.
    `mes` = "MM/YYYY" (default: mês da última transação, ou o atual)."""
    if not mes:
        ultima = (db.query(Transacao)
                  .filter(Transacao.mes_referencia.isnot(None))
                  .order_by(Transacao.id.desc()).first())
        mes = ultima.mes_referencia if ultima else datetime.now().strftime("%m/%Y")

    cats = (db.query(Categoria)
            .filter(Categoria.orcamento_mensal > 0, Categoria.ativo == True)
            .all())
    if not cats:
        return {"mes": mes, "itens": [], "total_orcado": 0.0, "total_gasto": 0.0}

    ids = [c.id for c in cats]
    gasto = {cid: 0.0 for cid in ids}
    trans = (db.query(Transacao)
             .options(joinedload(Transacao.categoria))
             .filter(
                 Transacao.mes_referencia == mes,
                 Transacao.categoria_id.in_(ids),
                 (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
                 (Transacao.dividida == False) | Transacao.dividida.is_(None),
             ).all())
    for tr in trans:
        v = tr.valor or 0.0
        if _eh_abatedora(tr):
            gasto[tr.categoria_id] -= v          # estorno/reembolso reduz o gasto
        elif tr.tipo == "Despesa":
            gasto[tr.categoria_id] += v

    itens = []
    for c in cats:
        g = max(gasto.get(c.id, 0.0), 0.0)
        orc = c.orcamento_mensal or 0.0
        itens.append({
            "id": c.id, "nome": c.nome, "icone": c.icone,
            "orcamento": round(orc, 2), "gasto": round(g, 2),
            "restante": round(orc - g, 2),
            "pct": round((g / orc * 100) if orc > 0 else 0, 1),
            "estourou": g > orc,
        })
    itens.sort(key=lambda x: -x["pct"])
    return {
        "mes": mes,
        "itens": itens,
        "total_orcado": round(sum(i["orcamento"] for i in itens), 2),
        "total_gasto": round(sum(i["gasto"] for i in itens), 2),
    }


@router.get("/api/dashboard")
def dashboard(
    mes: Optional[str] = None,
    data_inicio: Optional[str] = None,   # "YYYY-MM-DD" — sobrepõe mes
    data_fim: Optional[str] = None,      # "YYYY-MM-DD"
    incluir_especiais: bool = False,
    regime: str = "pagamento",           # "pagamento" (caixa) | "emissao" (compra)
    db: Session = Depends(get_db),
):
    """
    Retorna totais agregados.

    Modo padrão (mês): passa `mes="MM/YYYY"`. Filtra por mes_referencia.
    Modo período: passa `data_inicio` e `data_fim` (ISO date). Filtra por data
      da transação. Ignora `mes` quando ambos estão presentes.
    """
    from datetime import date as _date_cls
    from calendar import monthrange

    # Detecta modo
    modo_periodo = bool(data_inicio and data_fim)
    di_obj = None
    df_obj = None
    if modo_periodo:
        try:
            di_obj = _date_cls.fromisoformat(data_inicio)
            df_obj = _date_cls.fromisoformat(data_fim)
        except (ValueError, TypeError):
            raise HTTPException(400, "data_inicio/data_fim inválidos (formato YYYY-MM-DD)")
        if df_obj < di_obj:
            raise HTTPException(400, "data_fim deve ser >= data_inicio")
        # Calcula período anterior de mesma duração (pra comparativo).
        # Blindado: se o início do período estiver perto de date.min (0001-01-01),
        # subtrair um dia estoura (OverflowError) — nesse caso, simplesmente não há
        # comparativo, mas o dashboard NUNCA deve quebrar por causa disso.
        from datetime import timedelta
        duracao = (df_obj - di_obj).days + 1
        try:
            df_ant_obj = di_obj - timedelta(days=1)
            di_ant_obj = df_ant_obj - timedelta(days=duracao - 1)
            mes_anterior_label = f"{di_ant_obj.isoformat()} a {df_ant_obj.isoformat()}"
        except (OverflowError, ValueError):
            df_ant_obj = di_ant_obj = None
            mes_anterior_label = None
        # Pra exibição, deriva um "label" do período
        mes_label = f"{data_inicio} a {data_fim}"
    else:
        if not mes:
            ultima_trans = db.query(Transacao).order_by(Transacao.data.desc()).first()
            if ultima_trans:
                mes = ultima_trans.mes_referencia
            else:
                mes = datetime.now().strftime("%m/%Y")
        mes_label = mes
        mes_anterior_label = None  # vai ser calculado depois

    # Regime: por qual data filtrar o período.
    #   "pagamento" (caixa) → data efetiva de pagamento (cartão = vencimento/pagamento
    #                         da fatura; extrato = a própria data).
    #   "emissao"           → data da compra.
    regime = (regime or "pagamento").lower()
    if regime not in ("pagamento", "emissao"):
        regime = "pagamento"
    campo_data = (func.coalesce(Transacao.data_pagamento, Transacao.data)
                  if regime == "pagamento" else Transacao.data)

    # IDs das categorias especiais a excluir dos totais (Investimentos e
    # Empréstimos seguem como categoria; fatura/transferência saem por flag).
    NOMES_ESPECIAIS = [
        "Empréstimos a Terceiros",
        "Investimentos",
    ]
    cats_especiais = db.query(Categoria).filter(
        Categoria.nome.in_(NOMES_ESPECIAIS)
    ).all()
    ids_especiais = [c.id for c in cats_especiais]

    # Base: exclui suspeitas de duplicata (não contam até usuário revisar)
    if modo_periodo:
        base = db.query(Transacao).filter(
            campo_data >= di_obj,
            campo_data <= df_obj,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
        )
    else:
        base = db.query(Transacao).filter(
            Transacao.mes_referencia == mes,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
        )
    # O pai de uma transação dividida NUNCA entra nos totais (as filhas é que contam)
    base = base.filter((Transacao.dividida == False) | Transacao.dividida.is_(None))
    if not incluir_especiais:
        # Movimentações internas (fatura/transferência) nunca entram nos totais
        base = base.filter(Transacao.movimentacao.is_(None))
        if ids_especiais:
            base = base.filter(
                ~Transacao.categoria_id.in_(ids_especiais) | Transacao.categoria_id.is_(None)
            )

    # Total de cada categoria especial (pra mostrar separado) — também exclui suspeitas
    totais_especiais = {}
    for c in cats_especiais:
        q = db.query(func.sum(Transacao.valor)).filter(
            Transacao.categoria_id == c.id,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
            (Transacao.dividida == False) | Transacao.dividida.is_(None),
        )
        if modo_periodo:
            q = q.filter(campo_data >= di_obj, campo_data <= df_obj)
        else:
            q = q.filter(Transacao.mes_referencia == mes)
        v = q.scalar() or 0
        if v > 0:
            totais_especiais[c.nome] = v

    # Totais das movimentações internas (por flag) — pra exibir "fora dos totais"
    LABEL_MOV = {"fatura": "Pagamento de Fatura", "transferencia": "Transferência entre Contas"}
    for flag, label in LABEL_MOV.items():
        q = db.query(func.sum(Transacao.valor)).filter(
            Transacao.movimentacao == flag,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
            (Transacao.dividida == False) | Transacao.dividida.is_(None),
        )
        if modo_periodo:
            q = q.filter(campo_data >= di_obj, campo_data <= df_obj)
        else:
            q = q.filter(Transacao.mes_referencia == mes)
        v = q.scalar() or 0
        if v > 0:
            totais_especiais[label] = v

    # === Fluxos especiais do período (pro "Saldo geral") — empréstimos e
    # investimentos por tipo (entrou/saiu), respeitando período/regime/exclusões. ===
    cat_por_nome = {c.nome: c for c in cats_especiais}

    def _fluxo(cat_nome, tipo):
        c = cat_por_nome.get(cat_nome)
        if not c:
            return 0.0
        q = db.query(func.sum(Transacao.valor)).filter(
            Transacao.categoria_id == c.id,
            Transacao.tipo == tipo,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
            (Transacao.dividida == False) | Transacao.dividida.is_(None),
        )
        if modo_periodo:
            q = q.filter(campo_data >= di_obj, campo_data <= df_obj)
        else:
            q = q.filter(Transacao.mes_referencia == mes)
        return q.scalar() or 0.0

    emp_recebido = _fluxo("Empréstimos a Terceiros", "Receita")
    emp_concedido = _fluxo("Empréstimos a Terceiros", "Despesa")
    inv_resgatado = _fluxo("Investimentos", "Receita")
    inv_aplicado = _fluxo("Investimentos", "Despesa")

    # === Cálculo principal: receitas, despesas, essencial/discricionário ===
    # Em vez de SQL (que não consegue distinguir abatedoras), usamos Python.
    # Regra: receita com categoria de Despesa (exceto Cashback) ABATE da categoria,
    # não conta como receita.
    todas_trans = base.options(joinedload(Transacao.categoria)).all()

    receitas = 0.0
    despesas = 0.0
    desp_essencial = 0.0
    desp_discricionario = 0.0

    for tr in todas_trans:
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            # Reduz despesa total e despesa da categoria correspondente
            despesas -= valor
            # Decide qual bucket essencial/discricionário diminuir (segue padrão da categoria)
            if tr.essencial_override is not None:
                eh_essencial = bool(tr.essencial_override)
            elif tr.categoria and tr.categoria.essencial is not None:
                eh_essencial = bool(tr.categoria.essencial)
            else:
                eh_essencial = True
            if eh_essencial:
                desp_essencial -= valor
            else:
                desp_discricionario -= valor
        elif tr.tipo == "Receita":
            receitas += valor
        else:
            # Despesa normal
            despesas += valor
            if tr.essencial_override is not None:
                eh_essencial = bool(tr.essencial_override)
            elif tr.categoria and tr.categoria.essencial is not None:
                eh_essencial = bool(tr.categoria.essencial)
            else:
                eh_essencial = True
            if eh_essencial:
                desp_essencial += valor
            else:
                desp_discricionario += valor

    # === Agregações em Python pra considerar abatedoras ===
    # Reutiliza todas_trans (já carregada acima com joinedload de categoria).
    # Pra Atribuição e Banco, faço query separada com joinedload do que precisa.

    # Por categoria
    cat_totais = {}  # nome -> {"icone", "total"}
    for tr in todas_trans:
        if not tr.categoria:
            continue
        nome = tr.categoria.nome
        icone = tr.categoria.icone
        if nome not in cat_totais:
            cat_totais[nome] = {"icone": icone, "total": 0.0}
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            cat_totais[nome]["total"] -= valor
        elif tr.tipo == "Despesa":
            cat_totais[nome]["total"] += valor
        # Receitas normais não entram em "por_categoria" (gráfico de despesas)
    rows_cat = sorted(
        [(d["icone"], n, d["total"]) for n, d in cat_totais.items() if d["total"] > 0],
        key=lambda x: x[2], reverse=True,
    )
    # Formato esperado depois: [(nome, icone, total)]
    rows_cat = [(n, i, v) for i, n, v in rows_cat]

    # Por atribuição
    atr_totais = {}  # id -> {"nome", "tipo", "cor", "total"}
    todas_com_atr = base.options(
        joinedload(Transacao.categoria),
        joinedload(Transacao.atribuicao),
    ).filter(Transacao.atribuicao_id.isnot(None)).all()
    for tr in todas_com_atr:
        if not tr.atribuicao:
            continue
        aid = tr.atribuicao_id
        if aid not in atr_totais:
            atr_totais[aid] = {
                "nome": tr.atribuicao.nome,
                "tipo": tr.atribuicao.tipo,
                "cor": tr.atribuicao.cor,
                "total": 0.0,
            }
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            atr_totais[aid]["total"] -= valor
        elif tr.tipo == "Despesa":
            atr_totais[aid]["total"] += valor
    rows_atr = sorted(
        [(d["nome"], d["tipo"], d["cor"], d["total"]) for d in atr_totais.values() if d["total"] > 0],
        key=lambda x: x[3], reverse=True,
    )

    # Por banco
    banco_totais = {}  # nome -> total
    todas_com_conta = base.options(
        joinedload(Transacao.categoria),
        joinedload(Transacao.conta).joinedload(Conta.banco_obj),
    ).all()
    for tr in todas_com_conta:
        if tr.conta:
            if tr.conta.banco_obj:
                banco_label = tr.conta.banco_obj.nome
            elif tr.conta.banco:
                banco_label = tr.conta.banco
            else:
                banco_label = "Sem banco"
        else:
            banco_label = "Sem banco"
        if banco_label not in banco_totais:
            banco_totais[banco_label] = 0.0
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            banco_totais[banco_label] -= valor
        elif tr.tipo == "Despesa":
            banco_totais[banco_label] += valor
    rows_banco = sorted(
        [(n, v) for n, v in banco_totais.items() if v > 0],
        key=lambda x: x[1], reverse=True,
    )

    # Por forma de pagamento
    forma_totais = {}
    for tr in todas_trans:
        forma = tr.forma_pagamento or "Não especificada"
        if forma not in forma_totais:
            forma_totais[forma] = 0.0
        valor = tr.valor or 0.0
        if _eh_abatedora(tr):
            forma_totais[forma] -= valor
        elif tr.tipo == "Despesa":
            forma_totais[forma] += valor
    rows_forma = sorted(
        [(f, v) for f, v in forma_totais.items() if v > 0],
        key=lambda x: x[1], reverse=True,
    )

    # Total não categorizado / não atribuído
    nao_cat = base.filter(
        Transacao.categoria_id.is_(None), Transacao.tipo == "Despesa"
    ).count()
    nao_atr = base.filter(
        Transacao.atribuicao_id.is_(None), Transacao.tipo == "Despesa"
    ).count()

    # Lista de meses disponíveis
    # Ordena cronologicamente, mais recente primeiro.
    # Não dá pra usar ORDER BY do SQL porque mes_referencia é string "MM/YYYY"
    # e a ordenação alfabética agruparia mal (todos os "12" juntos, etc).
    def _mes_para_chave(s: str) -> tuple:
        try:
            mm, yyyy = s.split("/")
            return (int(yyyy), int(mm))
        except (ValueError, AttributeError):
            return (0, 0)
    meses_raw = [r[0] for r in db.query(Transacao.mes_referencia).distinct().all() if r[0]]
    meses = sorted(meses_raw, key=_mes_para_chave, reverse=True)

    # === Comparativo com período anterior ===
    if modo_periodo and di_ant_obj is not None and df_ant_obj is not None:
        # Período de mesma duração antes
        mes_anterior = mes_anterior_label
        base_ant_query = db.query(Transacao).filter(
            campo_data >= di_ant_obj,
            campo_data <= df_ant_obj,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
        )
        n_ant_total = base_ant_query.count()
    else:
        # Modo mês: calcula mês anterior em formato MM/YYYY
        try:
            m_atual, y_atual = mes.split("/")
            m_int, y_int = int(m_atual), int(y_atual)
            if m_int == 1:
                m_ant, y_ant = 12, y_int - 1
            else:
                m_ant, y_ant = m_int - 1, y_int
            mes_anterior = f"{m_ant:02d}/{y_ant}"
        except (ValueError, AttributeError):
            mes_anterior = None
        base_ant_query = None
        n_ant_total = 0

    receitas_anteriores = 0.0
    despesas_anteriores = 0.0
    desp_essencial_ant = 0.0
    desp_discricionario_ant = 0.0
    tem_mes_anterior = False
    if modo_periodo:
        if n_ant_total > 0:
            tem_mes_anterior = True
            base_ant = base_ant_query
            base_ant = base_ant.filter((Transacao.dividida == False) | Transacao.dividida.is_(None))
            if not incluir_especiais:
                base_ant = base_ant.filter(Transacao.movimentacao.is_(None))
                if ids_especiais:
                    base_ant = base_ant.filter(
                        ~Transacao.categoria_id.in_(ids_especiais) | Transacao.categoria_id.is_(None)
                    )
            for tr in base_ant.options(joinedload(Transacao.categoria)).all():
                valor = tr.valor or 0.0
                if _eh_abatedora(tr):
                    despesas_anteriores -= valor
                    if tr.essencial_override is not None:
                        eh_e = bool(tr.essencial_override)
                    elif tr.categoria and tr.categoria.essencial is not None:
                        eh_e = bool(tr.categoria.essencial)
                    else:
                        eh_e = True
                    if eh_e:
                        desp_essencial_ant -= valor
                    else:
                        desp_discricionario_ant -= valor
                elif tr.tipo == "Receita":
                    receitas_anteriores += valor
                else:
                    despesas_anteriores += valor
                    if tr.essencial_override is not None:
                        eh_e = bool(tr.essencial_override)
                    elif tr.categoria and tr.categoria.essencial is not None:
                        eh_e = bool(tr.categoria.essencial)
                    else:
                        eh_e = True
                    if eh_e:
                        desp_essencial_ant += valor
                    else:
                        desp_discricionario_ant += valor
    elif mes_anterior:
        n_ant = db.query(func.count(Transacao.id)).filter(
            Transacao.mes_referencia == mes_anterior
        ).scalar() or 0
        if n_ant > 0:
            tem_mes_anterior = True
            base_ant = db.query(Transacao).filter(Transacao.mes_referencia == mes_anterior)
            base_ant = base_ant.filter((Transacao.dividida == False) | Transacao.dividida.is_(None))
            if not incluir_especiais:
                base_ant = base_ant.filter(Transacao.movimentacao.is_(None))
                if ids_especiais:
                    base_ant = base_ant.filter(
                        ~Transacao.categoria_id.in_(ids_especiais) | Transacao.categoria_id.is_(None)
                    )
            for tr in base_ant.options(joinedload(Transacao.categoria)).all():
                valor = tr.valor or 0.0
                if _eh_abatedora(tr):
                    despesas_anteriores -= valor
                    if tr.essencial_override is not None:
                        eh_e = bool(tr.essencial_override)
                    elif tr.categoria and tr.categoria.essencial is not None:
                        eh_e = bool(tr.categoria.essencial)
                    else:
                        eh_e = True
                    if eh_e:
                        desp_essencial_ant -= valor
                    else:
                        desp_discricionario_ant -= valor
                elif tr.tipo == "Receita":
                    receitas_anteriores += valor
                else:
                    despesas_anteriores += valor
                    if tr.essencial_override is not None:
                        eh_e = bool(tr.essencial_override)
                    elif tr.categoria and tr.categoria.essencial is not None:
                        eh_e = bool(tr.categoria.essencial)
                    else:
                        eh_e = True
                    if eh_e:
                        desp_essencial_ant += valor
                    else:
                        desp_discricionario_ant += valor

    # === Investimentos do mês: Compras + Aportes - Resgates ===
    # Usa data da operação (não mes_referencia) — investimentos não têm mes_ref.
    def _calcular_investido_range(di_obj_local, df_obj_local) -> float:
        if not di_obj_local or not df_obj_local:
            return 0.0
        ops = db.query(OperacaoInvestimento).filter(
            OperacaoInvestimento.data >= di_obj_local,
            OperacaoInvestimento.data <= df_obj_local,
            OperacaoInvestimento.tipo.in_(["Compra", "Aporte", "Resgate"]),
        ).all()
        total = 0.0
        for op in ops:
            valor_brl = (op.valor_total or 0) * (op.cotacao_cambio or 1)
            if op.tipo in ("Compra", "Aporte"):
                total += valor_brl
            elif op.tipo == "Resgate":
                total -= valor_brl
        return total

    def _calcular_investido(mes_str: str) -> float:
        if not mes_str or "/" not in mes_str:
            return 0.0
        try:
            mm, yyyy = mes_str.split("/")
            mm, yyyy = int(mm), int(yyyy)
        except (ValueError, TypeError):
            return 0.0
        from datetime import date as _d
        from calendar import monthrange as _mr
        dia_inicio = _d(yyyy, mm, 1)
        dia_fim = _d(yyyy, mm, _mr(yyyy, mm)[1])
        return _calcular_investido_range(dia_inicio, dia_fim)

    if modo_periodo:
        investido_mes = _calcular_investido_range(di_obj, df_obj)
        investido_mes_anterior = _calcular_investido_range(di_ant_obj, df_ant_obj)
    else:
        investido_mes = _calcular_investido(mes)
        investido_mes_anterior = _calcular_investido(mes_anterior) if mes_anterior else 0.0

    # === Resumo de empréstimos a terceiros (saldo a receber, ACUMULADO) ===
    # Saldo de empréstimo é cumulativo ("quanto fulano ainda me deve") — não pode
    # ser cortado pelo período, senão um empréstimo que começou antes do recorte
    # (ex.: compras de dez/2025 que caem na fatura de jan/2026) fica de fora e o
    # saldo aparece errado. Por isso calculamos sobre TODO o histórico.
    cat_emprestimos = db.query(Categoria).filter(
        Categoria.nome == "Empréstimos a Terceiros"
    ).first()
    emprestimos_resumo = {
        "emprestado": 0.0,    # despesas: dinheiro saiu emprestado
        "recebido": 0.0,      # receitas: dinheiro recebido de volta
        "saldo": 0.0,         # emprestado - recebido = a receber
        "por_pessoa": [],
    }
    if cat_emprestimos:
        q_emp = db.query(Transacao).filter(
            Transacao.categoria_id == cat_emprestimos.id,
            (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
            (Transacao.dividida == False) | Transacao.dividida.is_(None),
        )
        emprestimos_lista = q_emp.options(joinedload(Transacao.atribuicao)).all()
        # Agrupa por pessoa
        por_pessoa = {}
        for t in emprestimos_lista:
            chave = t.atribuicao.nome if t.atribuicao else "— sem atribuição —"
            if chave not in por_pessoa:
                por_pessoa[chave] = {"emprestado": 0, "recebido": 0}
            if t.tipo == "Despesa":
                por_pessoa[chave]["emprestado"] += t.valor or 0
                emprestimos_resumo["emprestado"] += t.valor or 0
            elif t.tipo == "Receita":
                por_pessoa[chave]["recebido"] += t.valor or 0
                emprestimos_resumo["recebido"] += t.valor or 0
        emprestimos_resumo["saldo"] = emprestimos_resumo["emprestado"] - emprestimos_resumo["recebido"]
        emprestimos_resumo["por_pessoa"] = [
            {"nome": k, "emprestado": v["emprestado"], "recebido": v["recebido"], "saldo": v["emprestado"] - v["recebido"]}
            for k, v in por_pessoa.items()
            if (v["emprestado"] + v["recebido"]) > 0
        ]
        emprestimos_resumo["por_pessoa"].sort(key=lambda x: x["saldo"], reverse=True)

    # Saldo geral (caixa): tudo que entrou e saiu no período — receitas, despesas,
    # empréstimos (recebido−concedido) e investimentos (resgatado−aplicado).
    emp_liquido = emp_recebido - emp_concedido          # + recebeu mais do que emprestou
    inv_liquido_caixa = inv_resgatado - inv_aplicado     # - aplicou mais do que resgatou
    saldo_geral = (receitas - despesas) + emp_liquido + inv_liquido_caixa

    return {
        "mes": mes,
        "meses_disponiveis": meses,
        "receitas": receitas,
        "despesas": despesas,
        "saldo": receitas - despesas,
        # Saldo geral (caixa) + componentes do período
        "saldo_geral": round(saldo_geral, 2),
        "fluxo_emprestimos": {"recebido": round(emp_recebido, 2), "concedido": round(emp_concedido, 2),
                              "liquido": round(emp_liquido, 2)},
        "fluxo_investimentos": {"resgatado": round(inv_resgatado, 2), "aplicado": round(inv_aplicado, 2),
                                "liquido": round(inv_liquido_caixa, 2)},
        # Essencial vs Discricionário do mês atual
        "despesas_essenciais": desp_essencial,
        "despesas_discricionarias": desp_discricionario,
        # Comparativo com mês anterior
        "mes_anterior": mes_anterior,
        "tem_mes_anterior": tem_mes_anterior,
        "receitas_anteriores": receitas_anteriores,
        "despesas_anteriores": despesas_anteriores,
        "despesas_essenciais_anteriores": desp_essencial_ant,
        "despesas_discricionarias_anteriores": desp_discricionario_ant,
        "saldo_anterior": receitas_anteriores - despesas_anteriores,
        # Investimentos do mês (Compras + Aportes - Resgates, em BRL)
        "investido_mes": investido_mes,
        "investido_mes_anterior": investido_mes_anterior,
        # Resumo de empréstimos a terceiros
        "emprestimos": emprestimos_resumo,
        # Modo período (datas) ou modo mês
        "modo_periodo": modo_periodo,
        "data_inicio": data_inicio if modo_periodo else None,
        "data_fim": data_fim if modo_periodo else None,
        "totais_especiais": totais_especiais,
        "incluir_especiais": incluir_especiais,
        "n_nao_categorizadas": nao_cat,
        "n_nao_atribuidas": nao_atr,
        "por_categoria": [
            {"nome": n, "icone": i, "total": v} for n, i, v in rows_cat
        ],
        "por_atribuicao": [
            {"nome": n, "tipo": t, "cor": c, "total": v} for n, t, c, v in rows_atr
        ],
        "por_banco": [
            {"nome": n, "total": v} for n, v in rows_banco
        ],
        "por_forma": [
            {"nome": n or "?", "total": v} for n, v in rows_forma
        ],
    }


@router.get("/api/dashboard/evolucao")
def evolucao_mensal(meses: int = 12, incluir_especiais: bool = False,
                    regime: str = "pagamento", db: Session = Depends(get_db)):
    """Retorna receitas e despesas mês a mês, ordenadas cronologicamente.
    `regime`: "pagamento" agrupa pelo mês de pagamento (caixa); "emissao" pelo mês
    da compra."""
    NOMES_ESPECIAIS = [
        "Empréstimos a Terceiros",
        "Investimentos",
    ]
    cats_esp = db.query(Categoria).filter(Categoria.nome.in_(NOMES_ESPECIAIS)).all()
    ids_esp = [c.id for c in cats_esp]

    regime = (regime or "pagamento").lower()
    if regime not in ("pagamento", "emissao"):
        regime = "pagamento"
    campo_data = (func.coalesce(Transacao.data_pagamento, Transacao.data)
                  if regime == "pagamento" else Transacao.data)
    mes_chave = func.strftime("%m/%Y", campo_data)   # "MM/YYYY" do regime escolhido

    q = db.query(
        mes_chave,
        Transacao.tipo,
        func.sum(Transacao.valor),
    ).filter((Transacao.dividida == False) | Transacao.dividida.is_(None))
    if not incluir_especiais:
        q = q.filter(Transacao.movimentacao.is_(None))
        if ids_esp:
            q = q.filter(
                ~Transacao.categoria_id.in_(ids_esp) | Transacao.categoria_id.is_(None)
            )
    rows = q.group_by(mes_chave, Transacao.tipo).all()

    # rows: lista de (mes_ref "MM/YYYY", tipo, total)
    por_mes = {}
    for mes, tipo, total in rows:
        if not mes:
            continue
        por_mes.setdefault(mes, {"receitas": 0, "despesas": 0})
        if tipo == "Receita":
            por_mes[mes]["receitas"] += total or 0
        else:
            por_mes[mes]["despesas"] += total or 0

    # Ordena por (ano, mês)
    def _key(m):
        try:
            mm, aa = m.split("/")
            return (int(aa), int(mm))
        except Exception:
            return (0, 0)

    meses_ord = sorted(por_mes.keys(), key=_key)[-meses:]
    return {
        "labels": meses_ord,
        "receitas": [round(por_mes[m]["receitas"], 2) for m in meses_ord],
        "despesas": [round(por_mes[m]["despesas"], 2) for m in meses_ord],
    }


@router.get("/api/dashboard/previsao")
def previsao_parcelas(meses: int = 6, db: Session = Depends(get_db)):
    """
    Projeta valores comprometidos nos próximos N meses baseado em parcelas
    já compradas que ainda não venceram.

    Lógica:
      - Pega cada transação com parcela tipo "X/Y" onde X < Y
      - Calcula quantas parcelas faltam = Y - X
      - Cria projeções: mês_atual+1, mês_atual+2, ... até a Y
    """
    from datetime import date as _date
    import re as _re

    hoje = _date.today()
    base_ano = hoje.year
    base_mes = hoje.month

    # Coleta transações com parcela.
    # IMPORTANTE: filtra suspeitas de duplicata pra não inflar projeção.
    trans = db.query(Transacao).options(
        joinedload(Transacao.categoria),
        joinedload(Transacao.atribuicao),
        joinedload(Transacao.conta),
    ).filter(
        Transacao.parcela.isnot(None),
        Transacao.parcela != "",
        Transacao.tipo == "Despesa",
        (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
    ).all()

    re_parc = _re.compile(r"(\d+)\s*/\s*(\d+)")

    # ============================================================
    # Dedup por compra: agrupa transações da mesma compra (que aparece em
    # múltiplas faturas conforme as parcelas avançam).
    #
    # Estratégia em 2 passos:
    #   1. Agrupa por (total_parcelas, conta) — mesma compra obrigatoriamente
    #      tem mesmo número de parcelas
    #   2. Dentro do grupo, mescla itens com descrição SIMILAR (>=85% match)
    #      e valor próximo (tolerância 10% ou R$ 5,00) — alguns parcelamentos
    #      variam centavos entre parcelas, e o parser pode ler a descrição
    #      ligeiramente diferente em faturas distintas (encoding, OCR).
    # ============================================================
    import re as _re_alfa
    from difflib import SequenceMatcher

    def _desc_chave(desc: str) -> str:
        # Reduz a alfanuméricos uppercase, trunca em 30 chars
        return _re_alfa.sub(r'[^A-Za-z0-9]', '', (desc or "")).upper()[:30]

    def _similares(a: str, b: str) -> bool:
        """True se as descrições são quase idênticas (>= 88% match), considerando
        que parsers de PDF/OCR podem variar 1-2 caracteres na leitura."""
        if not a or not b:
            return False
        if a == b:
            return True
        # Diferença de tamanho grande = compras distintas (ex: "Home Cinema" vs "Receiver Home Cinema")
        if abs(len(a) - len(b)) > 2:
            return SequenceMatcher(None, a, b).ratio() >= 0.95
        # Tamanhos próximos: aceita 88% (cobre 1-2 chars diferentes em palavras de 8-25 chars)
        return SequenceMatcher(None, a, b).ratio() >= 0.88

    # Passo 1: agrupa por (total, conta) — agrupar amplo, depois filtrar por similaridade
    grupos = {}  # (total, conta_id) -> lista de (atual, valor, desc_chave, transacao)
    for t in trans:
        m = re_parc.match(t.parcela or "")
        if not m:
            continue
        try:
            atual = int(m.group(1))
            total = int(m.group(2))
        except ValueError:
            continue

        desc_chave_t = _desc_chave(t.descricao_normalizada or t.descricao)
        grupos.setdefault((total, t.conta_id), []).append(
            (atual, t.valor or 0, desc_chave_t, t)
        )

    # Passo 2: dentro de cada grupo, mescla por similaridade de descrição + valor
    compras_unicas = []  # lista de (atual_max, transacao_representante)
    for grupo, itens in grupos.items():
        # Ordena por valor pra agrupar similares
        itens_sorted = sorted(itens, key=lambda x: x[1])
        clusters = []  # cada cluster: lista de (atual, valor, desc, t)
        for it in itens_sorted:
            _, valor, desc_chave_t, _ = it
            # Tenta encaixar em algum cluster existente
            encaixou = False
            for c in clusters:
                ref_valor = c[0][1]
                ref_desc = c[0][2]
                # Tolerância de 10% do valor ou R$ 5 (o que for maior)
                tolerancia = max(ref_valor * 0.10, 5.0)
                if abs(valor - ref_valor) <= tolerancia and _similares(ref_desc, desc_chave_t):
                    c.append(it)
                    encaixou = True
                    break
            if not encaixou:
                clusters.append([it])

        for cluster in clusters:
            atual_max, _, _, t_repr = max(cluster, key=lambda x: x[0])
            compras_unicas.append((atual_max, t_repr))

    # Estrutura: por mês alvo, lista de parcelas projetadas
    por_mes = {}  # "MM/YYYY" -> {total, n, items: [...]}

    for atual, t in compras_unicas:
        m = re_parc.match(t.parcela or "")
        try:
            atual = int(m.group(1))
            total = int(m.group(2))
        except (ValueError, AttributeError):
            continue
        if total <= atual:
            continue  # já é a última, não há futuras

        # mes_referencia da transação base = "MM/YYYY"
        try:
            mm, yy = t.mes_referencia.split("/")
            ref_mes, ref_ano = int(mm), int(yy)
        except (ValueError, AttributeError):
            continue

        # Para cada parcela futura
        faltam = total - atual
        for i in range(1, faltam + 1):
            novo_mes = ref_mes + i
            novo_ano = ref_ano
            while novo_mes > 12:
                novo_mes -= 12
                novo_ano += 1
            chave = f"{novo_mes:02d}/{novo_ano}"

            # só projeta meses futuros (estritamente — não inclui o mês atual)
            if (novo_ano, novo_mes) <= (base_ano, base_mes):
                continue
            # limita ao número de meses pedidos
            diff_meses = (novo_ano - base_ano) * 12 + (novo_mes - base_mes)
            if diff_meses < 1 or diff_meses > meses:
                continue

            por_mes.setdefault(chave, {"mes": chave, "total": 0, "n": 0, "items": []})
            por_mes[chave]["total"] += t.valor
            por_mes[chave]["n"] += 1
            # Limita itens detalhados a 100 por mês
            if len(por_mes[chave]["items"]) < 100:
                por_mes[chave]["items"].append({
                    "descricao": t.descricao_personalizada or t.descricao,
                    "valor": t.valor,
                    "parcela_atual_no_futuro": f"{atual + i:02d}/{total:02d}",
                    "categoria": t.categoria.nome if t.categoria else None,
                    "icone": t.categoria.icone if t.categoria else None,
                    "conta": t.conta.nome if t.conta else None,
                    "transacao_origem_id": t.id,
                })

    # Ordena por mês (cronológico)
    def _key(ch):
        mm, yy = ch.split("/")
        return (int(yy), int(mm))

    items = sorted(por_mes.values(), key=lambda x: _key(x["mes"]))
    return {"meses": items}
