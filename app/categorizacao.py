"""
Engine de categorização e atribuição automáticas.

Ordem de prioridade ao classificar uma transação NOVA:
  1. Memória — se descrição_normalizada já foi classificada antes pelo usuário,
     reaproveita (peso pela contagem de vezes que foi corrigida — quanto mais,
     mais confiável).
  2. Regra — se uma palavra-chave da tabela `regras` aparece na descrição,
     aplica. Em caso de múltiplas, vence a de maior prioridade; empate, a
     palavra-chave mais longa (mais específica).
  3. None — fica "não categorizado", usuário decide depois.

Quando o usuário CORRIGE uma transação:
  - Atualiza a transação no banco
  - Insere/atualiza a Memória (incrementa contagem)
  - Não toca em transações antigas com a mesma descrição (decisões anteriores
    do usuário ficam preservadas), mas TODAS as próximas vão usar a memória nova.
"""
import re
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session

from .database import Categoria, Atribuicao, Regra, Memoria, Transacao
from .utils import normalizar_descricao


# Lojas "marketplace" (vendem de tudo): o nome não diz a categoria, então NÃO
# auto-categorizamos por memória/regra — a não ser que seja uma parcela de uma
# compra que o usuário já categorizou (a herança entre parcelas cobre esse caso
# na importação). Atribuição (pra quem) continua valendo normalmente.
_RE_MARKETPLACE = re.compile(
    r"AMAZON|MERCADO\s*LIVRE|MERCADOLIVRE|MERCADO\s*LIBRE|MERCADOLIBRE",
    re.IGNORECASE,
)


def _eh_marketplace(descricao: str) -> bool:
    """True se a descrição é de uma compra Amazon/Mercado Livre (categoria não
    deve ser inferida automaticamente)."""
    return bool(_RE_MARKETPLACE.search(descricao or ""))


@dataclass
class Classificacao:
    categoria_id: Optional[int]
    atribuicao_id: Optional[int]
    categoria_origem: str   # "memoria" | "regra" | "nao_categorizado"
    atribuicao_origem: str
    confianca: float        # 0-1, quanto mais alto, mais certo


def carregar_regras_ativas(session: Session) -> list:
    """Carrega as regras ativas uma vez (para reaproveitar em loops de import)."""
    return session.query(Regra).filter(Regra.ativa == True).all()


def classificar(session: Session, descricao: str, regras: list = None) -> Classificacao:
    """Retorna a melhor classificação automática para uma descrição.

    `regras` pode ser passada já carregada (em loops de importação) para evitar
    uma query ao banco por transação. Se None, carrega do banco.
    """
    desc_norm = normalizar_descricao(descricao)

    cat_id = None
    atr_id = None
    cat_origem = "nao_categorizado"
    atr_origem = "nao_categorizado"
    cat_confianca = 0.0
    atr_confianca = 0.0

    # Amazon/Mercado Livre: NÃO inferir categoria automaticamente (o nome da loja
    # não diz o que foi comprado). Atribuição segue normal. Parcelas de uma compra
    # já categorizada herdam da irmã na importação — esse é o único caso que volta
    # a ter categoria.
    pular_categoria = _eh_marketplace(descricao)

    # === 1. MEMÓRIA — busca exact-match na descrição normalizada ===
    if desc_norm:
        memoria = session.query(Memoria).filter(
            Memoria.descricao_normalizada == desc_norm
        ).first()
        if memoria:
            if memoria.categoria_id and not pular_categoria:
                cat_id = memoria.categoria_id
                cat_origem = "memoria"
                cat_confianca = min(1.0, 0.7 + 0.05 * memoria.contagem)
            if memoria.atribuicao_id:
                atr_id = memoria.atribuicao_id
                atr_origem = "memoria"
                atr_confianca = min(1.0, 0.7 + 0.05 * memoria.contagem)

    # === 2. REGRAS — só se memória não cobriu o campo ===
    # (categoria pulada de propósito p/ marketplace; atribuição ainda vale)
    if (cat_id is None and not pular_categoria) or atr_id is None:
        if regras is None:
            regras = session.query(Regra).filter(Regra.ativa == True).all()
        # Filtra as que batem na descrição (case-insensitive)
        desc_upper = (descricao or "").upper()
        candidatas = []
        for r in regras:
            kw = (r.palavra_chave or "").upper().strip()
            if not kw:
                continue
            if kw in desc_upper:
                candidatas.append(r)
        # Ordena: prioridade desc, depois comprimento da palavra-chave desc
        candidatas.sort(
            key=lambda r: (-(r.prioridade or 0), -len(r.palavra_chave or ""))
        )
        for r in candidatas:
            if cat_id is None and not pular_categoria and r.categoria_id:
                cat_id = r.categoria_id
                cat_origem = "regra"
                cat_confianca = 0.6
            if atr_id is None and r.atribuicao_id:
                atr_id = r.atribuicao_id
                atr_origem = "regra"
                atr_confianca = 0.6
            if (cat_id or pular_categoria) and atr_id:
                break

    return Classificacao(
        categoria_id=cat_id,
        atribuicao_id=atr_id,
        categoria_origem=cat_origem,
        atribuicao_origem=atr_origem,
        confianca=max(cat_confianca, atr_confianca),
    )


