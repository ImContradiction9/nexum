"""Testes de saldos da carteira e progresso/projeção de metas (app/main.py)."""
import json
from datetime import date, timedelta

import pytest

from app.database import Ativo, OperacaoInvestimento, CDIDiario, Meta
from app.routers.investimentos import _serializar_ativo
from app.routers.metas import (
    _calcular_saldos_brl, _serializar_meta,
    _calcular_progresso_meta, _taxa_anual_meta,
)


def _ativo(db, **kw):
    a = Ativo(nome=kw.pop("nome", "Ativo"), tipo=kw.pop("tipo", "CDB"),
              moeda=kw.pop("moeda", "BRL"), ativo=True, **kw)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _op(db, ativo, tipo, valor, dias_atras=10, **kw):
    op = OperacaoInvestimento(
        ativo_id=ativo.id, tipo=tipo, valor_total=valor,
        data=date.today() - timedelta(days=dias_atras), **kw,
    )
    db.add(op)
    db.commit()
    return op


# --------------------------------------------------------------------------
# Saldo da carteira
# --------------------------------------------------------------------------
def test_saldo_conta_operacoes_sem_saldo_manual(db):
    """Regressão: meta/dashboard zeravam ativos sem saldo manual (bug corrigido)."""
    a = _ativo(db, nome="Caixinha", tipo="RDB")  # sem cdi_percentual, sem saldo manual
    _op(db, a, "Compra", 10000.0)
    saldos = _calcular_saldos_brl(db)
    assert saldos["por_tipo"]["RDB"] == pytest.approx(10000.0)
    assert saldos["por_ativo"][a.id] == pytest.approx(10000.0)
    assert saldos["total_brl"] == pytest.approx(10000.0)


def test_saldo_manual_tem_prioridade(db):
    a = _ativo(db, nome="Com saldo", tipo="CDB", saldo_atual=12345.0)
    _op(db, a, "Compra", 10000.0)
    ser = _serializar_ativo(a, [], cdi_serie={})
    assert ser["saldo_atual"] == pytest.approx(12345.0)
    assert ser["cdi_auto"] is False


def test_cdi_auto_acumula_rendimento(db):
    a = _ativo(db, nome="CDB CDI", tipo="CDB", cdi_percentual=100.0)
    _op(db, a, "Compra", 1000.0, dias_atras=3)
    # Série CDI dos últimos dias.
    for i in range(0, 4):
        db.add(CDIDiario(data=date.today() - timedelta(days=i), taxa=0.05))
    db.commit()
    ops = db.query(OperacaoInvestimento).all()
    serie = {c.data: c.taxa for c in db.query(CDIDiario).all()}
    ser = _serializar_ativo(a, ops, serie)
    assert ser["cdi_auto"] is True
    assert ser["saldo_atual"] > 1000.0          # rendeu
    assert ser["rentab_moeda"] > 0


