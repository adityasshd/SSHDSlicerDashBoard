"""Offline safeguards for the read-only MongoDB backup helper."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def backup_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "slicer_mongodb_backup.py"
    spec = spec_from_file_location("slicer_mongodb_backup", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_scope_and_hash(tmp_path):
    backup = backup_module()
    assert backup.DB_NAMES == ("slicing_dashboard", "Slicer_Analytics")
    document = tmp_path / "digest.txt"
    document.write_bytes(b"abc")
    assert backup.digest_file(document) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert backup.within(document, tmp_path)
    assert not backup.within(tmp_path.parent, tmp_path)


def test_connection_config_is_private_and_deleted():
    backup = backup_module()
    from os import path
    fake_uri = "mongodb+srv://user:sensitive-password@invalid.example/"
    with backup.safe_tool_config(fake_uri) as temp_path:
        assert path.exists(temp_path)
        with open(temp_path, encoding="utf-8") as handle:
            assert fake_uri in handle.read()
    assert not path.exists(temp_path)


def test_dry_run_does_not_require_a_connection(monkeypatch, tmp_path, capsys):
    backup = backup_module()
    monkeypatch.setattr("sys.argv", ["backup", "--output", str(tmp_path), "--dry-run"])
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert backup.main() == 0
    output = capsys.readouterr().out
    assert "No database writes or deletions" in output
    assert "slicing_dashboard" in output and "Slicer_Analytics" in output
