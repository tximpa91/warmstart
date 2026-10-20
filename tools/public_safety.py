"""Scan the publishable Git tree for credentials and prohibited private file types."""

import re
import subprocess
from pathlib import Path

from agent_workflow import ROOT
from detect_secrets import SecretsCollection
from detect_secrets.settings import transient_settings

# Publication is opt-in by application root, including paths already tracked in Git.
# Review additions here when introducing a new source root; do not scan unknown documents.
APPLICATION_ROOTS = frozenset(
    {
        ".claude",
        ".codex",
        ".cursor",
        ".env.example",
        ".github",
        ".gitignore",
        ".python-version",
        "AGENTS.md",
        "CLAUDE.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "agent-workflow",
        "data",
        "docs",
        "migrations",
        "package-lock.json",
        "package.json",
        "public",
        "pylock.toml",
        "pyproject.toml",
        "scripts",
        "src",
        "tests",
        "tools",
        "uv.lock",
        "wrangler.demo.toml",
        "wrangler.smoke.toml",
        "wrangler.toml",
    }
)
PRIVATE_PARTS = frozenset(
    {
        "private",
        "holdout",
        "artifacts",
        ".venv",
        ".venv-workers",
        "output",
        "secrets",
        ".secrets",
        "credentials",
        ".credentials",
        "credential-store",
        "credential_store",
        "auth",
        ".auth",
        "authentication",
        ".authentication",
        ".aws",
        ".azure",
        ".ssh",
        ".gnupg",
        ".kube",
        ".docker",
        ".config",
        ".direnv",
        ".git",
        "node_modules",
        "__pycache__",
    }
)
CREDENTIAL_FILES = frozenset(
    {
        ".netrc",
        "_netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        ".envrc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
        "kubeconfig",
    }
)
PRIVATE_SUFFIXES = frozenset(
    {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".log",
        ".keychain",
        ".keystore",
        ".jks",
    }
)
PUBLIC_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".mjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".css",
        ".html",
        ".md",
    }
)
STORE_WORDS = re.compile(
    r"(?:^|[._-])(?:credentials?|secrets?|tokens?|auth|authentication|oauth|"
    r"service[._-]?account|client[._-]?secret)(?:$|[._-])"
)


def files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [ROOT / name for name in sorted(set(result.stdout.decode().split("\0")) - {""})]


def private_path(relative: Path) -> bool:
    """Classify path names only; the sole environment-file exception is a root example."""
    parts = tuple(part.casefold() for part in relative.parts)
    if any(part in PRIVATE_PARTS for part in parts):
        return True
    if any(STORE_WORDS.search(part) is not None for part in parts[:-1]):
        return True
    for part in parts:
        if part == ".env" or part.startswith(".env."):
            if relative != Path(".env.example"):
                return True
        if part == ".dev.vars" or part.startswith(".dev.vars."):
            return True
    name = relative.name.casefold()
    suffix = relative.suffix.casefold()
    return (
        name in CREDENTIAL_FILES
        or suffix in PRIVATE_SUFFIXES
        # Reject credential stores regardless of serialization/backup extension while
        # retaining ordinary source files such as tests/test_authentication.py.
        or (suffix not in PUBLIC_SOURCE_SUFFIXES and STORE_WORDS.search(name) is not None)
    )


def no_symlink_ancestors(path: Path, root: Path) -> bool:
    """Check components from the trusted root outward, never traversing a known link."""
    current = root
    if current.is_symlink():
        return False
    for component in path.relative_to(root).parts:
        current = current / component
        if current.is_symlink():
            return False
    return True


def scan_paths(paths: list[Path], secrets: SecretsCollection, root: Path = ROOT) -> list[str]:
    """Reject private/unknown/linked paths before any content scan, even if tracked.

    The caller must scan and publish a frozen snapshot: path checks cannot prevent a
    different process from swapping a directory after validation (a filesystem race).
    """
    root = root.absolute()
    forbidden = []
    for path in paths:
        candidate = path if path.is_absolute() else root / path
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            forbidden.append(str(path))
            continue
        if (
            not relative.parts
            or ".." in relative.parts
            or relative.parts[0] not in APPLICATION_ROOTS
            or private_path(relative)
            or not no_symlink_ancestors(candidate, root)
        ):
            forbidden.append(str(relative))
            continue
        if candidate.is_file():
            secrets.scan_file(str(candidate))
    return forbidden


if __name__ == "__main__":
    secrets = SecretsCollection()
    # Hashes, UUIDs, golden-case IDs and action SHAs are intentional public metadata.
    plugins = [
        {"name": "PrivateKeyDetector"},
        {"name": "AWSKeyDetector"},
        {"name": "GitHubTokenDetector"},
        {"name": "JwtTokenDetector"},
        {"name": "OpenAIDetector"},
        {"name": "StripeDetector"},
    ]
    with transient_settings({"plugins_used": plugins}):
        forbidden = scan_paths(files(), secrets)
    findings = [
        (str(path), [item.type for item in values]) for path, values in secrets.data.items()
    ]
    if forbidden or findings:
        print({"forbidden_paths": forbidden, "credential_findings": findings})
        raise SystemExit(1)
    print("Publishable working tree passed credential/path scans; no zero-risk claim.")
