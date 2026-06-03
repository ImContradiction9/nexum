"""_merge_categoria: mescla uma categoria em outra (repointa transações/regras/
memórias e remove a origem). Usado em 1.0.43 pra mesclar Salário em Pró-labore."""
from datetime import date

from app.database import _merge_categoria, Categoria, Conta, Transacao, Regra


def _setup(db):
    sal = Categoria(nome="Salário", tipo="Receita")
    pro = Categoria(nome="Pró-labore", tipo="Receita")
    conta = Conta(nome="Conta", tipo="Conta Corrente")
    db.add_all([sal, pro, conta])
    db.commit()
    db.refresh(sal); db.refresh(pro); db.refresh(conta)
    db.add(Transacao(conta_id=conta.id, data=date(2026, 1, 5), descricao="PIX",
                     valor=1000.0, tipo="Receita", mes_referencia="01/2026",
                     categoria_id=sal.id, categoria_origem="manual"))
    db.add(Regra(palavra_chave="SALARIO", categoria_id=sal.id, prioridade=5))
    db.commit()
    return sal.id, pro.id


def test_merge_move_dados_e_remove_origem(db):
    sal_id, pro_id = _setup(db)
    _merge_categoria(db.get_bind(), "Salário", "Pró-labore")

    assert db.query(Categoria).filter(Categoria.nome == "Salário").first() is None
    assert db.query(Transacao).filter(Transacao.categoria_id == sal_id).count() == 0
    assert db.query(Transacao).filter(Transacao.categoria_id == pro_id).count() == 1
    assert db.query(Regra).filter(Regra.categoria_id == pro_id).count() == 1


def test_merge_idempotente_e_origem_inexistente(db):
    _setup(db)
    _merge_categoria(db.get_bind(), "Salário", "Pró-labore")
    # Rodar de novo (origem já não existe) não deve quebrar nem mexer no destino.
    _merge_categoria(db.get_bind(), "Salário", "Pró-labore")
    pro = db.query(Categoria).filter(Categoria.nome == "Pró-labore").first()
    assert pro is not None
    assert db.query(Transacao).filter(Transacao.categoria_id == pro.id).count() == 1
