"""
Bootstrap compartilhado do app: caminho do banco, backup, engine, sessão e a
dependência get_db. Centraliza o que main.py e os routers precisam, evitando
import circular (routers importam daqui, nunca de main).
"""
import os
from pathlib import Path

from .database import init_db, get_session
from .backup import fazer_backup

# Caminho do banco (env permite isolar em testes).
DB_PATH = os.environ.get(
    "FINANCEIRO_DB",
    str(Path(__file__).parent.parent / "data" / "financeiro.db"),
)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# Backup ANTES das migrações (cópia pré-migração fica salva).
fazer_backup(DB_PATH)

engine = init_db(DB_PATH)
SessionLocal = get_session(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
