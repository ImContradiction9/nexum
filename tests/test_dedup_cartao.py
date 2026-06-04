"""
Regressão de dedup de faturas (causa de totais divergentes):

1. O hash inclui o cartão → a MESMA compra em cartões diferentes da fatura
   (titular + adicionais) não colide (ex.: dois "SEGURO 9,99").
2. Hashes antigos (sem cartão) continuam idênticos → não duplica dados gravados.
3. Importação não deduplica linhas DENTRO da própria fatura: duas cobranças
   genuinamente idênticas no mesmo dia/cartão (ex.: dois pedágios) entram ambas.
"""
import os
import tempfile
from datetime import date

from app.utils import hash_dedup
from app.database import init_db, get_session, Banco, Conta, Fatura, Transacao
from app.importacao import importar_pdf  # noqa: F401 (garante import sem erro)


def test_hash_inclui_cartao():
    base = ("Santander", date(2026, 2, 3), 9.99, "SEGURO SUPERPROTEGIDO")
    h_2028 = hash_dedup(*base, cartao="2028")
    h_2023 = hash_dedup(*base, cartao="2023")
    assert h_2028 != h_2023            # cartões diferentes → hashes diferentes
    # mesmo cartão → mesmo hash
    assert h_2028 == hash_dedup(*base, cartao="2028")


def test_hash_sem_cartao_inalterado():
    # Sem cartão o hash é idêntico ao formato antigo (compat com dados gravados).
    base = ("Santander", date(2026, 2, 3), 9.99, "NETFLIX")
    assert hash_dedup(*base) == hash_dedup(*base, cartao=None)
    # E é diferente da variante com cartão.
    assert hash_dedup(*base) != hash_dedup(*base, cartao="1234")


def _mk_db():
    eng = init_db(str(tempfile.mktemp(suffix=".db")))
    s = get_session(eng)()
    b = Banco(nome="Santander")
    s.add(b)
    s.flush()
    conta = Conta(nome="Santander", tipo="Cartão de Crédito", banco_id=b.id)
    s.add(conta)
    s.flush()
    return s, conta


def test_linhas_identicas_na_mesma_fatura_entram_ambas():
    """Simula o efeito do dedup da importação: a query de duplicata exclui a
    própria fatura, então duas linhas idênticas do mesmo PDF não se anulam."""
    from sqlalchemy import or_
    s, conta = _mk_db()
    fat = Fatura(banco="Santander", conta_id=conta.id, mes_referencia="05/2026")
    s.add(fat)
    s.flush()

    h = hash_dedup("Santander", date(2026, 4, 7), 9.80, "CONCESSIONARIA LITORAL",
                   cartao="8547")
    inseridas = 0
    for _ in range(2):  # duas cobranças idênticas (dois pedágios)
        existente = s.query(Transacao).filter(
            Transacao.hash_dedup == h,
            Transacao.conta_id == conta.id,
            or_(Transacao.fatura_id != fat.id, Transacao.fatura_id.is_(None)),
        ).first()
        assert existente is None       # nunca acha duplicata dentro da mesma fatura
        s.add(Transacao(
            fatura_id=fat.id, conta_id=conta.id, data=date(2026, 4, 7),
            descricao="CONCESSIONARIA LITORAL", valor=9.80, tipo="Despesa",
            mes_referencia="05/2026", hash_dedup=h, cartao_final="8547",
        ))
        s.flush()
        inseridas += 1

    assert inseridas == 2
    soma = sum(t.valor for t in s.query(Transacao).filter(Transacao.fatura_id == fat.id))
    assert round(soma, 2) == 19.60
    s.close()
