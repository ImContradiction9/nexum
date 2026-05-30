"""Diagnóstico e manutenção: status/forçar migrações, extração de texto de PDF,
health-check e re-seed dos padrões. Extraído de main.py."""
import subprocess
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..deps import get_db, DB_PATH
from ..database import Categoria, Atribuicao, Regra
from ..seed import seed

router = APIRouter()


@router.post("/api/seed/reaplicar-padroes")
def reaplicar_padroes(db: Session = Depends(get_db)):
    """
    Reaplica as categorias, atribuições e regras padrão.
    Itens já existentes (mesmo nome) NÃO são tocados.
    Itens excluídos pelo usuário são recriados.
    Útil ao atualizar o app pra pegar categorias/regras novas.
    """
    # Conta antes pra mostrar diff
    n_cat_antes = db.query(Categoria).count()
    n_atr_antes = db.query(Atribuicao).count()
    n_reg_antes = db.query(Regra).count()

    seed(db, forcar=True)
    db.commit()

    return {
        "categorias_adicionadas": db.query(Categoria).count() - n_cat_antes,
        "atribuicoes_adicionadas": db.query(Atribuicao).count() - n_atr_antes,
        "regras_adicionadas": db.query(Regra).count() - n_reg_antes,
    }


@router.get("/api/_diagnostico/migracao")
def diagnostico_migracao(db: Session = Depends(get_db)):
    """Diagnóstico do estado da migração v1.7 (drop UNIQUE em contas.nome).
    Mostra DDL atual e índices. Use pra debugar."""
    from sqlalchemy import text
    out = {}
    ddl_row = db.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='contas'"
    )).fetchone()
    out["ddl_atual"] = ddl_row[0] if ddl_row else None
    out["tem_unique_no_ddl"] = bool(ddl_row and "UNIQUE" in (ddl_row[0] or "").upper())

    # Lista índices únicos
    indices = db.execute(text("PRAGMA index_list(contas)")).fetchall()
    out["indices"] = [
        {"name": r[1], "unique": bool(r[2]), "origin": r[3] if len(r) > 3 else None}
        for r in indices
    ]

    # Tenta inserir uma conta duplicada (rollback) pra ver se constraint ainda atua
    try:
        db.execute(text(
            "INSERT INTO contas (nome, tipo, banco, ativo) VALUES "
            "('__teste_dup__', 'Conta Corrente', 'TesteX', 1)"
        ))
        db.execute(text(
            "INSERT INTO contas (nome, tipo, banco, ativo) VALUES "
            "('__teste_dup__', 'Conta Corrente', 'TesteY', 1)"
        ))
        out["aceita_duplicata"] = True
    except Exception as e:
        out["aceita_duplicata"] = False
        out["erro_duplicata"] = str(e)
    finally:
        db.rollback()

    return out


