"""
Banco de dados — esquema completo do app financeiro.

Tabelas:
  contas          — contas correntes e cartões de crédito
  categorias      — categorias de despesa/receita
  atribuicoes     — pessoas e grupos (Micael, Andreina, Casa, Cachorros…)
  regras          — palavra-chave → categoria + atribuição automática
  faturas         — uma linha por PDF importado (rastreabilidade e dedup)
  transacoes      — toda transação (de fatura ou extrato)
  memoria         — memória de aprendizado: descrição → última correção do usuário
  divisoes        — quando uma transação é dividida com outra atribuição
  conciliacoes    — links entre transações conciliadas (ex.: pagamento ↔ fatura)
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean,
    ForeignKey, Text, UniqueConstraint, Index, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class Configuracao(Base):
    """Configurações chave-valor do app (nome do usuário, preferências, etc)."""
    __tablename__ = "configuracoes"
    chave = Column(String, primary_key=True)
    valor = Column(Text)


class Banco(Base):
    """Banco / instituição financeira. Agrupa contas (Conta, Crédito, Pix, etc.) de uma mesma instituição."""
    __tablename__ = "bancos"
    id = Column(Integer, primary_key=True)
    nome = Column(String, unique=True, nullable=False)         # "Nubank", "Bradesco", "Mercado Pago"
    cor = Column(String)                                        # hex para gráficos
    ativo = Column(Boolean, default=True)


class Conta(Base):
    """Conta corrente, cartão de crédito, carteira."""
    __tablename__ = "contas"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)                       # "Nubank" — pode repetir; uniqueness é por (banco_id, tipo, titular)
    tipo = Column(String, nullable=False)                       # "Cartão de Crédito" | "Conta Corrente" | "Pix" | "Carteira"
    banco_id = Column(Integer, ForeignKey("bancos.id"))         # nova FK para Banco
    banco = Column(String)                                      # MANTIDO por compat — nome em texto livre, deprecated
    dia_fechamento = Column(Integer)                            # Cartões só
    dia_vencimento = Column(Integer)                            # Cartões só
    final = Column(String)                                      # Últimos 4 dígitos do cartão
    senha_pdf = Column(String)                                  # Senha p/ abrir PDFs de fatura
    titular = Column(String)                                    # Nome do titular (vazio = você). Permite separar contas do mesmo banco entre membros da família
    # Saldo inicial manual: usado quando não há OFX do mês importado. O app calcula
    # o saldo a partir desta data + transações posteriores.
    saldo_inicial_manual = Column(Float)
    saldo_inicial_data = Column(Date)                           # data a partir da qual o saldo manual vale
    data_inicio_uso = Column(Date)                              # mês a partir do qual a conta passou a ser usada (anteriores = "não se aplica" no mapa de cobertura)
    ativo = Column(Boolean, default=True)
    observacoes = Column(Text)

    banco_obj = relationship("Banco")


class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True)
    nome = Column(String, unique=True, nullable=False)
    tipo = Column(String, nullable=False)                       # "Despesa" | "Receita"
    orcamento_mensal = Column(Float, default=0)
    # "Entra no orçamento": o usuário escolhe quais categorias acompanhar no
    # Orçamento (previsíveis sim, esporádicas não) — independente de ter teto.
    orcado = Column(Boolean, default=False)
    ativo = Column(Boolean, default=True)
    icone = Column(String)                                      # emoji opcional
    essencial = Column(Boolean, default=True)                   # padrão: essencial. False = discricionário/desejos.


class Atribuicao(Base):
    """Pessoa ou Grupo — para quem/o quê é a despesa."""
    __tablename__ = "atribuicoes"
    id = Column(Integer, primary_key=True)
    nome = Column(String, unique=True, nullable=False)
    tipo = Column(String, nullable=False)                       # "Pessoa" | "Grupo"
    descricao = Column(Text)
    ativo = Column(Boolean, default=True)
    cor = Column(String)                                        # hex para gráficos


class Regra(Base):
    """Regra de palavra-chave para auto-categorização e auto-atribuição."""
    __tablename__ = "regras"
    id = Column(Integer, primary_key=True)
    palavra_chave = Column(String, nullable=False, index=True)  # busca em descrição (case-insensitive)
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    atribuicao_id = Column(Integer, ForeignKey("atribuicoes.id"))
    prioridade = Column(Integer, default=0)                     # maior vence em caso de empate
    ativa = Column(Boolean, default=True)
    comentario = Column(Text)

    categoria = relationship("Categoria")
    atribuicao = relationship("Atribuicao")


class Fatura(Base):
    """Cada PDF de fatura importado vira uma linha aqui — rastreabilidade e dedup."""
    __tablename__ = "faturas"
    id = Column(Integer, primary_key=True)
    banco = Column(String, nullable=False)                      # "Nubank" | "Bradesco" | "Santander"
    conta_id = Column(Integer, ForeignKey("contas.id"))
    mes_referencia = Column(String, nullable=False)             # "MM/YYYY"
    data_vencimento = Column(Date)
    periodo_inicio = Column(Date)
    periodo_fim = Column(Date)
    total = Column(Float)
    # Saldo (relevante só para extratos de conta corrente; null para faturas de cartão)
    saldo_inicial = Column(Float)                               # saldo do dia anterior ao período
    saldo_final = Column(Float)                                 # saldo no fim do período
    pdf_filename = Column(String)
    pdf_hash = Column(String, unique=True)                      # SHA256 do PDF — evita reimportação
    importada_em = Column(DateTime, default=datetime.utcnow)
    observacoes = Column(Text)
    # Override manual da data de pagamento da fatura (ex.: paga adiantado, antes do
    # vencimento). Tem prioridade sobre o pagamento vinculado e sobre o vencimento.
    data_pagamento_manual = Column(Date)

    conta = relationship("Conta")
    transacoes = relationship(
        "Transacao",
        back_populates="fatura",
        foreign_keys="Transacao.fatura_id",
    )


class Transacao(Base):
    """Transação individual — pode ser de fatura de cartão ou extrato."""
    __tablename__ = "transacoes"
    id = Column(Integer, primary_key=True)
    fatura_id = Column(Integer, ForeignKey("faturas.id"))       # null se for de extrato
    conta_id = Column(Integer, ForeignKey("contas.id"), nullable=False)

    data = Column(Date, nullable=False)                         # data da compra/lançamento
    descricao = Column(String, nullable=False)                  # do PDF — IMUTÁVEL
    descricao_personalizada = Column(String)                    # editável pelo usuário
    descricao_normalizada = Column(String, index=True)          # normalizada para matching
    valor = Column(Float, nullable=False)                       # sempre positivo. tipo define direção
    tipo = Column(String, nullable=False)                       # "Despesa" | "Receita"
    forma_pagamento = Column(String)                            # "Crédito" | "Débito" | "Pix" | etc.
    parcela = Column(String)                                    # "2/12" | None
    mes_referencia = Column(String, nullable=False, index=True) # "MM/YYYY" — para cartão é o mês da fatura

    # Categorização — armazena IDs (FK), mas também o "snapshot" de origem para auditoria
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    categoria_origem = Column(String)                           # "manual" | "memoria" | "regra" | "nao_categorizado"
    atribuicao_id = Column(Integer, ForeignKey("atribuicoes.id"))
    atribuicao_origem = Column(String)
    # Essencial: None = usa o padrão da categoria; True/False = sobrescreve
    essencial_override = Column(Boolean, nullable=True)
    # Estorno: aponta pra transação de Despesa que essa Receita está revertendo
    estorno_de_id = Column(Integer, ForeignKey("transacoes.id"), nullable=True)
    # Suspeita de duplicata: marca transações que têm hash igual a outra existente.
    # Usuário decide manualmente se aceita (vira False) ou descarta (delete).
    # Enquanto True, a transação NÃO conta em totais/agregações.
    suspeita_duplicata = Column(Boolean, default=False)
    # Movimentação interna (não é "categoria"): pagamento de fatura de cartão ou
    # transferência entre contas próprias. Quando setada (não-None), a transação
    # NÃO aparece na lista de Transações nem conta nos totais — fica só no Extrato.
    # Valores: None (transação normal) | "fatura" | "transferencia".
    movimentacao = Column(String, nullable=True, index=True)

    observacoes = Column(Text)
    cartao_final = Column(String)                               # últimos 4 dígitos
    moeda_original = Column(String)                             # "USD" para compras internacionais
    valor_original = Column(Float)
    cotacao = Column(Float)

    # Conciliação
    conciliada = Column(Boolean, default=False)                 # True se vinculada a outra transação
    duplicata_de_id = Column(Integer, ForeignKey("transacoes.id"))   # quando marcada como duplicata
    pagamento_de_fatura_id = Column(Integer, ForeignKey("faturas.id"))  # transação que paga uma fatura

    # Divisão em partes: a transação original (movimento real do banco) vira "pai"
    # (dividida=True) e é quebrada em N filhas, cada uma com seu valor/categoria/
    # atribuição. O pai NÃO conta em totais nem na lista de Transações (mas aparece
    # no Extrato, pois é o movimento real); as filhas (parte_de_id setado) contam
    # nos totais/categorias e NÃO aparecem no Extrato (senão duplicaria o saldo).
    parte_de_id = Column(Integer, ForeignKey("transacoes.id"))  # setado nas filhas → aponta o pai
    dividida = Column(Boolean, default=False)                   # True no pai dividido

    # Data EFETIVA de pagamento (regime de caixa): quando o dinheiro saiu/entrou
    # de fato. Cartão = data de pagamento da fatura (manual > vínculo no extrato >
    # vencimento). Conta corrente/carteira/manual = a própria `data`. Armazenada
    # pra o dashboard só trocar o campo de filtro entre emissão (`data`) e pagamento.
    data_pagamento = Column(Date, index=True)

    importada_em = Column(DateTime, default=datetime.utcnow)
    hash_dedup = Column(String, index=True)                     # banco+data+valor+desc → detecta duplicata

    fatura = relationship("Fatura", back_populates="transacoes", foreign_keys=[fatura_id])
    conta = relationship("Conta")
    categoria = relationship("Categoria")
    atribuicao = relationship("Atribuicao")
    divisoes = relationship("Divisao", back_populates="transacao", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_trans_conta_data", "conta_id", "data"),
        Index("ix_trans_mes_ref", "mes_referencia"),
    )


class Divisao(Base):
    """
    Divisão de uma transação entre múltiplas atribuições.
    A "atribuicao_id" da transação é a principal (com seu percentual também aqui).
    Se uma transação tem 0 divisões, vai 100% para sua atribuicao_id.
    """
    __tablename__ = "divisoes"
    id = Column(Integer, primary_key=True)
    transacao_id = Column(Integer, ForeignKey("transacoes.id"), nullable=False)
    atribuicao_id = Column(Integer, ForeignKey("atribuicoes.id"), nullable=False)
    percentual = Column(Float, nullable=False)                  # 0-100

    transacao = relationship("Transacao", back_populates="divisoes")
    atribuicao = relationship("Atribuicao")


class Memoria(Base):
    """
    Memória de aprendizado.
    Cada vez que o usuário corrige a categoria/atribuição de uma transação,
    grava aqui. Da próxima vez que aparecer descrição igual, usa daqui.
    """
    __tablename__ = "memoria"
    id = Column(Integer, primary_key=True)
    descricao_normalizada = Column(String, nullable=False, index=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    atribuicao_id = Column(Integer, ForeignKey("atribuicoes.id"))
    contagem = Column(Integer, default=1)                       # quantas vezes essa correção foi feita
    ultima_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria = relationship("Categoria")
    atribuicao = relationship("Atribuicao")

    __table_args__ = (UniqueConstraint("descricao_normalizada"),)


class Conciliacao(Base):
    """
    Vínculo explícito entre transações.
    Tipos:
      "pagamento_fatura" — pagamento no extrato ↔ fatura de cartão
      "duplicata"        — mesma transação importada de duas fontes
      "transferencia"    — saída em uma conta = entrada em outra (sua)
    """
    __tablename__ = "conciliacoes"
    id = Column(Integer, primary_key=True)
    tipo = Column(String, nullable=False)
    transacao_a_id = Column(Integer, ForeignKey("transacoes.id"), nullable=False)
    transacao_b_id = Column(Integer, ForeignKey("transacoes.id"))   # opcional (pagamento de fatura usa fatura_id)
    fatura_id = Column(Integer, ForeignKey("faturas.id"))
    confianca = Column(Float)                                       # 0-1, quão certo foi o match
    confirmada = Column(Boolean, default=False)                     # usuário confirmou ou só sugestão
    criada_em = Column(DateTime, default=datetime.utcnow)
    observacao = Column(Text)


# ============================================================
# INVESTIMENTOS
# ============================================================

class Ativo(Base):
    """
    Ativo de investimento. Pode ser:
      - Renda fixa: CDB, LCI, LCA, Tesouro Direto, fundo DI
      - Renda variável: ação BR, FII, ETF nacional, ETF internacional
      - Outros: cripto, fundo imobiliário fora bolsa, etc.

    Categoria principal: tipo. Sub-detalhe: detalhes_taxa (ex: "100% CDI", "IPCA+5,5%").
    """
    __tablename__ = "ativos"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)              # "VWRA - Vanguard FTSE All-World"
    ticker = Column(String)                            # "VWRA.L" — opcional pra renda fixa
    tipo = Column(String, nullable=False)              # "ETF Internacional" | "CDB" | "LCI" | "LCA" | "Tesouro" | "Fundo" | "Ação BR" | "FII" | "Cripto" | "Outros"
    moeda = Column(String, default="BRL")              # "BRL" | "USD" | "EUR" | "GBP"
    instituicao = Column(String)                       # corretora/banco onde está custodiado
    detalhes_taxa = Column(String)                     # "100% CDI", "IPCA+5,5%", "12% a.a.", livre

    # Saldo manual (informado pelo usuário, atualizado quando vê no app do banco)
    saldo_atual = Column(Float, default=0)             # na moeda do ativo
    saldo_atualizado_em = Column(Date)                 # data da última atualização manual

    # Pra registro/IR
    data_vencimento = Column(Date)                     # CDB com data fim. None pra renda variável

    ativo = Column(Boolean, default=True)              # se False, sumido da carteira mas histórico fica
    criado_em = Column(DateTime, default=datetime.utcnow)
    observacoes = Column(Text)

    # Se True, operações tipo "Rendimento" incorporam ao saldo do ativo
    # (juros de RF, cashback acumulando em caixinha, rewards de cripto).
    # Se False, "Rendimento" representa dividendo/JCP que cai na conta
    # corrente — não muda o saldo do ativo (caso típico de RV).
    # None = usa o default baseado no tipo (RF → True; resto → False).
    rendimento_incorpora_saldo = Column(Boolean)

    # % do CDI para auto-cálculo do rendimento em renda fixa indexada ao CDI.
    # Ex: 100 = 100% CDI, 120 = 120% CDI. Quando setado (e o ativo é renda
    # fixa, sem saldo manual), o saldo é acumulado dia a dia pela série CDI do
    # Banco Central — em vez de depender de lançamentos manuais de "Rendimento".
    # None = sem auto-cálculo (comportamento antigo).
    cdi_percentual = Column(Float)

    # Objetivo do investimento: "patrimonio" (riqueza de longo prazo) ou
    # "aquisicao" (reservado pra comprar um bem: carro, casa…). O gráfico de
    # patrimônio e metas de patrimônio total só contam objetivo="patrimonio".
    objetivo = Column(String, default="patrimonio")


class OperacaoInvestimento(Base):
    """
    Cada compra, venda, aporte ou resgate. Histórico completo.

    Tipos:
      "Compra"   — aquisição de ativo (ETF/ação) ou aplicação inicial (CDB/Tesouro)
      "Venda"    — venda total ou parcial de ativo
      "Aporte"   — aporte adicional num CDB/fundo já existente
      "Resgate"  — resgate parcial ou total
      "Rendimento" — provento/dividendo recebido (FII, ação, JCP)
    """
    __tablename__ = "operacoes_investimento"
    id = Column(Integer, primary_key=True)
    ativo_id = Column(Integer, ForeignKey("ativos.id"), nullable=False)
    tipo = Column(String, nullable=False)              # Compra/Venda/Aporte/Resgate/Rendimento
    data = Column(Date, nullable=False)

    # Renda variável: quantidade × preço unitário = valor_total
    quantidade = Column(Float)                         # None pra renda fixa
    preco_unitario = Column(Float)                     # na moeda da operação. None pra renda fixa.

    # Renda fixa: só valor_total (já é o total aplicado)
    valor_total = Column(Float, nullable=False)        # SEMPRE positivo, na moeda da operação
    moeda_operacao = Column(String, default="BRL")     # "BRL" | "USD" | "EUR"
    cotacao_cambio = Column(Float)                     # 1 unidade da moeda_operacao em BRL no dia da operação

    taxas = Column(Float, default=0)                   # corretagem, IOF, etc. (na moeda da operação)
    # Resgate/Venda que ENCERROU o título: o valor_total é o líquido recebido e o
    # app zera o saldo (o resíduo bruto = IR/IOF retido vira custo realizado).
    resgate_total = Column(Boolean, default=False)
    observacoes = Column(Text)
    criado_em = Column(DateTime, default=datetime.utcnow)

    ativo_obj = relationship("Ativo")


class CDIDiario(Base):
    """
    Cache local da série CDI diária (BCB SGS série 12), em % ao dia.
    Permite acumular o rendimento de renda fixa indexada ao CDI sem depender
    de internet a cada cálculo — sincroniza incrementalmente quando online.
    """
    __tablename__ = "cdi_diario"
    data = Column(Date, primary_key=True)
    taxa = Column(Float, nullable=False)   # % ao dia (ex: 0.053400)


class PatrimonioSnapshot(Base):
    """Foto diária do patrimônio investido (em BRL), pra montar o gráfico de
    evolução ao longo do tempo. Gravado (upsert por dia) ao abrir a carteira."""
    __tablename__ = "patrimonio_snapshot"
    data = Column(Date, primary_key=True)
    total_brl = Column(Float, nullable=False)       # posição atual em BRL (carteira toda)
    investido_brl = Column(Float, nullable=False)   # custo investido em BRL
    patrimonio_brl = Column(Float)                  # só ativos objetivo="patrimonio" (p/ o gráfico)


# ============================================================
# METAS DE PATRIMÔNIO
# ============================================================

class Meta(Base):
    """
    Meta de patrimônio. Suporta níveis (hierarquia) via meta_pai_id e três
    formas de medir o valor atual:

      escopo="patrimonio_total" — soma de TODOS os ativos (em BRL).
      escopo="tipos_ativo"      — soma dos ativos com tipo em `escopo_tipos`
                                  (ex: ["ETF Internacional","Ação BR"] = RV).
      escopo="manual"           — valor editado à mão pelo usuário, pra metas
                                  livres ("entrada do apê") não vinculadas.

    O progresso é calculado dinamicamente no endpoint — nada de cache.
    """
    __tablename__ = "metas"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    descricao = Column(Text)

    # Hierarquia: None = meta raiz; senão é sub-meta de outra.
    meta_pai_id = Column(Integer, ForeignKey("metas.id"), nullable=True)

    escopo = Column(String, nullable=False)            # patrimonio_total | tipos_ativo | ativos | manual
    escopo_tipos = Column(Text)                        # JSON list de tipos (quando escopo=tipos_ativo)
    escopo_ativos = Column(Text)                       # JSON list de ids de ativo (quando escopo=ativos)
    escopo_excluir_ativos = Column(Text)               # JSON list de ids de ativo a IGNORAR (patrimonio_total/tipos_ativo)
    objetivo = Column(String, default="patrimonio")    # "patrimonio" | "aquisicao" (categoria da meta)
    valor_atual_manual = Column(Float, default=0)      # só quando escopo=manual

    valor_alvo = Column(Float, nullable=False)         # no valor da moeda da meta (abaixo)
    # Moeda do valor alvo: "BRL" | "USD" | "EUR" | "GBP". Se != BRL, o alvo é
    # convertido pra BRL pela cotação atual ao calcular o progresso (ajusta sozinho).
    moeda = Column(String, default="BRL")
    data_alvo = Column(Date)                           # opcional

    ordem = Column(Integer, default=0)
    cor = Column(String)
    ativa = Column(Boolean, default=True)
    atingida_em = Column(Date)                         # set quando bate 100%
    criada_em = Column(DateTime, default=datetime.utcnow)

    # Taxa de retorno anual esperada (% a.a.) usada na projeção composta.
    # Quando None, a projeção usa a taxa derivada do CDI dos ativos no escopo
    # (renda fixa); útil para definir uma expectativa em metas de renda
    # variável ou manuais, onde não há taxa determinística.
    taxa_retorno_anual = Column(Float)

    meta_pai = relationship("Meta", remote_side=[id], backref="sub_metas")


# === Engine + sessão ===
def get_engine(db_path: str):
    """Cria engine SQLite. Usa StaticPool em testes para reuso de conexão."""
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )


def _aplicar_migracoes(engine):
    """
    Migrações simples manuais (ALTER TABLE). Adiciona colunas que faltam em
    bancos antigos. Idempotente — verifica antes de aplicar.

    Convenção: se você adicionar uma coluna nova num modelo, adicione aqui também.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    def add_column_if_missing(tabela: str, coluna: str, tipo_sql: str):
        try:
            cols = [c["name"] for c in insp.get_columns(tabela)]
        except Exception:
            return  # tabela ainda não existe, create_all vai cuidar
        if coluna not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo_sql}"))

    # v1.1 — senha de PDF por conta
    add_column_if_missing("contas", "senha_pdf", "VARCHAR")
    # v1.2 — descrição personalizada (editável) na transação
    add_column_if_missing("transacoes", "descricao_personalizada", "VARCHAR")
    # v1.3 — banco_id na conta (FK para bancos)
    add_column_if_missing("contas", "banco_id", "INTEGER")
    # v1.4 — titular da conta (separar contas do mesmo banco entre membros)
    add_column_if_missing("contas", "titular", "VARCHAR")
    # v1.5 — saldo inicial/final da fatura (extratos OFX)
    add_column_if_missing("faturas", "saldo_inicial", "FLOAT")
    add_column_if_missing("faturas", "saldo_final", "FLOAT")
    # v1.6 — saldo inicial manual da conta (fallback quando não há OFX importado)
    add_column_if_missing("contas", "saldo_inicial_manual", "FLOAT")
    add_column_if_missing("contas", "saldo_inicial_data", "DATE")
    # v1.8 — data de início de uso (filtra "não se aplica" no mapa de cobertura)
    add_column_if_missing("contas", "data_inicio_uso", "DATE")
    # v1.9 — essencial vs discricionário
    add_column_if_missing("categorias", "essencial", "BOOLEAN DEFAULT 1")
    add_column_if_missing("transacoes", "essencial_override", "BOOLEAN")
    # v1.10 — estorno_de_id pra ligar Receita revertendo Despesa
    add_column_if_missing("transacoes", "estorno_de_id", "INTEGER")
    # v1.11 — suspeita_duplicata pra revisão manual de duplicatas pós-importação
    add_column_if_missing("transacoes", "suspeita_duplicata", "BOOLEAN DEFAULT 0")
    # v1.12 — flag por ativo: rendimento incorpora ao saldo (override do default por tipo)
    add_column_if_missing("ativos", "rendimento_incorpora_saldo", "BOOLEAN")
    # v1.13 — % do CDI por ativo (auto-cálculo de rendimento de renda fixa)
    add_column_if_missing("ativos", "cdi_percentual", "FLOAT")
    # v1.13 — taxa de retorno anual esperada por meta (projeção composta)
    add_column_if_missing("metas", "taxa_retorno_anual", "FLOAT")
    # v1.14 — escopo de meta por ativos específicos (JSON list de ids)
    add_column_if_missing("metas", "escopo_ativos", "TEXT")

    # ativos a IGNORAR numa meta (ex: reservas pra carro/casa fora do "future proof")
    add_column_if_missing("metas", "escopo_excluir_ativos", "TEXT")

    # objetivo: patrimonio vs aquisicao de bens (ativo e meta) + snapshot só de patrimônio
    add_column_if_missing("ativos", "objetivo", "VARCHAR DEFAULT 'patrimonio'")
    add_column_if_missing("metas", "objetivo", "VARCHAR DEFAULT 'patrimonio'")
    add_column_if_missing("patrimonio_snapshot", "patrimonio_brl", "FLOAT")

    add_column_if_missing("operacoes_investimento", "resgate_total", "BOOLEAN DEFAULT 0")
    # v1.15 — movimentação interna (pagamento de fatura / transferência) deixa de ser
    # categoria e vira flag na transação. Migra dados antigos e remove as 2 categorias.
    add_column_if_missing("transacoes", "movimentacao", "VARCHAR")
    _migrar_movimentacao(engine)
    # v1.16 — zera saldos OFX que são snapshot atual (não do período): detecta
    # pela quebra de encadeamento entre meses (Santander carimba saldo atual).
    _corrigir_saldos_ofx_inconfiaveis(engine)
    # v1.17 — mescla a categoria "Salário" em "Pró-labore" (mantém Pró-labore).
    _merge_categoria(engine, "Salário", "Pró-labore")
    # v1.18 — divisão de transação em partes (transações-filhas)
    add_column_if_missing("transacoes", "parte_de_id", "INTEGER")
    add_column_if_missing("transacoes", "dividida", "BOOLEAN DEFAULT 0")
    # v1.19 — regime de pagamento: data efetiva de pagamento (caixa)
    add_column_if_missing("faturas", "data_pagamento_manual", "DATE")
    add_column_if_missing("transacoes", "data_pagamento", "DATE")
    _backfill_data_pagamento(engine)
    # v1.20 — moeda da meta (alvo em moeda estrangeira, ajustado pela cotação)
    add_column_if_missing("metas", "moeda", "VARCHAR DEFAULT 'BRL'")
    _autofill_cdi_percentual(engine)
    # v1.21 — flag "entra no orçamento" por categoria (decopla inclusão do teto).
    # Backfill: quem já tinha teto (>0) entra no orçamento; o resto fica de fora.
    add_column_if_missing("categorias", "orcado", "BOOLEAN")
    _backfill_orcado(engine)
    # v1.7 — remove unique constraint do nome da conta (permite múltiplas com mesmo nome)
    _drop_unique_index_se_existir(engine, "contas", "nome")


