"""Smoke-test harness para el catalogo de primitivas del worker OT.

Ejecuta cada handler en COMMAND_REGISTRY contra un proyecto TIA Portal
real. NO modifica archivos de produccion. Produce un reporte al final.

Uso:
    python tests/smoke_test_worker.py --plc <nombre_plc> --table <nombre_tabla>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKER_SCRIPT = Path(__file__).parent.parent / "main.py"
TIMEOUT_PER_HANDLER = 180.0  # Incrementado para compilar_plc y exportaciones masivas
PYTHON_EXEC = sys.executable

parser = argparse.ArgumentParser()
parser.add_argument("--plc", default="PLC1", help="Nombre del PLC objetivo")
parser.add_argument("--block", default=None, help="Nombre de un bloque existente (se auto-detecta)")
parser.add_argument("--table", default="TagTable_1", help="Nombre de una PlcTagTable existente")
args = parser.parse_args()

PLC_NAME = args.plc
TABLE_NAME = args.table


def _invoke_worker(command: str, args_dict: dict | None = None) -> dict:
    """Invoca el worker por subproceso y devuelve el JSON parseado."""
    payload = {"command": command, "args": args_dict or {}}
    payload_bytes = json.dumps(payload).encode("utf-8")

    proc = subprocess.run(
        [PYTHON_EXEC, "-u", str(WORKER_SCRIPT), "--worker"],
        input=payload_bytes,
        capture_output=True,
        timeout=TIMEOUT_PER_HANDLER,
    )

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    json_response = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                json_response = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return {
        "exit_code": proc.returncode,
        "stdout_raw": stdout,
        "stderr_raw": stderr,
        "json_response": json_response,
    }


def run_test(name: str, command: str, args_dict: dict | None = None,
             validator=None) -> tuple:
    """Ejecuta un test y devuelve (passed, message)."""
    print(f"\n=== TEST: {name} ({command}) ===", flush=True)
    start = time.monotonic()
    try:
        result = _invoke_worker(command, args_dict)
    except subprocess.TimeoutExpired:
        msg = f"TIMEOUT tras {TIMEOUT_PER_HANDLER}s"
        print(msg, flush=True)
        return False, msg
    elapsed = time.monotonic() - start

    jr = result["json_response"]
    if jr is None:
        msg = (
            f"Sin JSON parseable. STDOUT: {result['stdout_raw'][:200]} | "
            f"STDERR: {result['stderr_raw'][:200]}"
        )
        print(msg, flush=True)
        return False, msg

    if not isinstance(jr, dict):
        msg = f"JSON no es dict: {type(jr)}"
        print(msg, flush=True)
        return False, msg

    if "ok" not in jr:
        msg = "JSON sin clave 'ok'"
        print(msg, flush=True)
        return False, msg

    if validator:
        passed, msg = validator(jr, result, elapsed)
        print(f"{msg} [{elapsed:.2f}s]", flush=True)
        return passed, f"{msg} [{elapsed:.2f}s]"

    if jr["ok"] is True:
        msg = f"ok=True, result={type(jr.get('result')).__name__} [{elapsed:.2f}s]"
        print(msg, flush=True)
        return True, msg

    msg = f"ok=False, error={jr.get('error')}"
    print(msg, flush=True)
    return False, msg


def validate_list_plcs(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), list):
        return False, f"result no es list: {type(jr.get('result'))}"
    if not all(isinstance(p, str) for p in jr["result"]):
        return False, "algun elemento de result no es str"
    return True, f"{len(jr['result'])} PLCs detectados: {jr['result']}"


def validate_list_blocks(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), list):
        return False, "result no es list"
    return True, f"{len(jr['result'])} bloques"


def validate_compile_plc(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), bool):
        return False, f"result no es bool: {type(jr.get('result'))}"
    semantica = "TIENE errores" if jr["result"] else "OK (sin errores)"
    return True, f"compile_software()={jr['result']} -> {semantica}"


def validate_export(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), str):
        return False, "result no es str"
    return True, f"Exportado a '{jr['result']}'"


def validate_get_user_constants(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), dict):
        return False, "result no es dict"
    for k, v in jr["result"].items():
        if not isinstance(k, str) or not isinstance(v, str):
            return False, f"clave/valor no son str: {k!r}={v!r}"
    return True, f"{len(jr['result'])} constantes"


def validate_update_value(jr, result, elapsed):
    if jr["ok"] is not True:
        return False, f"ok=False: {jr.get('error')}"
    if not isinstance(jr.get("result"), bool):
        return False, "result no es bool"
    return True, "update_user_constant_value retorno True"


# ---------------------------------------------------------------------------
# Suite de tests
# ---------------------------------------------------------------------------

results = []

# SKIPs de seguridad (mutarian el proyecto o no hay primitivas complementarias)
SKIPS_SEGURIDAD = [
    ("open_project", "SKIPPED (requiere --project-path)"),
    ("save_project", "SKIPPED (podria persistir estado)"),
    ("close_project", "SKIPPED (cerraria el proyecto)"),
    ("import_blocks_scl", "SKIPPED (mutaria el PLC)"),
    ("import_plc_tags_xml", "SKIPPED (mutaria el PLC)"),
    ("import_block", "SKIPPED (mutaria el PLC)"),
    ("import_tag_table", "SKIPPED (mutaria el PLC)"),
    ("update_user_constant_name", "SKIPPED (no hay create_user_constant)"),
    ("delete_user_constant", "SKIPPED (no hay create_user_constant)"),
]
for name, reason in SKIPS_SEGURIDAD:
    results.append((name, None, reason))

# list_plcs
passed, msg = run_test("list_plcs", "list_plcs", {}, validate_list_plcs)
results.append(("list_plcs", passed, msg))

# Auto-detectar PLCs disponibles
jr_plcs = _invoke_worker("list_plcs", {}).get("json_response")
plcs_disponibles = jr_plcs.get("result") if jr_plcs and jr_plcs.get("ok") else []

if plcs_disponibles and PLC_NAME not in plcs_disponibles:
    print(f"\nAVISO: PLC '{PLC_NAME}' no detectado. PLCs disponibles: {plcs_disponibles}")
    print("   Re-ejecuta con --plc <nombre>")
    sys.exit(1)

# list_blocks
passed, msg = run_test(
    "list_blocks", "list_blocks", {"plc_name": PLC_NAME}, validate_list_blocks
)
results.append(("list_blocks", passed, msg))

# Auto-detectar bloque
jr_blocks = _invoke_worker("list_blocks", {"plc_name": PLC_NAME}).get("json_response")
if jr_blocks and jr_blocks.get("ok") and jr_blocks.get("result"):
    BLOCK_NAME = jr_blocks["result"][0]
    print(f"\n-> Bloque auto-detectado en raiz: '{BLOCK_NAME}'", flush=True)
else:
    BLOCK_NAME = args.block
    if not args.block:
        BLOCK_NAME = None
        print("\nAVISO: No se detectaron bloques en la raiz del PLC. "
              "Los tests granulares seran SKIPPED.", flush=True)

# compile_plc
passed, msg = run_test(
    "compile_plc", "compile_plc", {"plc_name": PLC_NAME}, validate_compile_plc
)
results.append(("compile_plc", passed, msg))

# Exportaciones masivas
with tempfile.TemporaryDirectory(prefix="zc_smoke_") as tmpdir:
    for cmd in ["export_blocks_scl", "export_udts_scl", "export_plc_tags_xml"]:
        passed, msg = run_test(
            cmd, cmd, {"plc_name": PLC_NAME, "target_dir": tmpdir}, validate_export
        )
        results.append((cmd, passed, msg))

# export_block (requiere BLOCK_NAME)
if BLOCK_NAME:
    with tempfile.TemporaryDirectory(prefix="zc_smoke_") as tmpdir:
        passed, msg = run_test(
            "export_block", "export_block",
            {"plc_name": PLC_NAME, "block_name": BLOCK_NAME, "target_dir": tmpdir},
            validate_export
        )
        results.append(("export_block", passed, msg))
else:
    results.append(("export_block", None, "SKIPPED (no hay bloque)"))

# export_tag_table
with tempfile.TemporaryDirectory(prefix="zc_smoke_") as tmpdir:
    passed, msg = run_test(
        "export_tag_table", "export_tag_table",
        {"plc_name": PLC_NAME, "table_name": TABLE_NAME, "target_dir": tmpdir},
        validate_export
    )
    results.append(("export_tag_table", passed, msg))

# get_user_constants
passed, msg = run_test(
    "get_user_constants", "get_user_constants",
    {"plc_name": PLC_NAME, "table_name": TABLE_NAME}, validate_get_user_constants
)
results.append(("get_user_constants", passed, msg))

# update_user_constant_value (sobre constante existente + restaurar)
jr_consts = _invoke_worker(
    "get_user_constants", {"plc_name": PLC_NAME, "table_name": TABLE_NAME}
).get("json_response")
if jr_consts and jr_consts.get("ok") and jr_consts.get("result"):
    primera_nombre = list(jr_consts["result"].values())[0]
    primer_valor = int(list(jr_consts["result"].keys())[0])
    passed, msg = run_test(
        "update_user_constant_value", "update_user_constant_value",
        {
            "plc_name": PLC_NAME,
            "table_name": TABLE_NAME,
            "constant_name": primera_nombre,
            "new_value": primer_valor + 1,
        },
        validate_update_value
    )
    results.append(("update_user_constant_value", passed, msg))
    # Restaurar valor original
    _invoke_worker("update_user_constant_value", {
        "plc_name": PLC_NAME,
        "table_name": TABLE_NAME,
        "constant_name": primera_nombre,
        "new_value": primer_valor,
    })
else:
    results.append(("update_user_constant_value", None, "SKIPPED (no hay constantes)"))


# ---------------------------------------------------------------------------
# Reporte final
# ---------------------------------------------------------------------------

print("\n" + "=" * 70)
print("REPORTE FINAL - Smoke-Test Worker OT contra TIA Portal V21")
print("=" * 70)

ejecutados = [(n, p, m) for n, p, m in results if p is not None]
skipped = [(n, p, m) for n, p, m in results if p is None]
pasados = [n for n, p, m in ejecutados if p]
fallados = [(n, m) for n, p, m in ejecutados if not p]

print(f"\nTotales: {len(results)} handlers")
print(f"  OK  Ejecutados y pasados: {len(pasados)}")
print(f"  ERR Ejecutados y fallados: {len(fallados)}")
print(f"  SKP SKIPPED (seguridad / falta handler): {len(skipped)}")

if fallados:
    print("\n--- FALLOS ---")
    for n, m in fallados:
        print(f"  {n}: {m}")

if pasados:
    print("\n--- ÉXITOS ---")
    for n in pasados:
        print(f"  {n}")

print("\nSKIPPED:")
for n, p, m in skipped:
    print(f"  {n}: {m}")

sys.exit(0 if not fallados else 1)