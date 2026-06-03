"""Saldo do extrato OFX: o LEDGERBAL só vale se o DTASOF estiver dentro do
período; saldos OFX que são 'snapshot atual' (não encadeiam entre meses) são
zerados na migração pra cair no cálculo acumulado.

Bug original: Santander carimba o LEDGERBAL com o saldo ATUAL no momento da
exportação, não o do fim do período → saldo inicial calculado vinha inflado
(ex.: conta aberta 16/03 zerada aparecia com saldo inicial de R$ 566,41).
"""
from datetime import date

from app.parsers.ofx import parse_extrato_ofx
from app.database import Conta, Fatura
from app.database import _corrigir_saldos_ofx_inconfiaveis


def _ofx(dtstart, dtend, dtasof, balamt, trns):
    """Monta um OFX Santander mínimo. trns: lista de (dtposted, amt)."""
    blocos = "".join(
        f"<STMTTRN><TRNTYPE>OTHER</TRNTYPE><DTPOSTED>{d}</DTPOSTED>"
        f"<TRNAMT>{a}</TRNAMT><FITID>{i}</FITID><MEMO>Mov {i}</MEMO></STMTTRN>"
        for i, (d, a) in enumerate(trns)
    )
    return f"""OFXHEADER:100
DATA:OFXSGML
ENCODING:USASCII
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>033</BANKID><ACCTID>123</ACCTID></BANKACCTFROM>
<BANKTRANLIST><DTSTART>{dtstart}</DTSTART><DTEND>{dtend}</DTEND>
{blocos}
</BANKTRANLIST>
<LEDGERBAL><BALAMT>{balamt}</BALAMT><DTASOF>{dtasof}</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


def _escreve(tmp_path, conteudo):
    p = tmp_path / "extrato.ofx"
    p.write_text(conteudo, encoding="utf-8")
    return str(p)


def test_dtasof_dentro_do_periodo_confia_no_saldo(tmp_path):
    # Saldo carimbado no fim do período (31/03) → confiável.
    ofx = _ofx("20260301", "20260331", "20260331", "238.46",
               [("20260316", "138.46"), ("20260320", "100.00")])
    out = parse_extrato_ofx(_escreve(tmp_path, ofx))
    assert out["saldo_final"] == 238.46
    # saldo_inicial = 238.46 - (138.46+100) = 0  → conta começou zerada
    assert abs(out["saldo_inicial"] - 0.0) < 0.01


def test_dtasof_fora_do_periodo_descarta_saldo(tmp_path):
    # LEDGERBAL carimbado em 30/04 (snapshot atual) num extrato de março.
    # Soma das transações de março = +238.46, mas o saldo informado é 804.87
    # (já com abril). Sem o guard, saldo_inicial sairia 566.41 (o bug).
    ofx = _ofx("20260301", "20260331", "20260430", "804.87",
               [("20260316", "138.46"), ("20260320", "100.00")])
    out = parse_extrato_ofx(_escreve(tmp_path, ofx))
    assert out["saldo_final"] is None
    assert out["saldo_inicial"] is None


def test_migracao_zera_saldos_que_nao_encadeiam(db):
    conta = Conta(nome="Santander", tipo="Conta Corrente")
    db.add(conta)
    db.commit()
    db.refresh(conta)

    # Cadeia QUEBRADA: março fecha 804.87 mas abril abre 208.46 (snapshot)
    db.add(Fatura(banco="Santander", conta_id=conta.id, mes_referencia="03/2026",
                  periodo_inicio=date(2026, 3, 1), periodo_fim=date(2026, 3, 31),
                  saldo_inicial=566.41, saldo_final=804.87))
    db.add(Fatura(banco="Santander", conta_id=conta.id, mes_referencia="04/2026",
                  periodo_inicio=date(2026, 4, 1), periodo_fim=date(2026, 4, 30),
                  saldo_inicial=208.46, saldo_final=774.87))
    db.commit()

    _corrigir_saldos_ofx_inconfiaveis(db.get_bind())

    for f in db.query(Fatura).filter(Fatura.conta_id == conta.id).all():
        db.refresh(f)
        assert f.saldo_inicial is None
        assert f.saldo_final is None


def test_migracao_preserva_saldos_que_encadeiam(db):
    conta = Conta(nome="Nubank", tipo="Conta Corrente")
    db.add(conta)
    db.commit()
    db.refresh(conta)

    # Cadeia OK: abril abre exatamente onde março fechou.
    db.add(Fatura(banco="Nubank", conta_id=conta.id, mes_referencia="03/2026",
                  periodo_inicio=date(2026, 3, 1), periodo_fim=date(2026, 3, 31),
                  saldo_inicial=0.0, saldo_final=500.0))
    db.add(Fatura(banco="Nubank", conta_id=conta.id, mes_referencia="04/2026",
                  periodo_inicio=date(2026, 4, 1), periodo_fim=date(2026, 4, 30),
                  saldo_inicial=500.0, saldo_final=700.0))
    db.commit()

    _corrigir_saldos_ofx_inconfiaveis(db.get_bind())

    saldos = sorted(
        (f.saldo_inicial, f.saldo_final)
        for f in db.query(Fatura).filter(Fatura.conta_id == conta.id).all()
    )
    assert saldos == [(0.0, 500.0), (500.0, 700.0)]
