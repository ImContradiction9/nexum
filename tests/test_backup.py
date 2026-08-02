"""Testes do backup automático (app/backup.py)."""
import sqlite3

from app import backup


def _criar_db(path):
    """SQLite de verdade: a cópia usa a API de backup do sqlite3."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES ('dados')")
    con.commit()
    con.close()
    return str(path)


def _ler_valor(path):
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT x FROM t").fetchone()[0]
    finally:
        con.close()


def test_backup_cria_copia(tmp_path):
    db = _criar_db(tmp_path / "financeiro.db")
    destino = backup.fazer_backup(db)
    assert destino is not None
    pasta = tmp_path / "backups"
    copias = list(pasta.glob("financeiro-*.db"))
    assert len(copias) == 1
    assert _ler_valor(copias[0]) == "dados"


def test_backup_consistente_com_conexao_aberta(tmp_path):
    # Cenário do backup pré-atualização: o app está RODANDO (conexão aberta).
    db = _criar_db(tmp_path / "financeiro.db")
    con = sqlite3.connect(db)
    try:
        destino = backup.fazer_backup(db, forcar=True)
        assert destino is not None
        assert _ler_valor(destino) == "dados"
    finally:
        con.close()


def test_backup_nao_duplica_no_mesmo_dia(tmp_path):
    db = _criar_db(tmp_path / "financeiro.db")
    assert backup.fazer_backup(db) is not None
    assert backup.fazer_backup(db) is None   # já tem um de hoje
    copias = list((tmp_path / "backups").glob("financeiro-*.db"))
    assert len(copias) == 1


def test_backup_forcar_cria_mesmo_com_um_de_hoje(tmp_path):
    # forcar=True (usado antes de atualizar o app) sempre cria, ignorando
    # o limite de um por dia.
    db = _criar_db(tmp_path / "financeiro.db")
    assert backup.fazer_backup(db) is not None
    assert backup.fazer_backup(db) is None              # dedup diário
    assert backup.fazer_backup(db, forcar=True) is not None  # força mesmo assim
    copias = list((tmp_path / "backups").glob("financeiro-*.db"))
    assert len(copias) == 2


def test_backup_db_inexistente_nao_quebra(tmp_path):
    assert backup.fazer_backup(str(tmp_path / "naoexiste.db")) is None


def test_backup_ignora_db_vazio(tmp_path):
    vazio = tmp_path / "financeiro.db"
    vazio.write_bytes(b"")
    assert backup.fazer_backup(str(vazio)) is None


def test_rotacao_mantem_apenas_n_mais_recentes(tmp_path):
    pasta = tmp_path / "backups"
    pasta.mkdir()
    # Cria 15 backups com nomes ordenáveis por data.
    for i in range(15):
        (pasta / f"financeiro-202601{i:02d}-120000.db").write_bytes(b"x")
    backup._rotacionar(pasta, max_backups=10)
    restantes = sorted(p.name for p in pasta.glob("financeiro-*.db"))
    assert len(restantes) == 10
    # Mantém os mais recentes (datas maiores).
    assert restantes[0] == "financeiro-20260105-120000.db"
    assert restantes[-1] == "financeiro-20260114-120000.db"
