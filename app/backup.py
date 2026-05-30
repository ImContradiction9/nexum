"""
Backup automático do banco de dados.

A cada inicialização do app, faz uma cópia de `financeiro.db` para
`data/backups/` (no máximo uma por dia) e mantém só as N mais recentes.
É feito ANTES das migrações — se uma migração corromper algo, a cópia
pré-migração continua disponível.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

MAX_BACKUPS = 10
_PREFIXO = "financeiro-"
_SUFIXO = ".db"


def fazer_backup(db_path: str, max_backups: int = MAX_BACKUPS) -> str | None:
    """
    Copia o banco para data/backups/financeiro-AAAAMMDD-HHMMSS.db.
    No máximo um backup por dia (se já existe um de hoje, não duplica).
    Mantém apenas os `max_backups` mais recentes. Tolerante a falha —
    nunca derruba a inicialização do app.

    Retorna o caminho do backup criado, ou None se não criou.
    """
    try:
        origem = Path(db_path)
        if not origem.exists() or origem.stat().st_size == 0:
            return None  # nada pra copiar ainda (primeira execução)

        pasta = origem.parent / "backups"
        pasta.mkdir(parents=True, exist_ok=True)

        hoje = datetime.now().strftime("%Y%m%d")
        # Já existe backup de hoje? Então não duplica.
        if any(p.name.startswith(f"{_PREFIXO}{hoje}") for p in pasta.glob(f"{_PREFIXO}*{_SUFIXO}")):
            _rotacionar(pasta, max_backups)
            return None

        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = pasta / f"{_PREFIXO}{carimbo}{_SUFIXO}"
        shutil.copy2(origem, destino)
        _rotacionar(pasta, max_backups)
        return str(destino)
    except Exception:
        # Backup nunca pode impedir o app de subir.
        return None


def _rotacionar(pasta: Path, max_backups: int):
    """Mantém só os `max_backups` arquivos mais recentes na pasta de backups."""
    backups = sorted(
        pasta.glob(f"{_PREFIXO}*{_SUFIXO}"),
        key=lambda p: p.name,
        reverse=True,
    )
    for antigo in backups[max_backups:]:
        try:
            antigo.unlink()
        except Exception:
            pass
