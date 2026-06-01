"""Regressão: commit tolerante a conflito de concorrência.

A página de investimentos dispara várias requisições em paralelo; duas podiam
tentar inserir a mesma linha (UNIQUE em cdi_diario / configuracoes) ao mesmo
tempo, e o erro de flush "envenenava" a sessão (PendingRollbackError), quebrando
os endpoints. O commit tolerante faz rollback e deixa a sessão usável.
"""
from datetime import date

from app.cdi import _commit_tolerante
from app.database import CDIDiario, Configuracao


def test_commit_ok_retorna_true(db):
    db.add(CDIDiario(data=date(2026, 1, 2), taxa=0.05))
    assert _commit_tolerante(db) is True
    assert db.query(CDIDiario).count() == 1


def test_conflito_unique_faz_rollback_e_nao_quebra_sessao(db):
    db.add(CDIDiario(data=date(2026, 1, 1), taxa=0.05))
    db.commit()
    # Tenta inserir a MESMA data (UNIQUE) — simula o que um request concorrente
    # já gravou. O commit tolerante deve devolver False e NÃO deixar a sessão
    # em estado de erro.
    db.add(CDIDiario(data=date(2026, 1, 1), taxa=0.05))
    assert _commit_tolerante(db) is False
    # A sessão continua usável (sem PendingRollbackError):
    assert db.query(CDIDiario).count() == 1
    db.add(Configuracao(chave="ok_apos_rollback", valor="1"))
    assert _commit_tolerante(db) is True
    assert db.query(Configuracao).filter_by(chave="ok_apos_rollback").count() == 1
