"""Testes do backup automático (app/backup.py)."""
from app import backup


def _criar_db(path, conteudo=b"dados"):
    path.write_bytes(conteudo)
    return str(path)


def test_backup_cria_copia(tmp_path):
    db = _criar_db(tmp_path / "financeiro.db")
    destino = backup.fazer_backup(db)
    assert destino is not None
    pasta = tmp_path / "backups"
    copias = list(pasta.glob("financeiro-*.db"))
    assert len(copias) == 1
    assert copias[0].read_bytes() == b"dados"


def test_backup_nao_duplica_no_mesmo_dia(tmp_path):
    db = _criar_db(tmp_path / "financeiro.db")
    assert backup.fazer_backup(db) is not None
    assert backup.fazer_backup(db) is None   # já tem um de hoje
    copias = list((tmp_path / "backups").glob("financeiro-*.db"))
    assert len(copias) == 1


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