def _migrar_movimentacao(engine):
    """Converte as categorias especiais 'Pagamento de Fatura' e 'Transferência entre
    Contas' na flag transacoes.movimentacao e remove as categorias.

    Idempotente: se as categorias já não existem (instalação nova ou migração já
    rodada), tudo vira no-op.
    """
    from sqlalchemy import text
    MAPA = {
        "Pagamento de Fatura": "fatura",
        "Transferência entre Contas": "transferencia",
    }

    def _exec(conn, sql, params):
        # Cada statement é isolado: uma tabela inexistente (ex.: memoria no
        # primeiro boot) não pode impedir os demais (sobretudo o DELETE).
        try:
            conn.execute(text(sql), params)
        except Exception:
            pass

    with engine.begin() as conn:
        try:
            cats = conn.execute(text("SELECT id, nome FROM categorias")).fetchall()
        except Exception:
            return  # tabela categorias ainda não existe (primeiro boot)
        nome_para_id = {n: i for i, n in cats}
        for nome, flag in MAPA.items():
            cat_id = nome_para_id.get(nome)
            if not cat_id:
                continue
            # Transações dessa categoria → flag de movimentação, sem categoria
            _exec(conn,
                  "UPDATE transacoes SET movimentacao = :f, categoria_id = NULL, "
                  "categoria_origem = 'movimentacao' WHERE categoria_id = :id",
                  {"f": flag, "id": cat_id})
            # Regras e memórias que apontavam pra ela ficam sem categoria (inócuas)
            _exec(conn, "UPDATE regras SET categoria_id = NULL WHERE categoria_id = :id", {"id": cat_id})
            _exec(conn, "UPDATE memoria SET categoria_id = NULL WHERE categoria_id = :id", {"id": cat_id})
            # Remove a categoria
            _exec(conn, "DELETE FROM categorias WHERE id = :id", {"id": cat_id})


