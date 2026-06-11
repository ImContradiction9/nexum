"""Pró-labore: registro de quanto o usuário JÁ retirou vs quanto FALTA retirar.

O usuário tem um pró-labore mensal fixo (configurável POR ANO), mas nem sempre
retira o valor cheio (deixa parte na empresa). Este módulo cruza:

- "pego"   = soma das receitas categorizadas como "Pró-labore" no ano (automático);
- "devido" = mensal do ano × meses DECORRIDOS (ano atual conta só os meses já
             passados; anos anteriores contam 12);
- "falta"  = devido − pego (o que ainda dá pra retirar da empresa).

O valor mensal de cada ano fica em Configuracao (chave `prolabore_mensal_por_ano`,
JSON {ano: valor}).
"""
import json
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Configuracao, Categoria, Transacao

router = APIRouter()

_CFG_CHAVE = "prolabore_mensal_por_ano"
_CFG_PEGO_MANUAL = "prolabore_pego_manual_por_ano"
_CAT_NOME = "Pró-labore"


def _mapa_int_float(db: Session, chave: str) -> dict:
    """Lê um Configuracao JSON {ano: valor} e devolve {int: float}."""
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    try:
        bruto = json.loads(c.valor) if (c and c.valor) else {}
    except (ValueError, TypeError):
        return {}
    out = {}
    for ano, v in bruto.items():
        try:
            out[int(ano)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _mensal_por_ano(db: Session) -> dict:
    return _mapa_int_float(db, _CFG_CHAVE)


def _pego_por_ano(db: Session) -> dict:
    """Soma das receitas 'Pró-labore' por ano-calendário (data da transação)."""
    cat = db.query(Categoria).filter(Categoria.nome == _CAT_NOME).first()
    if not cat:
        return {}, False
    rows = (db.query(func.strftime("%Y", Transacao.data), func.sum(Transacao.valor))
            .filter(
                Transacao.categoria_id == cat.id,
                Transacao.tipo == "Receita",
                (Transacao.suspeita_duplicata == False) | Transacao.suspeita_duplicata.is_(None),
                (Transacao.dividida == False) | Transacao.dividida.is_(None),
            )
            .group_by(func.strftime("%Y", Transacao.data))
            .all())
    out = {}
    for ano_str, soma in rows:
        if ano_str:
            out[int(ano_str)] = soma or 0.0
    return out, True


def _meses_decorridos(ano: int, hoje: date) -> int:
    if ano < hoje.year:
        return 12
    if ano == hoje.year:
        return hoje.month
    return 0  # ano futuro


@router.get("/api/prolabore")
def resumo_prolabore(db: Session = Depends(get_db)):
    hoje = date.today()
    mensal = _mensal_por_ano(db)
    pego_auto, tem_categoria = _pego_por_ano(db)
    pego_manual = _mapa_int_float(db, _CFG_PEGO_MANUAL)

    anos = sorted(set(mensal) | set(pego_auto) | set(pego_manual))
    linhas = []
    total_devido = total_pego = total_falta = 0.0
    for ano in anos:
        m = mensal.get(ano, 0.0)
        meses = _meses_decorridos(ano, hoje)
        devido = round(m * meses, 2)
        auto = round(pego_auto.get(ano, 0.0), 2)
        # "Peguei" efetivo: override manual vence o automático das transações.
        tem_manual = ano in pego_manual
        pg = round(pego_manual[ano], 2) if tem_manual else auto
        falta = round(devido - pg, 2)
        linhas.append({
            "ano": ano, "mensal": round(m, 2), "meses": meses,
            "devido": devido, "pego": pg, "pego_auto": auto,
            "pego_manual": tem_manual, "falta": falta,
        })
        total_devido += devido
        total_pego += pg
        total_falta += falta

    return {
        "linhas": linhas,
        "total_devido": round(total_devido, 2),
        "total_pego": round(total_pego, 2),
        "total_falta": round(total_falta, 2),
        "ano_atual": hoje.year,
        "mes_atual": hoje.month,
        "tem_categoria": tem_categoria,
        "configurado": bool(mensal),
    }


def _limpar_mapa(bruto: dict, permitir_zero: bool = False) -> dict:
    """{ano: valor} → {str(ano): round(valor,2)}; descarta inválidos e (por
    padrão) <=0. `permitir_zero=True` mantém 0 (ex.: peguei zero num ano)."""
    limpo = {}
    for ano, v in (bruto or {}).items():
        try:
            a = int(ano)
            pv = float(v)
        except (TypeError, ValueError):
            continue
        if pv > 0 or (permitir_zero and pv >= 0):
            limpo[str(a)] = round(pv, 2)
    return limpo


def _salvar_cfg_json(db: Session, chave: str, mapa: dict):
    c = db.query(Configuracao).filter(Configuracao.chave == chave).first()
    if not c:
        c = Configuracao(chave=chave, valor="")
        db.add(c)
    c.valor = json.dumps(mapa)


@router.post("/api/prolabore/config")
def salvar_prolabore_config(dados: dict, db: Session = Depends(get_db)):
    """Define o pró-labore mensal e (opcional) o "peguei" manual por ano:
      body {mensal_por_ano: {ano: valor}, pego_manual_por_ano: {ano: valor}}.
    `mensal`: valores <=0 limpam o ano. `pego_manual`: override do automático
    (use pra anos sem transações no app); ausência do ano = volta ao automático."""
    _salvar_cfg_json(db, _CFG_CHAVE, _limpar_mapa(dados.get("mensal_por_ano")))
    if "pego_manual_por_ano" in dados:
        _salvar_cfg_json(db, _CFG_PEGO_MANUAL,
                         _limpar_mapa(dados.get("pego_manual_por_ano"), permitir_zero=True))
    db.commit()
    return resumo_prolabore(db)
