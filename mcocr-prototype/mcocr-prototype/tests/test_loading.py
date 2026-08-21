from pathlib import Path


def test_project_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "main.py").is_file()
    assert (root / "config.json").is_file()
    assert (root / "profiles/java_default_ascii.json").is_file()