def aprender_correcao(
    session: Session,
    descricao: str,
    categoria_id: Optional[int] = None,
    atribuicao_id: Optional[int] = None,
):
    """
    Salva ou atualiza memória após correção do usuário.
    Pelo menos um dos dois (categoria_id ou atribuicao_id) precisa ser passado.
    Se ambos forem None, é um "limpar" — não grava (correção foi tirar tudo).
    """
    if categoria_id is None and atribuicao_id is None:
        return

    desc_norm = normalizar_descricao(descricao)
    if not desc_norm:
        return

    memoria = session.query(Memoria).filter(
        Memoria.descricao_normalizada == desc_norm
    ).first()

    if memoria is None:
        memoria = Memoria(descricao_normalizada=desc_norm)
        session.add(memoria)

    if categoria_id is not None:
        memoria.categoria_id = categoria_id
    if atribuicao_id is not None:
        memoria.atribuicao_id = atribuicao_id

    memoria.contagem = (memoria.contagem or 0) + 1
    session.flush()


def reclassificar_transacoes_pendentes(session: Session) -> int:
    """
    Roda classificar() em todas as transações com origem "nao_categorizado".
    Útil depois que o usuário adiciona uma regra nova ou corrige uma transação
    (a memória nova pode resolver outras pendentes).

    Retorna a quantidade que foi reclassificada com sucesso.
    """
    pendentes = session.query(Transacao).filter(
        (Transacao.categoria_origem == "nao_categorizado") |
        (Transacao.atribuicao_origem == "nao_categorizado")
    ).all()

    regras = carregar_regras_ativas(session)   # uma vez, não por transação
    n_resolvidas = 0
    for t in pendentes:
        c = classificar(session, t.descricao, regras=regras)
        atualizou = False
        if t.categoria_id is None and c.categoria_id:
            t.categoria_id = c.categoria_id
            t.categoria_origem = c.categoria_origem
            atualizou = True
        if t.atribuicao_id is None and c.atribuicao_id:
            t.atribuicao_id = c.atribuicao_id
            t.atribuicao_origem = c.atribuicao_origem
            atualizou = True
        if atualizou:
            n_resolvidas += 1
    session.flush()
    return n_resolvidas


# ============================================================
# Propagação de classificação entre parcelas da mesma compra
# ============================================================

def _denominador_parcela(parcela: Optional[str]) -> Optional[int]:
    """'2/12' → 12. None ou formato inválido → None."""
    if not parcela or "/" not in parcela:
        return None
    try:
        return int(parcela.split("/", 1)[1].strip())
    except (ValueError, AttributeError):
        return None


def _numerador_parcela(parcela: Optional[str]) -> Optional[int]:
    """'2/12' → 2. None ou formato inválido → None."""
    if not parcela or "/" not in parcela:
        return None
    try:
        return int(parcela.split("/", 1)[0].strip())
    except (ValueError, AttributeError):
        return None


# Tolerância de valor (em reais) ao comparar parcelas da mesma compra.
# Cobre pequenos juros que fazem o valor variar de centavos entre parcelas.
TOLERANCIA_VALOR_PARCELA = 0.05


