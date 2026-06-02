"""Metas: ativos a IGNORAR (excluir do cálculo) em patrimônio total / por tipo."""
import json

from app.database import Meta
from app.routers.metas import _calcular_progresso_meta


def _saldos():
    return {
        "total_brl": 1000.0, "total_liquido_brl": 1000.0,
        "por_tipo": {"CDB": 600.0, "ETF Internacional": 400.0},
        "por_tipo_liquido": {"CDB": 600.0, "ETF Internacional": 400.0},
        "por_ativo": {1: 600.0, 2: 400.0},
        "por_ativo_liquido": {1: 600.0, 2: 400.0},
        "ritmo_mensal_brl": 100.0,
        "ritmo_por_tipo_mensal": {"CDB": 60.0, "ETF Internacional": 40.0},
        "ritmo_por_ativo_mensal": {1: 60.0, 2: 40.0},
        "tipo_por_ativo": {1: "CDB", 2: "ETF Internacional"},
        "taxa_anual_total": 0.0, "taxa_anual_liq_total": 0.0,
        "taxa_anual_por_tipo": {}, "taxa_anual_liq_por_tipo": {},
        "taxa_anual_por_ativo": {}, "taxa_anual_liq_por_ativo": {},
        "cdi_anual": 0.0,
    }


def test_patrimonio_total_ignora_ativo():
    m = Meta(nome="x", escopo="patrimonio_total", valor_alvo=10000.0,
             escopo_excluir_ativos=json.dumps([1]))
    prog = _calcular_progresso_meta(m, _saldos())
    assert prog["valor_atual"] == 400.0          # 1000 - 600 (ativo 1 ignorado)
    assert prog["ritmo_mensal_estimado"] == 40.0  # 100 - 60


def test_sem_exclusao_conta_tudo():
    m = Meta(nome="x", escopo="patrimonio_total", valor_alvo=10000.0)
    prog = _calcular_progresso_meta(m, _saldos())
    assert prog["valor_atual"] == 1000.0


def test_tipos_ativo_ignora_so_dentro_do_escopo():
    # escopo = só CDB; ignorar ativo 2 (ETF, fora do tipo) não muda nada
    m = Meta(nome="x", escopo="tipos_ativo", valor_alvo=10000.0,
             escopo_tipos=json.dumps(["CDB"]), escopo_excluir_ativos=json.dumps([2]))
    assert _calcular_progresso_meta(m, _saldos())["valor_atual"] == 600.0
    # ignorar ativo 1 (CDB, dentro do escopo) zera
    m2 = Meta(nome="x", escopo="tipos_ativo", valor_alvo=10000.0,
              escopo_tipos=json.dumps(["CDB"]), escopo_excluir_ativos=json.dumps([1]))
    assert _calcular_progresso_meta(m2, _saldos())["valor_atual"] == 0.0
