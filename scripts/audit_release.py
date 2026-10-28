"""Audit tracked release inputs without reading ignored local credentials or data."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT_FILES = {".gitignore", ".gitattributes", ".dockerignore", ".env.example", ".env.compose.example",
    "README.md", "LICENSE", "CONTRIBUTING.md", "DATA_NOTICE.md", "Dockerfile",
    "compose.yaml", "pyproject.toml", "requirements.lock", "MANIFEST.in", "package.json", "package-lock.json"}
ALLOWED_FOLDERS = {"src", "tests", "migrations", "ontology", "examples", "sources", "docs", "evaluation", "scripts", ".github"}
FORBIDDEN_PARTS = {".venv", ".python-deps", "__pycache__", ".pytest_cache", "data", "node_modules", "dist", "build"}
PATTERNS = [
    ("machine-specific home path", re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/")),
    ("provider credential", re.compile(rb"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


def audit(paths):
    errors = []
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{name}: invalid release path"); continue
        if (FORBIDDEN_PARTS.intersection(path.parts) or name.endswith(".completed.csv")
                or path.suffix in {".sqlite", ".sqlite3", ".db", ".pyc", ".pyo"}
                or (path.name.startswith(".env") and name not in ALLOWED_ROOT_FILES)):
            errors.append(f"{name}: local/private artifact"); continue
        if (len(path.parts) == 1 and name not in ALLOWED_ROOT_FILES) or (len(path.parts) > 1 and path.parts[0] not in ALLOWED_FOLDERS):
            errors.append(f"{name}: unexpected release input"); continue
        local = ROOT / name
        if local.is_symlink():
            errors.append(f"{name}: symlinks are not release inputs"); continue
        content = local.read_bytes()
        for label, pattern in PATTERNS:
            if pattern.search(content): errors.append(f"{name}: {label}")
    return errors


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    names = [name for name in result.stdout.decode().split("\0") if name]
    if not names:
        raise SystemExit("No tracked inputs. Stage the reviewed source files before auditing.")
    errors = audit(names)
    if errors:
        print("\n".join(errors)); return 1
    print(f"Release audit passed: {len(names)} tracked files; no local artifacts or credential patterns.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
