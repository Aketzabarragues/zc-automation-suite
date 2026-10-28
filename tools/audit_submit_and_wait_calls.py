"""Audita las llamadas a ``submit_and_wait`` del repo.

Motivo: ``MagicMock(spec=SyncTIAClient)`` no valida la firma de la llamada,
asi que un kwarg erroneo o un ``timeout`` ausente pasan los tests y solo
reventan contra TIA real. Esta sonda recorre el codigo con ``ast`` y
lista, para cada llamada, el comando y los kwargs.

Uso:
    python tools/audit_submit_and_wait_calls.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".build_cache", "dist", "build", "node_modules"}


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def main() -> int:
    findings: list[str] = []
    sin_timeout: list[str] = []
    kwargs_malos: list[str] = []
    total = 0

    for path in _iter_py_files():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(rel))
        except (OSError, SyntaxError) as exc:
            findings.append(f"{rel}: no parseable ({exc})")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) != "submit_and_wait":
                continue

            cmd = "<expr>"
            if node.args and isinstance(node.args[0], ast.Constant):
                cmd = str(node.args[0].value)

            total += 1
            kw_names = [kw.arg for kw in node.keywords if kw.arg]
            line = f"{rel}:{node.lineno}"

            if "timeout_s" in kw_names:
                kwargs_malos.append(
                    f"{line}  submit_and_wait({cmd!r}) usa timeout_s= "
                    "(la firma real es timeout)"
                )
            elif "timeout" not in kw_names:
                sin_timeout.append(f"{line}  submit_and_wait({cmd!r}) sin timeout")

    print(f"=== llamadas a submit_and_wait detectadas: {total} ===")
    print()
    print("=== kwargs invalidos (timeout_s=) ===")
    print("\n".join(kwargs_malos) if kwargs_malos else "(ninguno)")
    print()
    print("=== llamadas sin timeout (default 30.0 s) ===")
    print("\n".join(sin_timeout) if sin_timeout else "(ninguna)")
    print()
    if findings:
        print("=== ficheros no parseables ===")
        print("\n".join(findings))
        print()

    return 1 if kwargs_malos or findings else 0


if __name__ == "__main__":
    sys.exit(main())