@router.post("/api/_diagnostico/forcar_migracao_v17")
def forcar_migracao_v17(db: Session = Depends(get_db)):
    """Força a migração v1.7 (drop UNIQUE em contas.nome) manualmente.
    Útil quando a migração automática falhou silenciosamente."""
    from sqlalchemy import text
    import re as _re

    # 1. Pega DDL atual
    row = db.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='contas'"
    )).fetchone()
    if not row:
        raise HTTPException(500, "Tabela contas não existe")

    ddl_atual = row[0]

    if "UNIQUE" not in ddl_atual.upper():
        return {"ok": True, "ja_sem_unique": True, "ddl": ddl_atual}

    # Tenta dois padrões:
    # A) UNIQUE inline: `"nome" VARCHAR NOT NULL UNIQUE`
    # B) UNIQUE como constraint separada: `UNIQUE (nome),`  ou  `UNIQUE ("nome")`
    padrao_inline = _re.compile(
        r'("?nome"?\s+\w+(?:\([^)]*\))?\s*(?:NOT\s+NULL\s+)?)UNIQUE',
        _re.IGNORECASE,
    )
    padrao_separado = _re.compile(
        r',\s*UNIQUE\s*\(\s*"?nome"?\s*\)',
        _re.IGNORECASE,
    )

    if padrao_inline.search(ddl_atual):
        ddl_novo = padrao_inline.sub(r'\1', ddl_atual, count=1)
    elif padrao_separado.search(ddl_atual):
        ddl_novo = padrao_separado.sub('', ddl_atual, count=1)
    else:
        return {
            "ok": False,
            "erro": "DDL tem UNIQUE mas nenhum dos padrões casou",
            "ddl": ddl_atual,
        }

    ddl_novo = _re.sub(r'\s+,', ',', ddl_novo)
    ddl_novo = _re.sub(r'\s{2,}', ' ', ddl_novo)

    # 3. Pega lista de colunas
    cols_rows = db.execute(text("PRAGMA table_info(contas)")).fetchall()
    cols = [r[1] for r in cols_rows]
    cols_quoted = ", ".join(f'"{c}"' for c in cols)

    # 4. Recria tabela em transação manual
    db.execute(text('DROP TABLE IF EXISTS "contas_old_v17"'))
    db.execute(text('ALTER TABLE "contas" RENAME TO "contas_old_v17"'))
    db.execute(text(ddl_novo))
    db.execute(text(
        f'INSERT INTO "contas" ({cols_quoted}) SELECT {cols_quoted} FROM "contas_old_v17"'
    ))
    db.execute(text('DROP TABLE "contas_old_v17"'))
    db.commit()

    return {
        "ok": True,
        "ddl_anterior": ddl_atual,
        "ddl_novo": ddl_novo,
    }


@router.get("/api/health")
def health():
    return {"ok": True, "db": DB_PATH}


@router.get("/api/diagnostico/pdftotext")
def diagnostico_pdftotext():
    """
    Diagnóstico do pdftotext: mostra qual executável foi encontrado,
    a versão, e se está acessível. Útil pra depurar problemas de importação.
    """
    import subprocess
    from app.parsers.helpers import _localizar_pdftotext

    resultado = {
        "caminho_encontrado": None,
        "versao": None,
        "executavel_ok": False,
        "erro": None,
    }
    try:
        caminho = _localizar_pdftotext()
        resultado["caminho_encontrado"] = caminho
        try:
            proc = subprocess.run(
                [caminho, "-v"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
            saida = (proc.stderr or "") + (proc.stdout or "")
            resultado["versao"] = saida.strip()[:300]
            resultado["executavel_ok"] = True
        except FileNotFoundError:
            resultado["erro"] = f"Executavel nao encontrado: {caminho}"
        except Exception as e:
            resultado["erro"] = f"Erro ao executar: {type(e).__name__}: {e}"
    except Exception as e:
        resultado["erro"] = f"Erro ao localizar: {type(e).__name__}: {e}"

    return resultado


@router.post("/api/diagnostico/extrair-texto")
async def diagnostico_extrair_texto(arquivo: UploadFile = File(...)):
    """
    Diagnóstico: recebe um PDF e devolve o texto bruto que o pdftotext extrai.
    Não salva nada no banco. Só pra depurar por que um parser falha.
    """
    import tempfile
    import os as _os
    from app.parsers.helpers import executar_pdftotext

    resultado = {
        "nome_arquivo": arquivo.filename,
        "tamanho_bytes": 0,
        "texto_extraido": None,
        "linhas": 0,
        "primeiras_40_linhas": [],
        "erro": None,
    }

    tmp_path = None
    try:
        conteudo = await arquivo.read()
        resultado["tamanho_bytes"] = len(conteudo)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(conteudo)
            tmp_path = tmp.name

        texto = executar_pdftotext(tmp_path, layout=True)
        resultado["texto_extraido"] = texto[:5000]
        linhas = texto.splitlines()
        resultado["linhas"] = len(linhas)
        resultado["primeiras_40_linhas"] = linhas[:40]
    except Exception as e:
        resultado["erro"] = f"{type(e).__name__}: {e}"
    finally:
        if tmp_path and _os.path.exists(tmp_path):
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass

    return resultado
