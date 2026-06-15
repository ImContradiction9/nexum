"""
Cache em memória de leituras quentes (processo único, multi-thread).

O Nexum roda num processo só (uvicorn local), então um dict de módulo com lock
basta. Guarda o RESULTADO de funções caras de LEITURA por um TTL curto, com
invalidação explícita quando a escrita correspondente acontece — assim os
valores nunca ficam errados, só evitam recomputar a mesma coisa várias vezes
na mesma abertura de aba (ex.: a série CDI é carregada por 4 endpoints).

Não persiste: é cache, não fonte de verdade. Some quando o app fecha.

IMPORTANTE: os valores guardados são compartilhados por referência. Só cacheie
dados tratados como SOMENTE-LEITURA pelos chamadores (dicts/listas que ninguém
muta in-place). Quem precisa mutar deve ler da fonte, não do cache.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_store: dict = {}   # chave -> (expira_em_monotonic, valor)


def get_or_set(chave: str, ttl: float, produtor):
    """Devolve o valor de `chave` se ainda válido; senão chama `produtor()`,
    guarda por `ttl` segundos e devolve. `produtor` roda FORA do lock (pode ser
    lento / tocar o banco) — no pior caso dois requests concorrentes produzem o
    mesmo valor, o que é inofensivo."""
    agora = time.monotonic()
    with _lock:
        ent = _store.get(chave)
        if ent is not None and ent[0] > agora:
            return ent[1]
    valor = produtor()
    with _lock:
        _store[chave] = (agora + ttl, valor)
    return valor


def invalidar(*chaves: str) -> None:
    """Remove chaves do cache. Sem argumentos, limpa tudo (usado nos testes)."""
    with _lock:
        if not chaves:
            _store.clear()
            return
        for c in chaves:
            _store.pop(c, None)