def _backfill_data_pagamento(engine):
    """Preenche transacoes.data_pagamento (data efetiva de pagamento) onde está NULL.
    Cartão de Crédito: COALESCE(manual da fatura, pagamento vinculado no extrato,
    vencimento da fatura, data da compra). Demais contas: a própria `data`.
    Só preenche NULLs (idempotente); mudanças posteriores via recalcular_data_pagamento."""
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.execute(text("""
                UPDATE transacoes SET data_pagamento = COALESCE(
                    (SELECT f.data_pagamento_manual FROM faturas f WHERE f.id = transacoes.fatura_id),
                    (SELECT MIN(p.data) FROM transacoes p WHERE p.pagamento_de_fatura_id = transacoes.fatura_id),
                    (SELECT f.data_vencimento FROM faturas f WHERE f.id = transacoes.fatura_id),
                    transacoes.data
                )
                WHERE data_pagamento IS NULL
                  AND conta_id IN (SELECT id FROM contas WHERE tipo = 'Cartão de Crédito')
            """))
            conn.execute(text(
                "UPDATE transacoes SET data_pagamento = data WHERE data_pagamento IS NULL"
            ))
        except Exception:
            pass


def _merge_categoria(engine, de_nome: str, para_nome: str):
    """Mescla a categoria `de_nome` em `para_nome`: repointa transações, regras
    e memórias e remove a categoria de origem. Idempotente (no-op se a origem
    não existe, ex.: instalação nova ou migração já rodada)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            de = conn.execute(text("SELECT id FROM categorias WHERE nome = :n"), {"n": de_nome}).fetchone()
            para = conn.execute(text("SELECT id FROM categorias WHERE nome = :n"), {"n": para_nome}).fetchone()
        except Exception:
            return  # tabela categorias ainda não existe
        if not de:
            return
        de_id = de[0]
        para_id = para[0] if para else None
        if para_id is None:
            # destino não existe: só renomeia a origem (preserva os dados)
            conn.execute(text("UPDATE categorias SET nome = :p WHERE id = :id"),
                         {"p": para_nome, "id": de_id})
            return
        for sql in (
            "UPDATE transacoes SET categoria_id = :para WHERE categoria_id = :de",
            "UPDATE regras SET categoria_id = :para WHERE categoria_id = :de",
            "UPDATE memoria SET categoria_id = :para WHERE categoria_id = :de",
        ):
            try:
                conn.execute(text(sql), {"para": para_id, "de": de_id})
            except Exception:
                pass  # tabela pode não existir no primeiro boot
        conn.execute(text("DELETE FROM categorias WHERE id = :id"), {"id": de_id})


def _corrigir_saldos_ofx_inconfiaveis(engine):
    """Zera saldo_inicial/saldo_final de faturas (extratos OFX) cujo saldo é um
    'snapshot atual' do banco, não o saldo do fim do período.

    Detecção: dentro de uma mesma conta, faturas confiáveis encadeiam — o
    saldo_inicial de um mês == saldo_final do mês anterior. Se QUALQUER par
    consecutivo não encadeia, os saldos daquela conta vêm do LEDGERBAL atual
    (ex.: Santander) e não servem; zera todos pra cair no cálculo acumulado.

    Idempotente: depois de zerar, as linhas saem do SELECT (saldos NULL) e
    nenhuma quebra é mais detectada.
    """
    from sqlalchemy import text
    from collections import defaultdict
    with engine.begin() as conn:
        try:
            rows = conn.execute(text(
                "SELECT id, conta_id, periodo_inicio, saldo_inicial, saldo_final "
                "FROM faturas "
                "WHERE saldo_inicial IS NOT NULL AND saldo_final IS NOT NULL "
                "ORDER BY conta_id, periodo_inicio"
            )).fetchall()
        except Exception:
            return  # tabela faturas ainda não existe
        por_conta = defaultdict(list)
        for r in rows:
            por_conta[r[1]].append(r)
        contas_quebradas = set()
        for conta_id, fts in por_conta.items():
            for prev, cur in zip(fts, fts[1:]):
                # saldo_inicial do atual deve bater com saldo_final do anterior
                if abs((cur[3] or 0) - (prev[4] or 0)) > 0.01:
                    contas_quebradas.add(conta_id)
                    break
        for conta_id in contas_quebradas:
            conn.execute(text(
                "UPDATE faturas SET saldo_inicial = NULL, saldo_final = NULL "
                "WHERE conta_id = :c"
            ), {"c": conta_id})


def _backfill_orcado(engine):
    """Marca como 'no orçamento' (orcado=1) as categorias que já tinham teto
    (orcamento_mensal > 0); as demais ficam fora (0). Só toca em linhas com
    orcado NULL — idempotente."""
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "UPDATE categorias SET orcado = CASE "
                "WHEN COALESCE(orcamento_mensal, 0) > 0 THEN 1 ELSE 0 END "
                "WHERE orcado IS NULL"
            ))
        except Exception:
            pass


def _autofill_cdi_percentual(engine):
    """Para ativos de renda fixa sem cdi_percentual, tenta extrair o % do CDI
    do texto livre em detalhes_taxa (ex: "100% CDI", "120% CDI (Cashback)").
    Idempotente — só preenche quem está nulo."""
    from sqlalchemy import text
    import re as _re
    padrao = _re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:do\s+)?CDI", _re.IGNORECASE)
    with engine.begin() as conn:
        try:
            rows = conn.execute(text(
                "SELECT id, detalhes_taxa FROM ativos "
                "WHERE cdi_percentual IS NULL AND detalhes_taxa IS NOT NULL"
            )).fetchall()
        except Exception:
            return
        for aid, detalhe in rows:
            if not detalhe:
                continue
            m = padrao.search(detalhe)
            if not m:
                continue
            pct = float(m.group(1).replace(",", "."))
            conn.execute(text(
                "UPDATE ativos SET cdi_percentual = :p WHERE id = :id"
            ), {"p": pct, "id": aid})


def _drop_unique_index_se_existir(engine, tabela: str, coluna: str):
    """SQLite não suporta DROP CONSTRAINT. Pra remover UNIQUE de uma coluna,
    precisamos recriar a tabela. Verifica se realmente tem a constraint antes."""
    from sqlalchemy import text
    import re as _re
    with engine.begin() as conn:
        # Pega DDL atual da tabela
        row = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"
        ), {"n": tabela}).fetchone()
        if not row:
            return
        ddl_atual = row[0]
        if "UNIQUE" not in ddl_atual.upper():
            # Já está migrado, nada a fazer
            return

        # Tenta dois padrões: UNIQUE inline ou UNIQUE separado em linha
        padrao_inline = _re.compile(
            rf'("?{coluna}"?\s+\w+(?:\([^)]*\))?\s*(?:NOT\s+NULL\s+)?)UNIQUE',
            _re.IGNORECASE,
        )
        padrao_separado = _re.compile(
            rf',\s*UNIQUE\s*\(\s*"?{coluna}"?\s*\)',
            _re.IGNORECASE,
        )

        if padrao_inline.search(ddl_atual):
            ddl_novo = padrao_inline.sub(r'\1', ddl_atual, count=1)
        elif padrao_separado.search(ddl_atual):
            ddl_novo = padrao_separado.sub('', ddl_atual, count=1)
        else:
            # Não conseguiu localizar — desiste sem quebrar
            return

        # Trim espaços
        ddl_novo = _re.sub(r'\s+,', ',', ddl_novo)
        ddl_novo = _re.sub(r'\s{2,}', ' ', ddl_novo)

        # Pega lista de colunas pra fazer SELECT explícito
        cols_rows = conn.execute(text(f"PRAGMA table_info({tabela})")).fetchall()
        cols = [r[1] for r in cols_rows]
        cols_quoted = ", ".join(f'"{c}"' for c in cols)

        tmp = f"{tabela}_old_v17"
        conn.execute(text(f'DROP TABLE IF EXISTS "{tmp}"'))
        conn.execute(text(f'ALTER TABLE "{tabela}" RENAME TO "{tmp}"'))
        conn.execute(text(ddl_novo))
        conn.execute(text(
            f'INSERT INTO "{tabela}" ({cols_quoted}) SELECT {cols_quoted} FROM "{tmp}"'
        ))
        conn.execute(text(f'DROP TABLE "{tmp}"'))
    # v1.3 — popula tabela bancos a partir do campo banco existente nas contas
    _popular_bancos_a_partir_de_contas(engine)


def _popular_bancos_a_partir_de_contas(engine):
    """Para cada nome de banco distinto presente em contas.banco, cria registro em bancos
    e atualiza contas.banco_id. Idempotente."""
    from sqlalchemy import text
    with engine.begin() as conn:
        # Coleta nomes de banco distintos
        rows = conn.execute(text(
            "SELECT DISTINCT banco FROM contas WHERE banco IS NOT NULL AND banco != ''"
        )).fetchall()
        for (nome_banco,) in rows:
            # Cria se não existe
            existe = conn.execute(text(
                "SELECT id FROM bancos WHERE nome = :n"
            ), {"n": nome_banco}).fetchone()
            if existe:
                banco_id = existe[0]
            else:
                cur = conn.execute(text(
                    "INSERT INTO bancos (nome, ativo) VALUES (:n, 1)"
                ), {"n": nome_banco})
                banco_id = cur.lastrowid
            # Atualiza contas que ainda não têm banco_id
            conn.execute(text(
                "UPDATE contas SET banco_id = :b WHERE banco = :n AND (banco_id IS NULL OR banco_id = 0)"
            ), {"b": banco_id, "n": nome_banco})


def init_db(db_path: str):
    """Cria todas as tabelas se ainda não existirem e aplica migrações."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _aplicar_migracoes(engine)
    return engine


def get_session(engine):
    """Retorna uma factory de sessões."""
    return sessionmaker(bind=engine, expire_on_commit=False)
