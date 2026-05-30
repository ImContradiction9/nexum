"""
Auto-atualização via GitHub Releases.

Fluxo:
  1. `verificar(versao_atual, repo)` consulta a API pública do GitHub
     (`releases/latest`), compara a tag com a versão atual e devolve o link do
     asset `.exe` (o NexumSetup.exe publicado na release).
  2. `baixar(url, destino)` baixa o instalador.
  3. `escrever_updater_bat(...)` gera um `.bat` que espera o app fechar, roda o
     instalador em silêncio e reabre o Nexum.

Sem dependências externas (urllib puro). Tolerante a offline/erros — `verificar`
nunca levanta exceção (devolve `erro` no dicionário).
"""
import json
import os
import re
import urllib.request
from pathlib import Path

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_UA = "Nexum-Updater"


def _parse_versao(s):
    """'v1.2.3' / '1.2.3' / '1.2' -> (1, 2, 3). Pega só os números."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums) or (0,)


def comparar_versoes(a, b):
    """-1 se a < b, 0 se iguais, 1 se a > b (por componente, com padding)."""
    ta, tb = _parse_versao(a), _parse_versao(b)
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def _http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def verificar(versao_atual, repo):
    """Diz se há versão nova no GitHub. NUNCA levanta exceção.

    Retorna dict com: tem_atualizacao, versao_atual, versao_disponivel, notas,
    url_release, url_download, erro.
    """
    base = {
        "tem_atualizacao": False,
        "versao_atual": versao_atual,
        "versao_disponivel": None,
        "notas": "",
        "url_release": "",
        "url_download": "",
        "erro": None,
    }
    repo = (repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        base["erro"] = "repo_nao_configurado"
        return base
    try:
        data = _http_json(API_LATEST.format(repo=repo))
    except Exception as e:  # offline, 404, rate limit, JSON inválido...
        base["erro"] = f"falha_rede: {e}"
        return base

    tag = data.get("tag_name") or data.get("name") or ""
    base["versao_disponivel"] = tag.lstrip("vV")
    base["notas"] = (data.get("body") or "")[:4000]
    base["url_release"] = data.get("html_url") or ""

    # Acha o asset .exe (o instalador). Prefere nomes com "setup".
    assets = data.get("assets") or []
    exes = [a for a in assets if (a.get("name") or "").lower().endswith(".exe")]
    preferidos = [a for a in exes if "setup" in (a.get("name") or "").lower()]
    escolhido = (preferidos or exes or [None])[0]
    if escolhido:
        base["url_download"] = escolhido.get("browser_download_url") or ""

    base["tem_atualizacao"] = bool(
        base["url_download"]
        and comparar_versoes(base["versao_disponivel"], versao_atual) > 0
    )
    return base


def baixar(url, destino):
    """Baixa `url` para `destino` (Path). Escreve em .part e renomeia no fim."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, destino)
    return destino


def escrever_updater_bat(setup_path, exe_alvo, bat_path):
    """Gera um .bat que espera ~2s (o app fechar), roda o instalador em silêncio
    e reabre o Nexum. Depois se auto-deleta."""
    setup_path, exe_alvo, bat_path = Path(setup_path), Path(exe_alvo), Path(bat_path)
    conteudo = (
        "@echo off\r\n"
        "rem Updater do Nexum (gerado automaticamente)\r\n"
        "ping 127.0.0.1 -n 4 >nul\r\n"  # ~3s (app fecha antes), sem depender de 'timeout'
        f'start "" /wait "{setup_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n'
        f'start "" "{exe_alvo}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'  # auto-remoção do próprio bat
    )
    bat_path.write_text(conteudo, encoding="utf-8")
    return bat_path
