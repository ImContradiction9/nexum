"""Compartilhamento na rede local (acesso pelo celular).

O app roda no PC (banco SQLite fica lá). Quando o usuário liga "Compartilhar na
rede", outros aparelhos no MESMO Wi-Fi podem abrir a interface pelo IP do PC,
protegidos por um PIN. Acesso de fora (internet) NÃO é coberto — só rede local.

Estado em memória (reseta a cada inicialização, por segurança: o app sempre
começa privado). O PIN, esse sim, persiste no banco (Configuracao).
"""
import hashlib
import secrets
import socket
import time

# Estado vivo do processo. compartilhando=False → app se comporta como antes
# (só localhost; fecha junto com a janela). tokens = sessões de celular válidas.
_estado = {
    "compartilhando": False,
    "tokens": set(),
    "porta": None,   # porta real escolhida pelo launcher
}

_SALT = "nexum-rede-v1:"


# --- compartilhamento ---
def compartilhando() -> bool:
    return _estado["compartilhando"]


def ativar() -> None:
    _estado["compartilhando"] = True


def desativar() -> None:
    _estado["compartilhando"] = False
    _estado["tokens"].clear()   # derruba sessões de celular ao desligar


def set_porta(porta: int) -> None:
    _estado["porta"] = porta


def porta() -> int | None:
    return _estado["porta"]


# --- sessões (cookie do celular) ---
def novo_token() -> str:
    t = secrets.token_urlsafe(24)
    _estado["tokens"].add(t)
    return t


def token_valido(token: str | None) -> bool:
    return bool(token) and token in _estado["tokens"]


# --- proteção contra força-bruta no PIN ---
_MAX_FALHAS = 5          # tentativas erradas antes de bloquear
_BLOQUEIO_SEG = 300      # 5 minutos de bloqueio
_falhas = {}             # ip -> {"n": int, "ate": monotonic}


def bloqueado_seg(ip: str | None) -> int:
    """Segundos restantes de bloqueio para esse IP (0 = liberado)."""
    info = _falhas.get(ip)
    if not info:
        return 0
    rest = info.get("ate", 0) - time.monotonic()
    return int(rest) + 1 if rest > 0 else 0


def registrar_falha(ip: str | None) -> None:
    info = _falhas.setdefault(ip, {"n": 0, "ate": 0})
    info["n"] += 1
    if info["n"] >= _MAX_FALHAS:
        info["ate"] = time.monotonic() + _BLOQUEIO_SEG
        info["n"] = 0   # recomeça a contagem após o bloqueio


def tentativas_restantes(ip: str | None) -> int:
    info = _falhas.get(ip)
    return _MAX_FALHAS - (info["n"] if info else 0)


def limpar_falhas(ip: str | None) -> None:
    _falhas.pop(ip, None)


# --- PIN ---
def hash_pin(pin: str) -> str:
    return hashlib.sha256((_SALT + (pin or "")).encode("utf-8")).hexdigest()


def pin_confere(pin: str, hash_guardado: str | None) -> bool:
    if not hash_guardado or not pin:
        return False
    return secrets.compare_digest(hash_pin(pin), hash_guardado)


# --- rede ---
def ip_local() -> str | None:
    """Descobre o IP do PC na rede local (LAN). Não envia nada — só usa um
    socket UDP pra ver qual interface o SO usaria pra sair, e lê o IP dela."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return None


def url_local() -> str | None:
    ip = ip_local()
    p = porta()
    if ip and p:
        return f"http://{ip}:{p}"
    return None


def eh_local(host: str | None) -> bool:
    """True se a requisição veio da própria máquina (não precisa de PIN)."""
    return host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")
