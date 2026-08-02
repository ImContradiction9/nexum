"""Mapa de cobertura: um extrato OFX de conta corrente cobre vários meses num
arquivo só. A Fatura fica rotulada num mês (ex.: 06), mas contém transações de
outros (ex.: 05). O mês deve contar como coberto se há transações dele — não só
se existe Fatura com aquele mes_referencia (bug: 05 aparecia faltando).

Também cobre a exclusão de fatura (limpeza de referências órfãs)."""
from datetime import date

from app.database import Conta, Fatura, Transacao
from app.routers.faturas import cobertura_arquivos, excluir_fatura


def _tx(db, conta, fatura, mes, dia):
    t = Transacao(
        conta_id=conta.id, fatura_id=fatura.id, data=date(2026, int(mes[:2]), dia),
        descricao="X", descricao_normalizada="x", valor=10.0, tipo="Despesa",
        mes_referencia=mes,
    )
    db.add(t); db.commit()
    return t


def test_lancamento_manual_nao_marca_mes_como_coberto(db):
    """Transação SEM fatura_id (lançamento manual) não pode cobrir o mês —
    mascararia exatamente o buraco de importação que o mapa detecta."""
    conta = Conta(nome="Santander", tipo="Conta Corrente", ativo=True)
    db.add(conta); db.commit(); db.refresh(conta)
    fat = Fatura(conta_id=conta.id, mes_referencia="04/2026", banco="Santander")
    db.add(fat); db.commit(); db.refresh(fat)
    _tx(db, conta, fat, "04/2026", 10)
    _tx(db, conta, fat, "06/2026", 3)
    # 05/2026 só tem um lançamento manual (sem arquivo)
    t = Transacao(conta_id=conta.id, data=date(2026, 5, 15), descricao="Manual",
                  descricao_normalizada="manual", valor=50.0, tipo="Despesa",
                  mes_referencia="05/2026")
    db.add(t); db.commit()

    res = cobertura_arquivos(meses=12, db=db)
    conta_res = next(c for c in res["contas"] if c["id"] == conta.id)
    por_mes = {x["mes"]: x for x in conta_res["cobertura"]}
    assert por_mes["05/2026"]["tem"] is False
    assert por_mes["05/2026"]["status"] == "buraco"


def test_eixo_de_meses_continuo_mostra_mes_sem_nada_como_buraco(db):
    """Mês sem transação em conta NENHUMA precisa aparecer no eixo (antes sumia
    e o buraco ficava invisível)."""
    conta = Conta(nome="Nubank", tipo="Cartão de Crédito", ativo=True)
    db.add(conta); db.commit(); db.refresh(conta)
    for mes in ("03/2026", "06/2026"):   # 04 e 05 sem nada no sistema inteiro
        fat = Fatura(conta_id=conta.id, mes_referencia=mes, banco="Nubank")
        db.add(fat); db.commit(); db.refresh(fat)
        _tx(db, conta, fat, mes, 5)

    res = cobertura_arquivos(meses=6, db=db)
    assert "04/2026" in res["meses"] and "05/2026" in res["meses"]
    conta_res = next(c for c in res["contas"] if c["id"] == conta.id)
    por_mes = {x["mes"]: x for x in conta_res["cobertura"]}
    assert por_mes["04/2026"]["status"] == "buraco"
    assert por_mes["05/2026"]["status"] == "buraco"


def test_mes_coberto_por_transacao_mesmo_sem_fatura_daquele_mes(db):
    conta = Conta(nome="Santander", tipo="Conta Corrente", ativo=True)
    db.add(conta); db.commit(); db.refresh(conta)
    # Uma única fatura (OFX multi-mês) rotulada 06/2026...
    fat = Fatura(conta_id=conta.id, mes_referencia="06/2026", banco="Santander")
    db.add(fat); db.commit(); db.refresh(fat)
    # ...mas com transações de 05 E 06 (o arquivo cobre os dois).
    _tx(db, conta, fat, "05/2026", 20)
    _tx(db, conta, fat, "06/2026", 3)

    res = cobertura_arquivos(meses=12, db=db)
    conta_res = next(c for c in res["contas"] if c["id"] == conta.id)
    por_mes = {x["mes"]: x for x in conta_res["cobertura"]}
    # 05/2026 tem transações (via fatura rotulada 06) → coberto, apontando pra fatura
    assert por_mes["05/2026"]["tem"] is True
    assert por_mes["05/2026"]["fatura_id"] == fat.id
    assert por_mes["06/2026"]["tem"] is True
    assert conta_res["buracos"] == 0

def test_excluir_fatura_limpa_referencias_orfas(db):
    """SQLite não aplica FK: excluir a fatura precisa apagar as FILHAS de
    divisão (nascem sem fatura_id) e limpar ponteiros de fora (pagamento de
    fatura, estorno) — senão órfãos seguem contando nos totais."""
    conta = Conta(nome="Nubank", tipo="Cartão de Crédito", ativo=True)
    cc = Conta(nome="Nubank CC", tipo="Conta Corrente", ativo=True)
    db.add_all([conta, cc]); db.commit(); db.refresh(conta); db.refresh(cc)
    fat = Fatura(conta_id=conta.id, mes_referencia="05/2026", banco="Nubank")
    db.add(fat); db.commit(); db.refresh(fat)

    pai = _tx(db, conta, fat, "05/2026", 10)
    pai.dividida = True
    filha = Transacao(conta_id=conta.id, parte_de_id=pai.id, data=pai.data,
                      descricao="parte", descricao_normalizada="parte", valor=5.0,
                      tipo="Despesa", mes_referencia="05/2026")
    # Transação do EXTRATO que paga esta fatura (outra conta, sem fatura)
    pagto = Transacao(conta_id=cc.id, data=date(2026, 6, 5), descricao="PGTO FATURA",
                      descricao_normalizada="pgto", valor=10.0, tipo="Despesa",
                      mes_referencia="06/2026", pagamento_de_fatura_id=fat.id,
                      conciliada=True)
    # Estorno em outra fatura apontando pra uma transação desta
    estorno = Transacao(conta_id=conta.id, data=date(2026, 6, 8), descricao="ESTORNO",
                        descricao_normalizada="estorno", valor=10.0, tipo="Receita",
                        mes_referencia="06/2026", estorno_de_id=pai.id)
    db.add_all([filha, pagto, estorno]); db.commit()

    ids = {"fat": fat.id, "pai": pai.id, "filha": filha.id,
           "pagto": pagto.id, "estorno": estorno.id}
    excluir_fatura(ids["fat"], db=db)
    db.expunge_all()   # o delete em bulk não expira objetos já carregados na sessão

    assert db.query(Fatura).get(ids["fat"]) is None
    assert db.query(Transacao).get(ids["pai"]) is None
    assert db.query(Transacao).get(ids["filha"]) is None   # filha não vira órfã
    pagto2 = db.query(Transacao).get(ids["pagto"])
    estorno2 = db.query(Transacao).get(ids["estorno"])
    assert pagto2.pagamento_de_fatura_id is None
    assert pagto2.conciliada is False
    assert estorno2.estorno_de_id is None
