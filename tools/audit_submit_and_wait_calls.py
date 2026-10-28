"""Audita las llamadas a ``submit_and_wait`` del repo.

Motivo: ``MagicMock(spec=SyncTIAClient)`` no valida la firma de la
llamada, asi que un kwarg erroneo o un ``timeout`` ausente pasan los
tests y solo revientan contra TIA real. Esta sonda recorre el codigo
con ``ast`` y lista, para cada llamada, el comando y los kwargs.

Cubre tres formas de llamar:

  1. Llamada directa: ``client.submit_and_wait(cmd, args, timeout=T)``.
  2. Empaquetada: ``partial(client.submit_and_wait, cmd, args, T)``.
     El timeout posicional es fragil: depende del orden de los
     parametros de la firma. Se reporta aparte.
  3. Dentro de una lambda.

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


def _is_submit_and_wait(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute) and node.attr == "submit_and_wait"
    ) or (
        isinstance(node, ast.Name) and node.id == "submit_and_wait"
    )


def _const(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant):
        return str(node.value)
    return "<expr>"


def main() -> int:
    findings: list[str] = []
    directos: list[str] = []
    sin_timeout: list[str] = []
    kwargs_malos: list[str] = []
    indirectas: list[str] = []
    total = 0

    for path in _iter_py_files():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(rel))
        except (OSError, SyntaxError) as exc:
            findings.append(f"{rel}: no parseable ({exc})")
            continue

        for node in ast.walk(tree):
            # --- 1. llamada directa -------------------------------------
            if isinstance(node, ast.Call) and _is_submit_and_wait(node.func):
                total += 1
                cmd = _const(node.args[0]) if node.args else "<expr>"
                kw_names = [kw.arg for kw in node.keywords if kw.arg]
                line = f"{rel}:{node.lineno}"
                if "timeout_s" in kw_names:
                    kwargs_malos.append(
                        f"{line}  submit_and_wait({cmd!r}) usa timeout_s= "
                        "(la firma real es timeout)"
                    )
                elif "timeout" not in kw_names:
                    sin_timeout.append(
                        f"{line}  submit_and_wait({cmd!r}) sin timeout "
                        "(default 30 s)"
                    )
                else:
                    directos.append(f"{line}  {cmd}")

            # --- 2. empaquetada con partial ----------------------------
            if (
                isinstance(node, ast.Call)
                and _call_name(node) == "partial"
                and node.args
                and _is_submit_and_wait(node.args[0])
            ):
                total += 1
                cmd = _const(node.args[1]) if len(node.args) > 1 else "<expr>"
                kw_names = [kw.arg for kw in node.keywords if kw.arg]
                line = f"{rel}:{node.lineno}"
                if "timeout_s" in kw_names:
                    kwargs_malos.append(
                        f"{line}  partial(submit_and_wait, {cmd!r}) usa timeout_s= "
                        "(la firma real es timeout)"
                    )
                elif "timeout" not in kw_names:
                    sin_timeout.append(
                        f"{line}  partial(submit_and_wait, {cmd!r}) sin timeout "
                        "(default 30 s)"
                    )
                else:
                    indirectas.append(
                        f"{line}  {cmd}  (timeout posicional: frágil)"
                    )

            # --- 3. lambda ----------------------------------------------
            if isinstance(node, ast.Lambda):
                for sub in ast.walk(node.body):
                    if (
                        isinstance(sub, ast.Call)
                        and _is_submit_and_wait(sub.func)
                    ):
                        total += 1
                        kw_names = [kw.arg for kw in sub.keywords if kw.arg]
                        line = f"{rel}:{node.lineno}"
                        if "timeout_s" in kw_names:
                            kwargs_malos.append(
                                f"{line}  lambda con submit_and_wait usa timeout_s="
                            )
                        elif "timeout" not in kw_names:
                            sin_timeout.append(
                                f"{line}  lambda con submit_and_wait sin timeout"
                            )
                        else:
                            indirectas.append(f"{line}  (lambda)")

    print(f"=== llamadas a submit_and_wait detectadas: {total} ===")
    print()
    print("=== kwargs invalidos (timeout_s=) ===")
    print("\n".join(kwargs_malos) if kwargs_malos else "(ninguno)")
    print()
    print("=== llamadas sin timeout (default 30 s) ===")
    print("\n".join(sin_timeout) if sin_timeout else "(ninguna)")
    print()
    print("=== llamadas indirectas (partial / lambda) ===")
    print("\n".join(indirectas) if indirectas else "(ninguna)")
    print()
    if findings:
        print("=== ficheros no parseables ===")
        print("\n".join(findings))
        print()

    return 1 if kwargs_malos or findings or indirectas else 0


if __name__ == "__main__":
    sys.exit(main())
