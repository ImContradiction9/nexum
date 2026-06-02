"""
Service de importação. É o que a UI chama quando o usuário sobe um arquivo.

Suporta:
  - PDF de fatura (cartão de crédito): Nubank, Bradesco, Santander, Mercado Pago
  - OFX de extrato (conta corrente): qualquer banco que exporte OFX padrão

Para PDF: dedup por hash do arquivo + hash de cada transação.
Para OFX: dedup por hash do arquivo + FITID (ID único do banco) por transação.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session

from .database import Conta, Categoria, Fatura, Transacao
from .parsers import parse_fatura
from .parsers.ofx import parse_extrato_ofx
from .parsers.helpers import PDFProtegido, PDFToTextNaoEncontrado
from .categorizacao import classificar, carregar_regras_ativas, parcelas_irmas, vincular_estorno
from .utils import hash_pdf, hash_dedup, normalizar_descricao


@dataclass
class ResultadoImportacao:
    sucesso: bool
    banco: str = ""
    mes_referencia: str = ""
    fatura_id: Optional[int] = None
    n_transacoes_inseridas: int = 0
    n_transacoes_duplicadas: int = 0  # legado: descartadas. Agora 0 por padrão.
    n_transacoes_suspeitas: int = 0   # marcadas como possível duplicata pra revisão
    n_categorizadas: int = 0
    valor_total: float = 0
    erro: str = ""
    ja_importado: bool = False
    precisa_senha: bool = False
    senha_funcionou: Optional[str] = None
    # Ambiguidade de conta (múltiplas contas-corrente do mesmo banco)
    ambiguidade_conta: bool = False
    contas_candidatas: list = None


# Mapa banco → nome canônico da conta CARTÃO DE CRÉDITO (faturas)
BANCO_TO_CONTA_CREDITO = {
    "Nubank":       "Nubank Crédito",
    "Bradesco":     "Bradesco Crédito",
    "Santander":    "Santander Crédito",
    "Mercado Pago": "Mercado Pago Crédito",
}

# Mapa banco → nome canônico da conta CORRENTE (extratos OFX)
BANCO_TO_CONTA_CORRENTE = {
    "Nubank":          "Nubank Conta",
    "Bradesco":        "Bradesco Conta",
    "Santander":       "Santander Conta",
    "Banco do Brasil": "Banco do Brasil",
    "Itaú":            "Itaú Conta",
    "Caixa":           "Caixa Conta",
    "Inter":           "Inter Conta",
    "Mercado Pago":    "Mercado Pago Conta",
}

# Compat
BANCO_TO_CONTA_NOME = BANCO_TO_CONTA_CREDITO


def _tentar_parse(pdf_path: str, senhas_para_tentar: list) -> tuple:
    """
    Tenta parsear o PDF com cada senha da lista (None primeiro = sem senha).
    Retorna (bill, senha_que_funcionou) ou levanta PDFProtegido se nenhuma funcionar.
    """
    erros = []
    for senha in senhas_para_tentar:
        try:
            bill = parse_fatura(pdf_path, senha=senha)
            return bill, senha
        except PDFProtegido as e:
            erros.append(str(e))
            continue
        # Outras exceções (parsing, banco não detectado etc) sobem direto
    # Se chegou aqui, todas as tentativas deram PDFProtegido
    raise PDFProtegido(f"PDF protegido — nenhuma das senhas testadas funcionou.")


def importar_pdf(
    session: Session,
    pdf_path: str,
    senha: Optional[str] = None,
    conta_id_override: Optional[int] = None,
) -> ResultadoImportacao:
    """
    Importa um PDF de fatura. Idempotente (não duplica).
    Se o PDF estiver protegido, tenta:
      1. sem senha
      2. cada senha cadastrada nas Contas
      3. senha explícita (se fornecida)
    Se nenhuma funcionar, retorna precisa_senha=True.
    """
    pdf_path_obj = Path(pdf_path)
    if not pdf_path_obj.exists():
        return ResultadoImportacao(sucesso=False, erro=f"PDF não encontrado: {pdf_path}")

    # 1. Hash do PDF
    h_pdf = hash_pdf(str(pdf_path_obj))
    fatura_existente = session.query(Fatura).filter(
        Fatura.pdf_hash == h_pdf
    ).first()
    if fatura_existente:
        return ResultadoImportacao(
            sucesso=True,
            ja_importado=True,
            banco=fatura_existente.banco,
            mes_referencia=fatura_existente.mes_referencia,
            fatura_id=fatura_existente.id,
            erro="PDF já foi importado anteriormente.",
        )

    # 2. Parse — tenta sem senha, depois cada senha cadastrada, depois senha explícita
    senhas_para_tentar = [None]  # primeiro tenta sem senha
    senhas_cadastradas = [
        c.senha_pdf for c in session.query(Conta).filter(
            Conta.senha_pdf.isnot(None), Conta.senha_pdf != ""
        ).all()
    ]
    senhas_para_tentar.extend(senhas_cadastradas)
    if senha and senha not in senhas_para_tentar:
        senhas_para_tentar.append(senha)

    try:
        bill, senha_usada = _tentar_parse(str(pdf_path_obj), senhas_para_tentar)
    except PDFProtegido:
        return ResultadoImportacao(
            sucesso=False,
            precisa_senha=True,
            erro="PDF protegido por senha. Forneça a senha para importar.",
        )
    except PDFToTextNaoEncontrado as e:
        return ResultadoImportacao(sucesso=False, erro=str(e))
    except Exception as e:
        return ResultadoImportacao(
            sucesso=False,
            erro=f"Erro ao parsear PDF: {e}",
        )

    banco = bill["banco"]
    mes_ref = bill["mes_ref"]

    # Localiza conta (cartão de crédito) do banco. Se houver várias, exige escolha.
    if conta_id_override:
        conta = session.query(Conta).filter(Conta.id == conta_id_override).first()
        if conta is None:
            return ResultadoImportacao(
                sucesso=False,
                erro=f"Conta selecionada (id={conta_id_override}) não existe.",
            )
    else:
        candidatos = session.query(Conta).filter(
            Conta.tipo == "Cartão de Crédito",
            Conta.ativo == True,
        ).all()
        candidatos_banco = [
            c for c in candidatos
            if ((c.banco_obj.nome if c.banco_obj else c.banco) or "") == banco
        ]
        if len(candidatos_banco) == 0:
            # Fallback ao nome canônico antigo (pré-titular)
            conta_nome = BANCO_TO_CONTA_NOME.get(banco)
            conta = (
                session.query(Conta).filter(Conta.nome == conta_nome).first()
                if conta_nome else None
            )
            if conta is None:
                return ResultadoImportacao(
                    sucesso=False,
                    erro=f"Nenhuma conta de Cartão de Crédito do {banco} cadastrada. "
                         f"Crie em Configurações → Contas (tipo: Cartão de Crédito, Banco: {banco}).",
                )
        elif len(candidatos_banco) == 1:
            conta = candidatos_banco[0]
        else:
            return ResultadoImportacao(
                sucesso=False,
                ambiguidade_conta=True,
                contas_candidatas=[
                    {"id": c.id, "nome": c.nome, "titular": c.titular or "(você)"}
                    for c in candidatos_banco
                ],
                banco=banco,
                erro=f"Existem {len(candidatos_banco)} cartões de crédito do {banco}. Selecione qual receberá a fatura.",
            )

    # Se uma senha explícita foi fornecida e funcionou (e não é igual à já cadastrada),
    # retorna pra UI oferecer salvar
    senha_para_oferecer = None
    if senha_usada and senha_usada == senha and senha_usada != conta.senha_pdf:
        senha_para_oferecer = senha_usada

    # 3. Cria fatura
    valor_total = sum(t["valor"] for t in bill["transacoes"])
    fatura = Fatura(
        banco=banco,
        conta_id=conta.id,
        mes_referencia=mes_ref,
        data_vencimento=bill.get("vencimento"),
        periodo_inicio=bill.get("periodo_inicio"),
        periodo_fim=bill.get("periodo_fim"),
        total=valor_total,
        pdf_filename=pdf_path_obj.name,
        pdf_hash=h_pdf,
    )
    session.add(fatura)
    session.flush()

    # 4. Insere transações com dedup e classificação
    n_inseridas = 0
    n_dups = 0
    n_categorizadas = 0
    n_suspeitas = 0  # transações inseridas com flag suspeita_duplicata=True

    regras_ativas = carregar_regras_ativas(session)   # uma vez, fora do loop

    for t in bill["transacoes"]:
        h_dedup = hash_dedup(banco, t["data_compra"], t["valor"], t["descricao"], t.get("parcela"))
        # Hash legado (versão antiga sem parcela) — ainda existem no banco. Compatibilidade.
        h_dedup_legado = hash_dedup(banco, t["data_compra"], t["valor"], t["descricao"])

        existente = session.query(Transacao).filter(
            Transacao.hash_dedup.in_([h_dedup, h_dedup_legado]),
            Transacao.conta_id == conta.id,
        ).first()

        # Decide se é suspeita de duplicata
        eh_suspeita = False
        if existente:
            # Se a parcela é diferente, NÃO é duplicata (é outra parcela da mesma compra)
            mesmo_parcela = (existente.parcela or "") == (t.get("parcela") or "")
            if mesmo_parcela:
                # Mesma parcela + mesmo hash = candidata a duplicata.
                # Insere como suspeita pra usuário revisar (em vez de descartar como antes).
                eh_suspeita = True

        classif = classificar(session, t["descricao"], regras=regras_ativas)

        # Tipo da transação: Receita se o parser marcar (cashback), senão Despesa
        tipo_trans = t.get("tipo", "Despesa")

        trans = Transacao(
            fatura_id=fatura.id,
            conta_id=conta.id,
            data=t["data_compra"],
            descricao=t["descricao"],
            descricao_normalizada=normalizar_descricao(t["descricao"]),
            valor=t["valor"],
            tipo=tipo_trans,
            forma_pagamento="Crédito",
            parcela=t.get("parcela"),
            mes_referencia=mes_ref,
            categoria_id=classif.categoria_id,
            categoria_origem=classif.categoria_origem,
            atribuicao_id=classif.atribuicao_id,
            atribuicao_origem=classif.atribuicao_origem,
            cartao_final=t.get("cartao_final4"),
            hash_dedup=h_dedup,
            observacoes=f"Fatura {banco} {mes_ref}",
            suspeita_duplicata=eh_suspeita,
        )

        # Se for parcelada e já existe irmã classificada manualmente,
        # herda dela (categoria + atribuição + descrição personalizada).
        # Memória já cobre os 2 primeiros, mas descrição_personalizada não.
        if trans.parcela and "/" in (trans.parcela or ""):
            session.add(trans)
            session.flush()  # precisa ter id pra parcelas_irmas funcionar
            irmas = parcelas_irmas(session, trans)
            if irmas:
                fonte = next(
                    (i for i in irmas if i.descricao_personalizada
                                       or i.categoria_origem == "manual"
                                       or i.atribuicao_origem == "manual"),
                    None,
                )
                if fonte:
                    if trans.categoria_id is None and fonte.categoria_id:
                        trans.categoria_id = fonte.categoria_id
                        trans.categoria_origem = "manual"
                    if trans.atribuicao_id is None and fonte.atribuicao_id:
                        trans.atribuicao_id = fonte.atribuicao_id
                        trans.atribuicao_origem = "manual"
                    if not trans.descricao_personalizada and fonte.descricao_personalizada:
                        trans.descricao_personalizada = fonte.descricao_personalizada
        else:
            session.add(trans)

        n_inseridas += 1
        if eh_suspeita:
            n_suspeitas += 1
        if trans.categoria_id is not None:
            n_categorizadas += 1

    session.flush()

    # Detecta estornos: pra cada Receita inserida agora, tenta achar a Despesa
    # original (mesma conta, mesma descrição, valor próximo, dentro da janela).
    # Se achar, vincula e copia categoria/atribuição.
    for trans in session.query(Transacao).filter(
        Transacao.fatura_id == fatura.id,
        Transacao.tipo == "Receita",
        Transacao.estorno_de_id.is_(None),
    ).all():
        vincular_estorno(session, trans)
    session.flush()

    return ResultadoImportacao(
        sucesso=True,
        banco=banco,
        mes_referencia=mes_ref,
        fatura_id=fatura.id,
        n_transacoes_inseridas=n_inseridas,
        n_transacoes_duplicadas=n_dups,
        n_transacoes_suspeitas=n_suspeitas,
        n_categorizadas=n_categorizadas,
        valor_total=valor_total,
        senha_funcionou=senha_para_oferecer,
    )


# ============================================================
# IMPORTAÇÃO DE EXTRATO OFX
# ============================================================

# Palavras-chave que indicam pagamento de fatura de cartão.
# Quando uma transação no extrato bate isso, ela recebe categoria
# especial "Pagamento de Fatura" para não duplicar com a fatura em si.
KEYWORDS_PAGAMENTO_FATURA = [
    "pagamento de fatura",
    "pgto fatura",
    "pgto. fatura",
    "fatura cartao",
    "fatura cartão",
    "pagto fatura",
    "banco ibi",      # IBI = Bradescard / Bradesco fatura cartão
    "bradescard",
    "pgto cartao",
    "pgto. cartao",
    "pagto cartao",
    "pagamento cartao credito",
]

# Instituições financeiras que aparecem como contraparte em Pix mas
# representam transferência interna entre suas contas (recarga / pagamento).
# Quando o destino/origem do Pix é uma dessas, marcamos como
# "Transferência entre Contas" (fora dos totais).
KEYWORDS_TRANSFERENCIA_INTERCONTA = [
    "mercado pago institui",      # Pix pra conta MP = recarga/pgto
    "mercado pago ip",
    "nu pagamentos",              # Pix entre Nubank e outra conta sua
    "pagseguro",
    "picpay",
    "stone instituicao",
    "rede instituicao",
]

# Descrições genéricas que indicam cashback de cartão de crédito.
# No Nubank é "Crédito em conta" com valor pequeno.
KEYWORDS_CASHBACK = [
    "credito em conta",
    "crédito em conta",
    "cashback",
    "cash back",
    "credito de pontos",
    "crédito de pontos",
    "estorno de pontos",
    "rewards",
]


def _eh_pagamento_fatura(descricao: str, forma_pagamento: str) -> bool:
    """Detecta se uma transação de extrato é pagamento de fatura de cartão."""
    desc_lower = (descricao or "").lower()
    forma_lower = (forma_pagamento or "").lower()
    if "pagamento de fatura" in forma_lower:
        return True
    return any(k in desc_lower for k in KEYWORDS_PAGAMENTO_FATURA)


def _eh_transferencia_interconta(descricao: str, nomes_familia: list = None) -> bool:
    """
    Detecta se uma transação é transferência entre contas próprias OU entre
    membros da família (conta efetivamente compartilhada).

    Heurísticas:
      1. Descrição contém o nome de alguém da família (Pix entre vocês)
      2. Contraparte é instituição financeira de conta digital (MP, PicPay, etc.)

    A detecção #1 exige pelo menos 2 partes do nome em comum (evita falso positivo
    com pessoas de mesmo primeiro nome — ex: "Micael Calçados Ltda" não bate
    com "Micael Italo da Silva Salvador" porque só "Micael" é comum).
    """
    desc_lower = (descricao or "").lower()

    # 1. Nome de alguém da família aparece como remetente/destinatário
    for nome in (nomes_familia or []):
        if not nome:
            continue
        partes = [p.lower() for p in nome.split() if len(p) >= 4]
        # Precisa bater pelo menos 2 partes do nome
        matches = sum(1 for p in partes if p in desc_lower)
        if matches >= 2:
            return True

    # 2. Contraparte é instituição financeira / conta digital
    return any(k in desc_lower for k in KEYWORDS_TRANSFERENCIA_INTERCONTA)


def _eh_cashback(descricao: str, valor: float, tipo: str) -> bool:
    """Detecta cashback. Só aplica em receitas (entradas)."""
    if tipo != "Receita":
        return False
    desc_lower = (descricao or "").lower()
    return any(k in desc_lower for k in KEYWORDS_CASHBACK)


def importar_ofx(session: Session, ofx_path: str, conta_id_override: int = None) -> ResultadoImportacao:
    """
    Importa um extrato OFX. Idempotente.

    Diferença pro PDF:
      - Dedup por FITID (ID único do banco) — mais confiável que hash
      - Vai pra conta corrente (não cartão de crédito)
      - Detecta pagamento de fatura automaticamente
    """
    ofx_path_obj = Path(ofx_path)
    if not ofx_path_obj.exists():
        return ResultadoImportacao(sucesso=False, erro=f"OFX não encontrado: {ofx_path}")

    # 1. Hash do arquivo (anti-reimportação)
    h_arquivo = hash_pdf(str(ofx_path_obj))  # mesma função, funciona pra qualquer arquivo
    fatura_existente = session.query(Fatura).filter(
        Fatura.pdf_hash == h_arquivo
    ).first()
    if fatura_existente:
        return ResultadoImportacao(
            sucesso=True,
            ja_importado=True,
            banco=fatura_existente.banco,
            mes_referencia=fatura_existente.mes_referencia,
            fatura_id=fatura_existente.id,
            erro="Arquivo já foi importado anteriormente.",
        )

    # 2. Parse
    try:
        bill = parse_extrato_ofx(str(ofx_path_obj))
    except Exception as e:
        return ResultadoImportacao(sucesso=False, erro=f"Erro ao parsear OFX: {e}")

    banco = bill["banco"]
    transacoes = bill["transacoes"]
    if not transacoes:
        return ResultadoImportacao(
            sucesso=False,
            erro="OFX não contém transações.",
        )

    # Mês de referência: usa o mês da última transação (período fechado)
    ultima = max(t["data"] for t in transacoes)
    mes_ref = f"{ultima.month:02d}/{ultima.year}"

    # 3. Encontra a conta corrente do banco
    # Aceita conta_id explícito (frontend escolheu) ou tenta resolver automaticamente
    if conta_id_override:
        conta = session.query(Conta).filter(Conta.id == conta_id_override).first()
        if conta is None:
            return ResultadoImportacao(
                sucesso=False,
                erro=f"Conta selecionada (id={conta_id_override}) não existe.",
            )
    else:
        # Busca todas contas-corrente do banco
        candidatos = session.query(Conta).filter(
            Conta.tipo == "Conta Corrente",
            Conta.ativo == True,
        )
        # Filtra pelo nome do banco (preferência: banco_obj, fallback: nome canônico)
        candidatos_banco = []
        for c in candidatos.all():
            nome_banco_da_conta = (c.banco_obj.nome if c.banco_obj else c.banco) or ""
            if nome_banco_da_conta == banco:
                candidatos_banco.append(c)

        if len(candidatos_banco) == 0:
            # Fallback: busca pelo nome canônico antigo (compat)
            conta_nome = BANCO_TO_CONTA_CORRENTE.get(banco)
            if conta_nome:
                conta = session.query(Conta).filter(Conta.nome == conta_nome).first()
            else:
                conta = None
            if conta is None:
                return ResultadoImportacao(
                    sucesso=False,
                    erro=f"Nenhuma conta corrente do {banco} cadastrada. "
                         f"Crie em Configurações → Contas (tipo: Conta Corrente, Banco: {banco}).",
                )
        elif len(candidatos_banco) == 1:
            # Única opção, usa direto
            conta = candidatos_banco[0]
        else:
            # AMBIGUIDADE: retorna erro especial pro frontend escolher
            return ResultadoImportacao(
                sucesso=False,
                ambiguidade_conta=True,
                contas_candidatas=[
                    {
                        "id": c.id,
                        "nome": c.nome,
                        "titular": c.titular or "(você)",
                    }
                    for c in candidatos_banco
                ],
                banco=banco,
                erro=f"Existem {len(candidatos_banco)} contas correntes do {banco}. Selecione qual receberá o extrato.",
            )

    # 4. Cria registro de Fatura (representa o "extrato importado")
    valor_total_entradas = sum(t["valor"] for t in transacoes if t["tipo"] == "Receita")
    valor_total_saidas   = sum(t["valor"] for t in transacoes if t["tipo"] == "Despesa")
    fatura = Fatura(
        banco=banco,
        conta_id=conta.id,
        mes_referencia=mes_ref,
        periodo_inicio=bill.get("periodo_inicio"),
        periodo_fim=bill.get("periodo_fim"),
        total=valor_total_saidas,        # total = saídas (pra ser comparável com fatura)
        saldo_inicial=bill.get("saldo_inicial"),
        saldo_final=bill.get("saldo_final"),
        pdf_filename=ofx_path_obj.name,
        pdf_hash=h_arquivo,
        observacoes=f"Extrato OFX | Entradas: R$ {valor_total_entradas:.2f} | "
                    f"Saídas: R$ {valor_total_saidas:.2f}",
    )
    session.add(fatura)
    session.flush()

    # 5. Categorias especiais (cria se não existirem)
    cat_pgto_fatura = session.query(Categoria).filter(
        Categoria.nome == "Pagamento de Fatura"
    ).first()
    if cat_pgto_fatura is None:
        cat_pgto_fatura = Categoria(
            nome="Pagamento de Fatura", tipo="Despesa", icone="💳", orcamento_mensal=0,
        )
        session.add(cat_pgto_fatura)
        session.flush()

    cat_transferencia = session.query(Categoria).filter(
        Categoria.nome == "Transferência entre Contas"
    ).first()
    if cat_transferencia is None:
        cat_transferencia = Categoria(
            nome="Transferência entre Contas", tipo="Despesa", icone="🔁", orcamento_mensal=0,
        )
        session.add(cat_transferencia)
        session.flush()

    cat_cashback = session.query(Categoria).filter(
        Categoria.nome == "Cashback"
    ).first()
    if cat_cashback is None:
        cat_cashback = Categoria(
            nome="Cashback", tipo="Receita", icone="🪙", orcamento_mensal=0,
        )
        session.add(cat_cashback)
        session.flush()

    # Lê nomes da família das configurações (pra detectar Pix interno)
    # Aceita: "nome_usuario" (o seu) + "familia_nomes" (lista separada por ;)
    from .database import Configuracao
    nomes_familia = []
    cfg_user = session.query(Configuracao).filter(Configuracao.chave == "nome_usuario").first()
    if cfg_user and cfg_user.valor:
        nomes_familia.append(cfg_user.valor)
    cfg_fam = session.query(Configuracao).filter(Configuracao.chave == "familia_nomes").first()
    if cfg_fam and cfg_fam.valor:
        # Lista separada por ; (uma pessoa por entrada)
        nomes_familia.extend([n.strip() for n in cfg_fam.valor.split(";") if n.strip()])

    # 6. Insere transações
    n_inseridas = 0
    n_dups = 0
    n_suspeitas = 0
    n_categorizadas = 0

    regras_ativas = carregar_regras_ativas(session)   # uma vez, fora do loop

    for t in transacoes:
        # Pula linhas de saldo inicial/abertura (valor zero, sem significado real)
        if t["valor"] == 0:
            continue

        fitid = t.get("fitid", "")
        # FITID inválido (alguns bancos como Santander preenchem com "000000",
        # "0", ou string vazia — não serve pra dedup, todos seriam iguais).
        # Nesses casos, cai pro hash genérico.
        fitid_invalido = (
            not fitid
            or fitid in ("000000", "0", "00000000", "1", "0000")
            or fitid.replace("0", "").strip() == ""
        )
        if fitid_invalido:
            fitid_dedup = hash_dedup(banco, t["data"], t["valor"], t["descricao"])
        else:
            fitid_dedup = fitid

        existente = session.query(Transacao).filter(
            Transacao.hash_dedup == fitid_dedup,
            Transacao.conta_id == conta.id,
        ).first()

        eh_suspeita = bool(existente)
        # Não descarta mais — insere como suspeita pra revisão manual

        # Detecções automáticas, em ordem de prioridade
        eh_pf = _eh_pagamento_fatura(t["descricao"], t.get("forma_pagamento", ""))
        eh_transf = _eh_transferencia_interconta(t["descricao"], nomes_familia)
        eh_cb = _eh_cashback(t["descricao"], t["valor"], t["tipo"])

        if eh_pf:
            categoria_id = cat_pgto_fatura.id
            categoria_origem = "automatica"
            atribuicao_id = None
            atribuicao_origem = "nao_categorizado"
        elif eh_transf:
            categoria_id = cat_transferencia.id
            categoria_origem = "automatica"
            atribuicao_id = None
            atribuicao_origem = "nao_categorizado"
        elif eh_cb:
            categoria_id = cat_cashback.id
            categoria_origem = "automatica"
            atribuicao_id = None
            atribuicao_origem = "nao_categorizado"
        else:
            classif = classificar(session, t["descricao"], regras=regras_ativas)
            categoria_id = classif.categoria_id
            categoria_origem = classif.categoria_origem
            atribuicao_id = classif.atribuicao_id
            atribuicao_origem = classif.atribuicao_origem

        mes_ref_trans = f"{t['data'].month:02d}/{t['data'].year}"

        trans = Transacao(
            fatura_id=fatura.id,
            conta_id=conta.id,
            data=t["data"],
            descricao=t["descricao"],
            descricao_normalizada=normalizar_descricao(t["descricao"]),
            valor=t["valor"],
            tipo=t["tipo"],
            forma_pagamento=t.get("forma_pagamento"),
            mes_referencia=mes_ref_trans,
            categoria_id=categoria_id,
            categoria_origem=categoria_origem,
            atribuicao_id=atribuicao_id,
            atribuicao_origem=atribuicao_origem,
            hash_dedup=fitid_dedup,
            observacoes=f"Extrato {banco} {mes_ref}",
            suspeita_duplicata=eh_suspeita,
        )
        session.add(trans)
        n_inseridas += 1
        if eh_suspeita:
            n_suspeitas += 1
        if categoria_id is not None:
            n_categorizadas += 1

    session.flush()

    # Detecta estornos para o OFX (extrato bancário)
    for trans in session.query(Transacao).filter(
        Transacao.fatura_id == fatura.id,
        Transacao.tipo == "Receita",
        Transacao.estorno_de_id.is_(None),
    ).all():
        vincular_estorno(session, trans)
    session.flush()

    return ResultadoImportacao(
        sucesso=True,
        banco=banco,
        mes_referencia=mes_ref,
        fatura_id=fatura.id,
        n_transacoes_inseridas=n_inseridas,
        n_transacoes_duplicadas=n_dups,
        n_transacoes_suspeitas=n_suspeitas,
        n_categorizadas=n_categorizadas,
        valor_total=valor_total_saidas,
    )


def importar_arquivo(
    session: Session,
    file_path: str,
    senha: Optional[str] = None,
    conta_id_override: Optional[int] = None,
) -> ResultadoImportacao:
    """
    Wrapper que detecta o tipo de arquivo e roteia para o importador correto.
      - .pdf → importar_pdf (fatura)
      - .ofx → importar_ofx (extrato)

    conta_id_override só faz sentido pra OFX — quando o usuário escolheu
    qual conta receberá o extrato (caso de ambiguidade).
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return importar_pdf(session, file_path, senha=senha, conta_id_override=conta_id_override)
    if ext == ".ofx":
        return importar_ofx(session, file_path, conta_id_override=conta_id_override)
    return ResultadoImportacao(
        sucesso=False,
        erro=f"Tipo de arquivo não suportado: {ext}. Use PDF (faturas) ou OFX (extratos).",
    )
