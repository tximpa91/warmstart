import subprocess

import public_safety
import pytest


class ScanSpy:
    def __init__(self):
        self.paths = []

    def scan_file(self, path):
        self.paths.append(path)


def test_tracked_output_is_rejected_without_content_scan(tmp_path, monkeypatch):
    # All test documents are synthetic. This models ignore rules being added too late.
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    exported = tmp_path / "output" / "synthetic-document.docx"
    exported.parent.mkdir()
    exported.write_bytes(b"synthetic test fixture")
    subprocess.run(["git", "-C", str(tmp_path), "add", "output"], check=True)
    (tmp_path / ".gitignore").write_text("/output/\n")
    readme = tmp_path / "README.md"
    readme.write_text("Public application documentation.\n")
    monkeypatch.setattr(public_safety, "ROOT", tmp_path)
    candidates = public_safety.files()
    assert exported in candidates  # Git still reports tracked files despite the ignore.
    scanner = ScanSpy()
    forbidden = public_safety.scan_paths(candidates, scanner, root=tmp_path)
    assert forbidden == ["output/synthetic-document.docx"]
    assert str(exported) not in scanner.paths
    assert str(readme) in scanner.paths


def test_unknown_private_and_symlink_paths_never_reach_content_scanner(tmp_path):
    paths = [
        tmp_path / "unrelated-documents" / "draft.md",
        tmp_path / "docs" / "private" / "draft.md",
        tmp_path / "docs" / "holdout" / "questions.jsonl",
        tmp_path / "docs" / "key.pem",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic fixture.\n")
    link = tmp_path / "docs" / "public-looking.md"
    link.symlink_to(paths[0])
    scanner = ScanSpy()
    forbidden = public_safety.scan_paths([*paths, link], scanner, root=tmp_path)
    assert len(forbidden) == 5
    assert scanner.paths == []


@pytest.mark.parametrize(
    "name",
    [
        "docs/.env",
        "docs/.env.production",
        "docs/.env.example",
        "src/.ENV.staging",
        "src/.dev.vars",
        "src/.dev.vars.local",
        "src/.envrc",
        "docs/.netrc",
        ".codex/auth.json",
        ".claude/.credentials.json",
        "docs/credentials.toml",
        "docs/google-credentials.json",
        "docs/credentials.json.bak",
        "docs/auth.backup",
        "docs/auth.dat",
        "docs/credentials.enc",
        "docs/client_secret.json",
        "docs/oauth-token.json",
        "src/.auth_token",
        "src/service-account.json",
        "docs/credentials",
        "docs/secrets/credentials.json",
        "docs/.secrets/notes.md",
        "docs/credentials/notes.md",
        "docs/auth/notes.md",
        "docs/authentication/notes.md",
        "docs/secrets-prod/notes.md",
        "src/.aws/config",
        "src/.ssh/id_rsa",
        "src/.config/tool/settings.json",
    ],
)
def test_credential_patterns_are_rejected_even_if_force_tracked(tmp_path, monkeypatch, name):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    candidate = tmp_path / name
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("Synthetic credential-store placeholder.\n")
    (tmp_path / ".gitignore").write_text(".env*\n.dev.vars*\nsecrets/\ncredentials/\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--force", "--", name], check=True)
    monkeypatch.setattr(public_safety, "ROOT", tmp_path)
    tracked = public_safety.files()
    assert candidate in tracked
    scanner = ScanSpy()
    assert name in public_safety.scan_paths(tracked, scanner, root=tmp_path)
    assert str(candidate) not in scanner.paths


def test_explicit_public_placeholder_and_normal_source_names_remain_scannable(tmp_path):
    public_names = [
        ".env.example",
        "README.md",
        "src/warmstart/access.py",
        "tests/test_access.py",
        "tests/test_authentication.py",
        "docs/ARCHITECTURE.md",
        "tools/public_safety.py",
    ]
    candidates = []
    for name in public_names:
        candidate = tmp_path / name
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("Public synthetic test content.\n")
        candidates.append(candidate)
    scanner = ScanSpy()
    assert public_safety.scan_paths(candidates, scanner, root=tmp_path) == []
    assert scanner.paths == [str(path) for path in candidates]


def test_tracked_descendant_under_replaced_symlinked_directory_is_not_traversed(
    tmp_path, monkeypatch
):
    root = tmp_path / "application"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    descendant = root / "docs" / "linked-parent" / "fixture.md"
    descendant.parent.mkdir(parents=True)
    descendant.write_text("Original synthetic public fixture.\n")
    subprocess.run(["git", "-C", str(root), "add", "docs"], check=True)
    target = tmp_path / "synthetic-excluded"
    target.mkdir()
    (target / "fixture.md").write_text("Synthetic excluded fixture; must not be scanned.\n")
    descendant.unlink()
    descendant.parent.rmdir()
    descendant.parent.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(public_safety, "ROOT", root)
    candidates = public_safety.files()
    assert descendant in candidates
    scanner = ScanSpy()
    forbidden = public_safety.scan_paths(candidates, scanner, root=root)
    assert "docs/linked-parent/fixture.md" in forbidden
    assert scanner.paths == []


def test_root_escape_and_symlink_root_rejected_without_scanning(tmp_path):
    root = tmp_path / "application"
    root.mkdir()
    outside = tmp_path / "README.md"
    outside.write_text("Synthetic outside-root fixture.\n")
    traversal = root / "docs" / ".." / ".." / "README.md"
    scanner = ScanSpy()
    assert len(public_safety.scan_paths([outside, traversal], scanner, root=root)) == 2
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    (root / "README.md").write_text("Synthetic public fixture.\n")
    assert public_safety.scan_paths([alias / "README.md"], scanner, root=alias) == ["README.md"]
    assert scanner.paths == []