def parcelas_irmas(session: Session, transacao: Transacao):
    """
    Retorna lista de outras transações que são parcelas da MESMA compra.

    Critérios (TODOS têm que bater):
      1. Mesmo denominador no campo `parcela` (ex: ambos "/12")
      2. Mesma descrição normalizada
      3. Numeradores DIFERENTES (1/12 e 2/12 são irmãs;
         duas 2/12 não são — são compras diferentes)
      4. Valores próximos (até 5 centavos de diferença, pra cobrir juros)
      5. ID diferente (não retorna a própria)

    Retorna [] se a transação atual não é parcelada.
    """
    denom = _denominador_parcela(transacao.parcela)
    num_fonte = _numerador_parcela(transacao.parcela)
    if denom is None or num_fonte is None:
        return []

    desc_norm = normalizar_descricao(transacao.descricao)
    if not desc_norm:
        return []

    valor_fonte = transacao.valor or 0.0

    # Busca candidatos: todas com parcela contendo "/{denom}" — filtra Python depois
    sufixo = f"/{denom}"
    candidatos = session.query(Transacao).filter(
        Transacao.id != transacao.id,
        Transacao.parcela.like(f"%{sufixo}"),
    ).all()

    resultado = []
    for c in candidatos:
        # 1. Mesmo denominador
        if _denominador_parcela(c.parcela) != denom:
            continue
        # 2. Mesma descrição normalizada
        if normalizar_descricao(c.descricao) != desc_norm:
            continue
        # 3. Numeradores diferentes (não pode ter duas "2/12" da mesma compra)
        num_c = _numerador_parcela(c.parcela)
        if num_c is None or num_c == num_fonte:
            continue
        # 4. Valor próximo (tolerância pra juros)
        valor_c = c.valor or 0.0
        if abs(valor_c - valor_fonte) > TOLERANCIA_VALOR_PARCELA:
            continue
        resultado.append(c)
    return resultado


def propagar_para_parcelas(
    session: Session,
    transacao: Transacao,
    *,
    forcar: bool = False,
) -> dict:
    """
    Espelha categoria, atribuição e descrição_personalizada da transação
    pras parcelas irmãs.

    Modos:
      forcar=False (auto): só sobrescreve campos NULL ou já iguais aos da fonte.
                            Divergências (campo já tem valor diferente) ficam intocadas
                            e são contadas em `divergentes`.
      forcar=True:         sobrescreve TUDO, inclusive divergências.

    Retorna {
      "irmas_total": int,
      "atualizadas": int,
      "divergentes": int  # divergências encontradas (sobrescritas se forcar=True, intocadas se False)
    }
    """
    irmas = parcelas_irmas(session, transacao)
    if not irmas:
        return {"irmas_total": 0, "atualizadas": 0, "divergentes": 0}

    # Campos a propagar
    campos = {
        "categoria_id": transacao.categoria_id,
        "atribuicao_id": transacao.atribuicao_id,
        "descricao_personalizada": transacao.descricao_personalizada,
    }

    n_atualizadas = 0
    n_divergentes = 0

    for irma in irmas:
        mudou = False
        for campo, valor_fonte in campos.items():
            valor_atual = getattr(irma, campo)
            if valor_atual == valor_fonte:
                continue  # já é igual, nada a fazer
            if valor_atual is None or forcar:
                # NULL ou força → sobrescreve
                setattr(irma, campo, valor_fonte)
                # Marca origem como manual quando muda categoria/atribuição
                if campo == "categoria_id":
                    irma.categoria_origem = "manual"
                elif campo == "atribuicao_id":
                    irma.atribuicao_origem = "manual"
                mudou = True
            else:
                # Tinha valor diferente e não forçou → conta como divergente
                n_divergentes += 1
        if mudou:
            n_atualizadas += 1

    session.flush()
    return {
        "irmas_total": len(irmas),
        "atualizadas": n_atualizadas,
        "divergentes": n_divergentes,
    }


def preview_propagacao(session: Session, transacao: Transacao) -> dict:
    """
    Olha as parcelas irmãs e retorna o que aconteceria se rodasse propagar.
    NÃO altera nada. Usado pra mostrar prompt antes de forçar.

    Retorna {
      "irmas_total": int,
      "iguais": int,         # já têm os mesmos valores
      "vazias": int,         # campos NULL que seriam preenchidos
      "divergentes": int,    # têm valor diferente — precisariam confirmação pra sobrescrever
    }
    """
    irmas = parcelas_irmas(session, transacao)
    if not irmas:
        return {"irmas_total": 0, "iguais": 0, "vazias": 0, "divergentes": 0}

    campos = {
        "categoria_id": transacao.categoria_id,
        "atribuicao_id": transacao.atribuicao_id,
        "descricao_personalizada": transacao.descricao_personalizada,
    }

    n_iguais = 0
    n_vazias = 0
    n_divergentes = 0

    for irma in irmas:
        irma_iguais = True
        irma_tem_vazia = False
        irma_tem_div = False
        for campo, valor_fonte in campos.items():
            valor_atual = getattr(irma, campo)
            if valor_atual == valor_fonte:
                continue
            irma_iguais = False
            if valor_atual is None:
                irma_tem_vazia = True
            else:
                irma_tem_div = True

        if irma_iguais:
            n_iguais += 1
        elif irma_tem_div:
            n_divergentes += 1
        elif irma_tem_vazia:
            n_vazias += 1

    return {
        "irmas_total": len(irmas),
        "iguais": n_iguais,
        "vazias": n_vazias,
        "divergentes": n_divergentes,
    }


