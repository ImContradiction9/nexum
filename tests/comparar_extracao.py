"""
Harness de validação: compara a extração NOVA (pypdfium2) com a ANTIGA
(pdftotext/Poppler) em PDFs reais de fatura, e confere se os parsers produzem
as MESMAS transações pelos dois caminhos.

Uso:
    # 1. Coloque PDFs de fatura em tests/fixtures/ (ou passe uma pasta)
    python tests/comparar_extracao.py [pasta_com_pdfs] [--senha SENHA]

Requer o binário pdftotext (Poppler) instalado SÓ nesta máquina de dev, para
servir de "gabarito". O app em produção não depende mais dele.
"""
import sys
import os
import sqlite3
from pathlib import Path

# Garante import do pacote app a partir da raiz do projeto.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Console em UTF-8 (evita UnicodeEncodeError no cp1252 do Windows).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _senhas_cadastradas() -> list:
    """Lê as senhas de PDF salvas nas contas (data/financeiro.db)."""
    db = RAIZ / "data" / "financeiro.db"
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(str(db))
        rows = con.execute(
            "select distinct senha_pdf from contas "
            "where senha_pdf is not null and senha_pdf != ''"
        ).fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _extrair(pdf, senha, usar_poppler):
    if usar_poppler:
        os.environ["NEXUM_USAR_POPPLER"] = "1"
    else:
        os.environ.pop("NEXUM_USAR_POPPLER", None)
    # Reimporta helpers para pegar a flag atual.
    import importlib
    from app.parsers import helpers
    importlib.reload(helpers)
    return helpers.executar_pdftotext(str(pdf), senha=senha, layout=True)


def _parse(pdf, senhas, usar_poppler):
    """Tenta parsear o PDF com cada senha (None primeiro), como o app faz."""
    if usar_poppler:
        os.environ["NEXUM_USAR_POPPLER"] = "1"
    else:
        os.environ.pop("NEXUM_USAR_POPPLER", None)
    import importlib
    from app.parsers import helpers
    importlib.reload(helpers)
    # Recarrega os parsers para que usem o helpers recarregado.
    for mod in ("nubank", "bradesco", "santander", "mercadopago", "__init__"):
        try:
            importlib.reload(importlib.import_module(f"app.parsers.{mod}" if mod != "__init__" else "app.parsers"))
        except Exception:
            pass
    from app.parsers import parse_fatura
    from app.parsers.pdf_text import PDFProtegido

    ultimo_erro = None
    for s in [None] + list(senhas):
        try:
            return parse_fatura(str(pdf), senha=s)
        except PDFProtegido as e:
            ultimo_erro = e
            continue
    raise ultimo_erro or RuntimeError("não consegui abrir o PDF")


def _resumo(bill):
    txs = bill.get("transacoes", [])
    total = sum(t["valor"] for t in txs)
    chaves = sorted(
        (t["data_compra"].isoformat(), round(t["valor"], 2),
         (t.get("descricao") or "")[:30], t.get("parcela") or "")
        for t in txs
    )
    return len(txs), round(total, 2), chaves


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    senhas = _senhas_cadastradas()
    if "--senha" in sys.argv:
        senhas = [sys.argv[sys.argv.index("--senha") + 1]] + senhas
    print(f"(senhas disponíveis para tentar: {len(senhas)})")

    pasta = Path(args[0]) if args else (RAIZ / "tests" / "fixtures")
    if not pasta.exists():
        print(f"Pasta não encontrada: {pasta}")
        print("Crie tests/fixtures/ e coloque PDFs de fatura lá.")
        return 1

    # dedupe case-insensitive (no Windows, glob *.pdf e *.PDF batem nos mesmos arquivos)
    pdfs = sorted({p.resolve() for p in pasta.iterdir()
                   if p.suffix.lower() == ".pdf"})
    if not pdfs:
        print(f"Nenhum PDF em {pasta}")
        return 1

    falhas = 0
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            bill_novo = _parse(pdf, senhas, usar_poppler=False)
            n_n, tot_n, ch_n = _resumo(bill_novo)
            print(f"  NOVO (pypdfium2):  {bill_novo['banco']:<12} {n_n:>3} tx  R$ {tot_n:,.2f}")
        except BaseException as e:
            print(f"  NOVO  FALHOU: {e}")
            falhas += 1
            continue

        try:
            bill_velho = _parse(pdf, senhas, usar_poppler=True)
            n_v, tot_v, ch_v = _resumo(bill_velho)
            print(f"  VELHO (poppler):   {bill_velho['banco']:<12} {n_v:>3} tx  R$ {tot_v:,.2f}")
        except BaseException as e:
            print(f"  VELHO indisponível ({e}) — comparação pulada.")
            continue

        if ch_n == ch_v:
            print("  ✅ IDÊNTICO (mesmas transações)")
        else:
            falhas += 1
            print("  ❌ DIFERENTE!")
            so_novo = [c for c in ch_n if c not in ch_v]
            so_velho = [c for c in ch_v if c not in ch_n]
            for c in so_velho[:10]:
                print(f"     - só no VELHO: {c}")
            for c in so_novo[:10]:
                print(f"     + só no NOVO:  {c}")

    print(f"\n{'='*40}\n{'FALHAS: ' + str(falhas) if falhas else 'TUDO OK ✅'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