def test_cdi_sem_serie_cai_no_calculo_de_operacoes(db):
    """Offline (série vazia) não deve produzir saldo errado/negativo."""
    a = _ativo(db, nome="CDB", tipo="CDB", cdi_percentual=100.0)
    _op(db, a, "Compra", 1000.0)
    _op(db, a, "Resgate", 1000.0, dias_atras=1)
    ser = _serializar_ativo(a, db.query(OperacaoInvestimento).all(), cdi_serie={})
    assert ser["cdi_auto"] is False
    assert ser["saldo_atual"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Metas — escopos
# --------------------------------------------------------------------------
def test_meta_tipos_ativo_soma_por_classe(db):
    rdb = _ativo(db, nome="RDB1", tipo="RDB")
    cdb = _ativo(db, nome="CDB1", tipo="CDB")
    _op(db, rdb, "Compra", 5000.0)
    _op(db, cdb, "Compra", 3000.0)
    saldos = _calcular_saldos_brl(db)
    m = Meta(nome="RF", escopo="tipos_ativo", escopo_tipos=json.dumps(["RDB"]), valor_alvo=10000)
    d = _serializar_meta(m, saldos)
    assert d["valor_atual"] == pytest.approx(5000.0)   # só RDB, não CDB


def test_meta_ativos_especificos(db):
    a1 = _ativo(db, nome="Reserva", tipo="RDB")
    a2 = _ativo(db, nome="Outro", tipo="RDB")
    _op(db, a1, "Compra", 7000.0)
    _op(db, a2, "Compra", 2000.0)
    saldos = _calcular_saldos_brl(db)
    m = Meta(nome="Só a1", escopo="ativos", escopo_ativos=json.dumps([a1.id]), valor_alvo=10000)
    d = _serializar_meta(m, saldos)
    assert d["valor_atual"] == pytest.approx(7000.0)   # diferencia dois RDB
    assert d["escopo_ativos"] == [a1.id]


# --------------------------------------------------------------------------
# Projeção composta
# --------------------------------------------------------------------------
def _saldos_fake(total, ritmo, taxa_anual):
    return {
        "total_brl": total, "por_tipo": {}, "por_ativo": {},
        "ritmo_mensal_brl": ritmo, "ritmo_por_tipo_mensal": {}, "ritmo_por_ativo_mensal": {},
        "taxa_anual_por_tipo": {}, "taxa_anual_por_ativo": {},
        "taxa_anual_total": taxa_anual, "cdi_anual": taxa_anual,
    }


def test_projecao_composta_atinge_meta_so_com_rendimento():
    # Sem aportes, mas com 20% a.a., R$10k vira R$20k em algum momento (linear seria 'nunca').
    m = Meta(nome="Dobrar", escopo="patrimonio_total", valor_alvo=20000)
    saldos = _saldos_fake(total=10000, ritmo=0, taxa_anual=0.20)
    d = _calcular_progresso_meta(m, saldos)
    assert d["meses_projetados"] is not None
    assert 40 <= d["meses_projetados"] <= 50   # ~46 meses pra dobrar a 20% a.a.


def test_taxa_override_da_meta_tem_prioridade():
    m = Meta(nome="X", escopo="patrimonio_total", valor_alvo=100, taxa_retorno_anual=15.0)
    saldos = _saldos_fake(total=50, ritmo=0, taxa_anual=0.05)
    assert _taxa_anual_meta(m, saldos) == pytest.approx(0.15)


# --------------------------------------------------------------------------
# Saldo líquido (IR + IOF) na carteira e nas metas
# --------------------------------------------------------------------------
def test_saldo_liquido_cdb_desconta_ir(db):
    # CDB com saldo manual 11000 e aporte 10000 há ~800 dias → rendimento 1000,
    # prazo longo (IR 15%, sem IOF) → líquido 10850.
    a = _ativo(db, nome="CDB longo", tipo="CDB", saldo_atual=11000.0)
    _op(db, a, "Compra", 10000.0, dias_atras=800)
    ser = _serializar_ativo(a, db.query(OperacaoInvestimento).all(), cdi_serie={})
    assert ser["saldo_atual"] == pytest.approx(11000.0)        # bruto intacto
    assert ser["ir_aliquota"] == 0.15
    assert ser["iof_valor"] == 0.0
    assert ser["saldo_liquido"] == pytest.approx(10850.0)
    assert ser["isento_ir"] is False


def test_saldo_liquido_lci_isento(db):
    a = _ativo(db, nome="LCI", tipo="LCI", saldo_atual=11000.0)
    _op(db, a, "Compra", 10000.0, dias_atras=800)
    ser = _serializar_ativo(a, db.query(OperacaoInvestimento).all(), cdi_serie={})
    assert ser["isento_ir"] is True
    assert ser["saldo_liquido"] == pytest.approx(11000.0)      # nada de IR


def test_renda_variavel_nao_deduz(db):
    a = _ativo(db, nome="Ação", tipo="Ação BR", saldo_atual=5000.0)
    _op(db, a, "Compra", 3000.0, dias_atras=800)
    ser = _serializar_ativo(a, db.query(OperacaoInvestimento).all(), cdi_serie={})
    assert ser["saldo_liquido"] == pytest.approx(5000.0)       # RV não entra no escopo


def test_meta_usa_saldo_liquido(db):
    a = _ativo(db, nome="CDB meta", tipo="CDB", saldo_atual=11000.0)
    _op(db, a, "Compra", 10000.0, dias_atras=800)
    saldos = _calcular_saldos_brl(db)
    assert saldos["total_brl"] == pytest.approx(11000.0)
    assert saldos["total_liquido_brl"] == pytest.approx(10850.0)
    m = Meta(nome="Patrimônio", escopo="patrimonio_total", valor_alvo=20000)
    d = _serializar_meta(m, saldos)
    assert d["valor_atual"] == pytest.approx(10850.0)          # líquido
    assert d["valor_atual_bruto"] == pytest.approx(11000.0)    # bruto p/ referência


def test_aporte_necessario_menor_com_rendimento():
    alvo = 120000
    data_alvo = date.today() + timedelta(days=365)
    m_sem = Meta(nome="sem", escopo="patrimonio_total", valor_alvo=alvo,
                 data_alvo=data_alvo, taxa_retorno_anual=0.0)
    m_com = Meta(nome="com", escopo="patrimonio_total", valor_alvo=alvo,
                 data_alvo=data_alvo, taxa_retorno_anual=12.0)
    saldos = _saldos_fake(total=10000, ritmo=0, taxa_anual=0.0)
    a_sem = _calcular_progresso_meta(m_sem, saldos)["aporte_mensal_necessario"]
    a_com = _calcular_progresso_meta(m_com, saldos)["aporte_mensal_necessario"]
    assert a_com < a_sem   # o rendimento ajuda a bater a meta com aportes menores