# ============================================================
# Detecção de estorno (par compra+estorno na mesma conta)
# ============================================================

# Janela máxima entre compra e estorno (dias)
JANELA_ESTORNO_DIAS = 90
# Tolerância de valor (alguns estornos podem ter diferença de centavos)
TOLERANCIA_VALOR_ESTORNO = 0.05


import re as _re_estorno

# Regex pra extrair nome da loja de "Estorno de \"X\"" ou variações
_RE_ESTORNO_NOME = _re_estorno.compile(
    r'estorno\s+(?:de|do|da)\s*["\'""]?([^"\'""\n]+?)["\'""]?\s*$',
    _re_estorno.IGNORECASE,
)


def _extrair_nome_estorno(descricao: str) -> Optional[str]:
    """
    Se a descrição é tipo 'Estorno de "Mercadolivre*Primeiro"', extrai 'Mercadolivre*Primeiro'.
    Retorna None se não detectar padrão de estorno.
    """
    if not descricao:
        return None
    m = _RE_ESTORNO_NOME.search(descricao.strip())
    if m:
        return m.group(1).strip()
    return None


def encontrar_compra_original(session: Session, receita: Transacao) -> Optional[Transacao]:
    """
    Dado uma transação Receita, tenta achar a Despesa que ela pode estar revertendo.

    Estratégia:
      1. Match exato de descrição_normalizada (estornos onde a descrição == compra)
      2. Match por padrão "Estorno de X" — extrai X e procura compras com essa descrição

    Critérios:
      - Mesma conta
      - tipo='Despesa', valor próximo (tolerância 5 centavos)
      - Data anterior ou igual (estorno depois da compra)
      - Diferença máxima de 90 dias
      - A despesa ainda não foi "estornada" por outra receita
    """
    if receita.tipo != "Receita" or not receita.conta_id:
        return None

    valor_alvo = receita.valor or 0.0
    if valor_alvo <= 0:
        return None

    from datetime import timedelta
    data_minima = receita.data - timedelta(days=JANELA_ESTORNO_DIAS)

    # Lista de descrições candidatas a tentar
    desc_candidatas = []

    # Caso 1: descrição literal (estornos com mesma descrição da compra)
    desc_norm = normalizar_descricao(receita.descricao)
    if desc_norm:
        desc_candidatas.append(desc_norm)

    # Caso 2: padrão "Estorno de X" — extrai X e normaliza
    nome_extraido = _extrair_nome_estorno(receita.descricao)
    if nome_extraido:
        nome_norm = normalizar_descricao(nome_extraido)
        if nome_norm and nome_norm not in desc_candidatas:
            desc_candidatas.append(nome_norm)

    if not desc_candidatas:
        return None

    # Busca despesas elegíveis na mesma conta, dentro da janela
    # Ignora suspeitas de duplicata (ainda não confirmadas pelo usuário)
    candidatas_query = session.query(Transacao).filter(
        Transacao.id != receita.id,
        Transacao.conta_id == receita.conta_id,
        Transacao.tipo == "Despesa",
        Transacao.data >= data_minima,
        Transacao.data <= receita.data,
        Transacao.descricao_normalizada.in_(desc_candidatas),
        (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
    ).order_by(Transacao.data.desc()).all()

    for despesa in candidatas_query:
        # Valor próximo
        if abs((despesa.valor or 0) - valor_alvo) > TOLERANCIA_VALOR_ESTORNO:
            continue
        # A despesa já foi estornada por outra receita?
        ja_estornada = session.query(Transacao).filter(
            Transacao.estorno_de_id == despesa.id
        ).first()
        if ja_estornada:
            continue
        return despesa

    return None


def vincular_estorno(session: Session, receita: Transacao) -> Optional[Transacao]:
    """
    Tenta detectar e vincular um estorno: marca receita.estorno_de_id e
    herda categoria/atribuição da despesa original.

    Retorna a despesa original (se vinculou) ou None.
    """
    despesa = encontrar_compra_original(session, receita)
    if not despesa:
        return None

    receita.estorno_de_id = despesa.id

    # Auto-classifica: estorno herda categoria + atribuição da compra
    if despesa.categoria_id and not receita.categoria_id:
        receita.categoria_id = despesa.categoria_id
        receita.categoria_origem = "estorno"
    if despesa.atribuicao_id and not receita.atribuicao_id:
        receita.atribuicao_id = despesa.atribuicao_id
        receita.atribuicao_origem = "estorno"

    session.flush()
    return despesa
