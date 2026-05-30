"""Testes do core de auto-atualização (app/atualizacao.py)."""
import app.atualizacao as up


def test_parse_e_comparar_versoes():
    assert up._parse_versao("v1.2.3") == (1, 2, 3)
    assert up._parse_versao("1.2") == (1, 2)
    assert up.comparar_versoes("1.2.0", "1.10.0") < 0   # 2 < 10 (não lexical)
    assert up.comparar_versoes("1.0.0", "1.0.0") == 0
    assert up.comparar_versoes("2.0", "1.9.9") > 0
    assert up.comparar_versoes("1.1", "1.1.0") == 0      # padding


def test_repo_nao_configurado():
    r = up.verificar("1.0.0", "")
    assert r["tem_atualizacao"] is False
    assert r["erro"] == "repo_nao_configurado"
    r2 = up.verificar("1.0.0", "sembarra")
    assert r2["erro"] == "repo_nao_configurado"


def _fake_release(tag, *nomes_assets):
    return {
        "tag_name": tag,
        "body": "Notas da versão",
        "html_url": f"https://github.com/u/nexum/releases/{tag}",
        "assets": [
            {"name": n, "browser_download_url": f"https://dl/{n}"} for n in nomes_assets
        ],
    }


def test_tem_atualizacao_quando_remoto_maior(monkeypatch):
    monkeypatch.setattr(up, "_http_json", lambda *a, **k: _fake_release("v1.1.0", "NexumSetup.exe"))
    r = up.verificar("1.0.0", "u/nexum")
    assert r["tem_atualizacao"] is True
    assert r["versao_disponivel"] == "1.1.0"
    assert r["url_download"] == "https://dl/NexumSetup.exe"
    assert r["notas"] == "Notas da versão"


def test_sem_atualizacao_quando_igual(monkeypatch):
    monkeypatch.setattr(up, "_http_json", lambda *a, **k: _fake_release("v1.0.0", "NexumSetup.exe"))
    r = up.verificar("1.0.0", "u/nexum")
    assert r["tem_atualizacao"] is False


def test_sem_atualizacao_quando_remoto_menor(monkeypatch):
    monkeypatch.setattr(up, "_http_json", lambda *a, **k: _fake_release("v0.9.0", "NexumSetup.exe"))
    r = up.verificar("1.0.0", "u/nexum")
    assert r["tem_atualizacao"] is False


def test_sem_asset_exe_nao_atualiza(monkeypatch):
    # Versão maior, mas sem .exe pra baixar → não oferece update.
    monkeypatch.setattr(up, "_http_json", lambda *a, **k: _fake_release("v2.0.0", "notas.txt"))
    r = up.verificar("1.0.0", "u/nexum")
    assert r["tem_atualizacao"] is False
    assert r["url_download"] == ""


def test_prefere_asset_com_setup(monkeypatch):
    monkeypatch.setattr(up, "_http_json",
                        lambda *a, **k: _fake_release("v1.1.0", "Nexum.exe", "NexumSetup.exe"))
    r = up.verificar("1.0.0", "u/nexum")
    assert r["url_download"] == "https://dl/NexumSetup.exe"


def test_erro_rede_nao_quebra(monkeypatch):
    def boom(*a, **k):
        raise OSError("sem internet")
    monkeypatch.setattr(up, "_http_json", boom)
    r = up.verificar("1.0.0", "u/nexum")
    assert r["tem_atualizacao"] is False
    assert r["erro"].startswith("falha_rede")


def test_baixar_grava_arquivo(tmp_path):
    origem = tmp_path / "fonte.bin"
    origem.write_bytes(b"conteudo do instalador" * 1000)
    destino = tmp_path / "sub" / "NexumSetup.exe"
    up.baixar(origem.as_uri(), destino)   # file:// funciona no urllib
    assert destino.exists()
    assert destino.read_bytes() == origem.read_bytes()
    assert not destino.with_suffix(".exe.part").exists()  # .part foi renomeado


def test_escrever_updater_bat(tmp_path):
    setup = tmp_path / "NexumSetup.exe"
    exe = tmp_path / "Nexum.exe"
    bat = tmp_path / "update.bat"
    up.escrever_updater_bat(setup, exe, bat)
    txt = bat.read_text(encoding="utf-8")
    assert "/VERYSILENT" in txt
    assert str(setup) in txt
    assert str(exe) in txt
    assert "del " in txt  # auto-remoção
