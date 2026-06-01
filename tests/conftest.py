"""
Configuração dos testes.

- Isola o banco: aponta FINANCEIRO_DB para um arquivo temporário ANTES de
  importar app.main (que cria engine/seed no import). Assim os testes nunca
  tocam data/financeiro.db.
- Desliga a rede do CDI: troca cdi.sincronizar por no-op, então _cdi_serie
  lê apenas o que o teste inserir em cdi_diario.
- Fixture `db`: uma sessão isolada por teste, com schema limpo.
"""
import os
import tempfile

# Precisa vir ANTES de qualquer import de app.main.
os.environ["FINANCEIRO_DB"] = os.path.join(tempfile.gettempdir(), "nexum_test_import.db")

import pytest

from app import cdi as cdi_mod
from app import cambio as cambio_mod
from app.database import init_db, get_session


@pytest.fixture(autouse=True)
def _sem_rede_cdi(monkeypatch):
    """Nenhum teste deve bater na API do Banco Central (CDI nem câmbio)."""
    monkeypatch.setattr(
        cdi_mod, "sincronizar",
        lambda *a, **k: {"ok": True, "atualizado": False, "dias_baixados": 0, "erro": None},
    )
    monkeypatch.setattr(
        cambio_mod, "sincronizar",
        lambda *a, **k: {"ok": True, "atualizado": False, "erro": None},
    )


@pytest.fixture
def db(tmp_path):
    engine = init_db(str(tmp_path / "teste.db"))
    Session = get_session(engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
