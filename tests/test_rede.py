"""Compartilhamento na rede local (acesso pelo celular): PIN, sessões e toggle."""
from types import SimpleNamespace

import pytest

from app import rede as rede_mod
from app.routers import rede as rede_router


def _req(host="127.0.0.1", cookies=None, path="/"):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        cookies=cookies or {},
        url=SimpleNamespace(path=path),
    )


@pytest.fixture(autouse=True)
def _reset_rede():
    rede_mod.desativar()
    rede_mod.set_porta(8765)
    yield
    rede_mod.desativar()


def test_pin_hash_e_confere():
    h = rede_mod.hash_pin("1234")
    assert h == rede_mod.hash_pin("1234")        # determinístico
    assert h != rede_mod.hash_pin("9999")
    assert rede_mod.pin_confere("1234", h)
    assert not rede_mod.pin_confere("0000", h)
    assert not rede_mod.pin_confere("1234", None)


def test_tokens_e_desativar_limpa():
    t = rede_mod.novo_token()
    assert rede_mod.token_valido(t)
    assert not rede_mod.token_valido("inexistente")
    rede_mod.desativar()
    assert not rede_mod.token_valido(t)          # desligar derruba sessões


def test_eh_local():
    assert rede_mod.eh_local("127.0.0.1")
    assert rede_mod.eh_local("::1")
    assert not rede_mod.eh_local("192.168.0.50")
    assert not rede_mod.eh_local(None)


def test_compartilhar_exige_pin(db):
    # Sem PIN definido, ligar deve falhar.
    with pytest.raises(Exception):
        rede_router.compartilhar(_req(), {"ativar": True}, db=db)
    assert not rede_mod.compartilhando()


def test_compartilhar_com_pin_liga_e_desliga(db):
    # Liga já definindo o PIN no mesmo request.
    out = rede_router.compartilhar(_req(), {"ativar": True, "pin": "4321"}, db=db)
    assert out["compartilhando"] is True
    assert rede_mod.compartilhando()
    st = rede_router.status(_req(), db=db)
    assert st["tem_pin"] is True
    # Desliga.
    out2 = rede_router.compartilhar(_req(), {"ativar": False}, db=db)
    assert out2["compartilhando"] is False
    assert not rede_mod.compartilhando()


def test_config_so_pelo_pc(db):
    # Requisição de outro IP (celular) não pode configurar.
    with pytest.raises(Exception):
        rede_router.status(_req(host="192.168.0.99"), db=db)


def test_bloqueio_forca_bruta():
    ip = "192.168.0.123"
    rede_mod.limpar_falhas(ip)
    assert rede_mod.bloqueado_seg(ip) == 0
    # 4 falhas: ainda liberado, com tentativas restantes diminuindo
    for i in range(4):
        rede_mod.registrar_falha(ip)
    assert rede_mod.bloqueado_seg(ip) == 0
    assert rede_mod.tentativas_restantes(ip) == 1
    # 5ª falha: bloqueia
    rede_mod.registrar_falha(ip)
    assert rede_mod.bloqueado_seg(ip) > 0
    # limpar libera
    rede_mod.limpar_falhas(ip)
    assert rede_mod.bloqueado_seg(ip) == 0


def test_login_celular_valida_pin(db):
    rede_mod.limpar_falhas("10.0.0.5")
    rede_router.compartilhar(_req(), {"ativar": True, "pin": "4321"}, db=db)
    req = _req(host="10.0.0.5")
    # PIN errado: devolve a página de login de novo (status 200, sem cookie).
    resp_err = rede_router.fazer_login(request=req, pin="0000", db=db)
    assert resp_err.status_code == 200
    # PIN certo: redireciona com cookie de sessão.
    resp_ok = rede_router.fazer_login(request=req, pin="4321", db=db)
    assert resp_ok.status_code == 303
    set_cookie = resp_ok.raw_headers
    assert any(b"nexum_rede" in v for _, v in set_cookie)
