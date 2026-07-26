"""提交前安全扫描：禁止把密钥、密码和真实连接信息带进仓库。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHECK_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".sh", ".bat"}
EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
SENSITIVE_PATTERNS = (
    (re.compile(r"""(?:api[_-]?key|token)\s*=\s*["'](?!your-|test-|change-me|\$\{)[^"']+["']""", re.I), "疑似 API 凭据"),
    (re.compile(r"""password\s*=\s*["'](?!your-|test-|change-me|\$\{)[^"']+["']""", re.I), "疑似明文密码"),
    (
        re.compile(
            r"""(?:host|base_url)\s*=\s*["'](?!(?:127\.0\.0\.1|localhost))(?:(?:\d{1,3}\.){3}\d{1,3})["']""",
            re.I,
        ),
        "疑似真实连接地址",
    ),
)


def scan_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    findings: list[str] = []
    for pattern, label in SENSITIVE_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: {label}")
    return findings


def scan_repository(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in CHECK_EXTENSIONS:
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        findings.extend(scan_file(path))
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = scan_repository(root)
    if findings:
        print("[FAIL] security findings:")
        print("\n".join(findings))
        return 1
    print(f"[OK] security scan passed: {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
