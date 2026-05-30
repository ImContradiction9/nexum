"""Testes do router de auto-atualização (resolução do repo + guardas)."""
import pytest
from fastapi import HTTPException

from app.routers.atualizacao import status, instalar, _repo, CONFIG_REPO, REPO_PADRAO
from app.database import Configuracao


def test_repo_padrao_embutido(db):
    # Sem env nem config, cai no repositório padrão (funciona "de fábrica").
    assert _repo(db) == REPO_PADRAO
    assert "/" in REPO_PADRAO


def test_repo_da_config_sobrepoe_padrao(db):
    db.add(Configuracao(chave=CONFIG_REPO, valor="micael/nexum"))
    db.commit()
    assert _repo(db) == "micael/nexum"


def test_repo_env_tem_prioridade(db, monkeypatch):
    db.add(Configuracao(chave=CONFIG_REPO, valor="da/config"))
    db.commit()
    monkeypatch.setenv("NEXUM_UPDATE_REPO", "do/env")
    assert _repo(db) == "do/env"


def test_status_sem_repo_nao_quebra(db, monkeypatch):
    # Anula o padrão e a config → sem repo, status não bate na rede.
    monkeypatch.setattr("app.routers.atualizacao.REPO_PADRAO", "")
    r = status(db)
    assert r["tem_atualizacao"] is False
    assert r["erro"] == "repo_nao_configurado"
    assert r["instalado"] is False   # rodando em dev (não-frozen)


def test_instalar_fora_do_exe_recusa(db):
    # Em dev (não-frozen), auto-instalação é bloqueada.
    with pytest.raises(HTTPException) as exc:
        instalar(db)
    assert exc.value.status_code == 400
