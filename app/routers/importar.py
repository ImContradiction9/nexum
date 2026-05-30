"""Importação de faturas (PDF) e extratos (OFX). Extraído de main.py."""
import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..deps import get_db
from ..importacao import importar_arquivo

router = APIRouter()


@router.post("/api/import/fatura")
async def upload_arquivo(
    file: UploadFile = File(...),
    senha: Optional[str] = Form(None),
    conta_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Recebe arquivo (PDF de fatura ou OFX de extrato), parseia e importa.
    Senha só se aplica a PDFs protegidos.
    conta_id usado quando há ambiguidade (múltiplas contas mesmo banco).
    """
    # Resposta padrão pra erros — preenchida e retornada
    def erro_resposta(msg: str, filename: str = ""):
        return {
            "sucesso": False, "ja_importado": False, "precisa_senha": False,
            "ambiguidade_conta": False, "contas_candidatas": [],
            "banco": None, "mes_referencia": None, "fatura_id": None,
            "n_inseridas": 0, "n_duplicadas": 0, "n_categorizadas": 0,
            "valor_total": 0, "erro": msg, "senha_funcionou": None,
            "filename": filename or (file.filename if file else ""),
            "tipo_arquivo": "pdf",
        }

    # Wrapper que captura QUALQUER falha inesperada e devolve JSON em vez de 500.
    try:
        nome = (file.filename or "").lower()
        if not (nome.endswith(".pdf") or nome.endswith(".ofx")):
            return erro_resposta("Arquivo precisa ser PDF (fatura) ou OFX (extrato)", file.filename)

        suffix = ".pdf" if nome.endswith(".pdf") else ".ofx"

        # Salva em temp
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name
        except Exception as e:
            return erro_resposta(f"Falha ao salvar arquivo temporário: {e}", file.filename)

        # Processa
        try:
            try:
                res = importar_arquivo(db, tmp_path, senha=senha, conta_id_override=conta_id)
                db.commit()
            except Exception as e:
                import traceback
                print(f"[ERRO em /api/import/fatura] {e}\n{traceback.format_exc()}", flush=True)
                try:
                    db.rollback()
                except Exception:
                    pass
                return erro_resposta(str(e), file.filename)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass  # Windows às vezes trava arquivo, ignora

        # Sucesso ou resultado de erro tratado pelo importar_arquivo
        return {
            "sucesso": res.sucesso,
            "ja_importado": res.ja_importado,
            "precisa_senha": res.precisa_senha,
            "ambiguidade_conta": res.ambiguidade_conta,
            "contas_candidatas": res.contas_candidatas or [],
            "banco": res.banco,
            "mes_referencia": res.mes_referencia,
            "fatura_id": res.fatura_id,
            "n_inseridas": res.n_transacoes_inseridas,
            "n_duplicadas": res.n_transacoes_duplicadas,
            "n_categorizadas": res.n_transacoes_inseridas and res.n_categorizadas or 0,
            "valor_total": res.valor_total,
            "erro": res.erro,
            "senha_funcionou": res.senha_funcionou,
            "filename": file.filename,
            "tipo_arquivo": "ofx" if nome.endswith(".ofx") else "pdf",
        }
    except Exception as e:
        # Última linha de defesa — se algo escapou de tudo
        import traceback
        print(f"[FATAL em /api/import/fatura] {e}\n{traceback.format_exc()}", flush=True)
        return erro_resposta(f"Erro inesperado: {e}", file.filename if file else "")
