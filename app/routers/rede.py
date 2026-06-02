"""Compartilhamento na rede local: ligar/desligar, PIN e login do celular.

As rotas /api/rede/* que mexem na configuração só podem ser chamadas do próprio
PC (localhost) — o middleware garante isso. A página de login (/rede/entrar) e o
POST /rede/login são acessíveis pelo celular pra digitar o PIN.
"""
import subprocess
import sys

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from ..deps import get_db
from ..database import Configuracao
from .. import rede as rede_mod

router = APIRouter()

CHAVE_PIN = "rede_pin_hash"


def _so_local(request: Request):
    host = request.client.host if request.client else None
    if not rede_mod.eh_local(host):
        raise HTTPException(status_code=403, detail="Só pode ser configurado no próprio PC.")


def _get_cfg(db, chave):
    return db.query(Configuracao).filter(Configuracao.chave == chave).first()


def _set_cfg(db, chave, valor):
    cfg = _get_cfg(db, chave)
    if cfg is None:
        cfg = Configuracao(chave=chave, valor=valor)
        db.add(cfg)
    else:
        cfg.valor = valor
    db.commit()


@router.get("/api/rede/status")
def status(request: Request, db: Session = Depends(get_db)):
    _so_local(request)
    tem_pin = _get_cfg(db, CHAVE_PIN) is not None
    return {
        "compartilhando": rede_mod.compartilhando(),
        "tem_pin": tem_pin,
        "ip": rede_mod.ip_local(),
        "porta": rede_mod.porta(),
        "url": rede_mod.url_local(),
    }


@router.post("/api/rede/pin")
def definir_pin(request: Request, dados: dict, db: Session = Depends(get_db)):
    _so_local(request)
    pin = (dados.get("pin") or "").strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="O PIN precisa ter pelo menos 4 dígitos.")
    _set_cfg(db, CHAVE_PIN, rede_mod.hash_pin(pin))
    return {"ok": True, "tem_pin": True}


@router.post("/api/rede/compartilhar")
def compartilhar(request: Request, dados: dict, db: Session = Depends(get_db)):
    _so_local(request)
    ativar = bool(dados.get("ativar"))
    if not ativar:
        rede_mod.desativar()
        return {"ok": True, "compartilhando": False}

    # Pra ligar, precisa de PIN definido (pode vir junto no mesmo request).
    pin = (dados.get("pin") or "").strip()
    if pin:
        if len(pin) < 4:
            raise HTTPException(status_code=400, detail="O PIN precisa ter pelo menos 4 dígitos.")
        _set_cfg(db, CHAVE_PIN, rede_mod.hash_pin(pin))
    if _get_cfg(db, CHAVE_PIN) is None:
        raise HTTPException(status_code=400, detail="Defina um PIN antes de compartilhar.")

    rede_mod.ativar()
    return {
        "ok": True,
        "compartilhando": True,
        "url": rede_mod.url_local(),
        "ip": rede_mod.ip_local(),
        "porta": rede_mod.porta(),
    }


@router.post("/api/rede/firewall")
def liberar_firewall(request: Request):
    """Libera o Nexum no Firewall do Windows para acesso pela rede local.
    Pede elevação (UAC) uma vez. Apaga regras antigas do programa (inclusive as
    de BLOQUEIO que o Windows cria quando o alerta é negado — bloqueio vence
    permissão) e cria uma permissão de entrada POR PROGRAMA em TODOS os perfis
    (Privado e Público — redes domésticas costumam vir como Pública). Best-effort:
    se o usuário recusar o UAC, devolve ok=False e a UI mostra instruções."""
    _so_local(request)
    p = rede_mod.porta()
    exe = sys.executable  # frozen → caminho do Nexum.exe
    nome = "Nexum (rede local)"
    # Chaqueia vários netsh num cmd /c elevado (um único UAC).
    partes = [
        f'netsh advfirewall firewall delete rule name=all program="{exe}"',
        f'netsh advfirewall firewall delete rule name="{nome}"',
        f'netsh advfirewall firewall add rule name="{nome}" dir=in '
        f'action=allow program="{exe}" enable=yes profile=any',
    ]
    if p:
        partes.append(
            f'netsh advfirewall firewall add rule name="{nome} porta" dir=in '
            f'action=allow protocol=TCP localport={p} profile=any'
        )
    cmds = " & ".join(partes)
    ps = f"Start-Process -Verb RunAs -WindowStyle Hidden -FilePath cmd -ArgumentList '/c','{cmds}'"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=40,
        )
        ok = r.returncode == 0
        return {"ok": ok, "detalhe": (r.stderr or r.stdout or "").strip()[:300]}
    except Exception as e:
        return {"ok": False, "detalhe": str(e)[:300]}


# ===========================================================
# Login do celular (acessível por aparelhos da rede)
# ===========================================================
def _pagina_login(erro: str = "") -> HTMLResponse:
    aviso = f'<p class="erro">{erro}</p>' if erro else ""
    html = f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexum — entrar</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#09090b; color:#e4e4e7; font-family:system-ui,-apple-system,sans-serif; }}
  .card {{ width:min(92vw,360px); background:#18181b; border:1px solid #27272a; border-radius:16px;
           padding:32px 24px; box-shadow:0 10px 40px rgba(0,0,0,.4); }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  p.sub {{ margin:0 0 20px; color:#a1a1aa; font-size:14px; }}
  input {{ width:100%; box-sizing:border-box; font-size:24px; text-align:center; letter-spacing:8px;
           padding:14px; border-radius:10px; border:1px solid #3f3f46; background:#09090b; color:#fff; }}
  button {{ width:100%; margin-top:16px; padding:14px; font-size:16px; font-weight:600; border:0;
            border-radius:10px; background:#10b981; color:#052e22; cursor:pointer; }}
  .erro {{ color:#f87171; font-size:14px; margin:0 0 12px; }}
</style></head><body>
  <form class="card" method="post" action="/rede/login">
    <h1>Nexum</h1>
    <p class="sub">Digite o PIN para acessar suas finanças neste aparelho.</p>
    {aviso}
    <input name="pin" type="password" inputmode="numeric" autocomplete="off"
           placeholder="• • • •" autofocus>
    <button type="submit">Entrar</button>
  </form>
</body></html>"""
    return HTMLResponse(html)


@router.get("/rede/entrar", response_class=HTMLResponse)
def pagina_entrar():
    return _pagina_login()


@router.post("/rede/login")
def fazer_login(pin: str = Form(""), db: Session = Depends(get_db)):
    if not rede_mod.compartilhando():
        return HTMLResponse("<h2>Compartilhamento desligado no PC.</h2>", status_code=403)
    cfg = _get_cfg(db, CHAVE_PIN)
    if not rede_mod.pin_confere(pin.strip(), cfg.valor if cfg else None):
        return _pagina_login("PIN incorreto. Tente de novo.")
    token = rede_mod.novo_token()
    resp = RedirectResponse(url="/", status_code=303)
    # Cookie de sessão (some ao fechar o navegador do celular).
    resp.set_cookie("nexum_rede", token, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    return resp
