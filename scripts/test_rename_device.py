"""Test directo: rename de una PlcUserConstant en una tabla de dispositivos.

Cambia el nombre de la constante ``ED_001`` en la tabla
``2000_Disp_ED`` a ``ED_DESDE_SCRIPT`` usando
``gateway.update_user_constant_name`` (el comando del worker
para PlcUserConstants; NO ``rename_plc_tag`` que opera sobre
PlcTag y falla con "No se encontr\u00f3 PlcTag con Name=..." en
nuestro caso de uso real).

Uso:
    python scripts/test_rename_device.py ZC_PLC_STD
    python scripts/test_rename_device.py ZC_PLC_STD --dry-run   # solo lee

El script:
  1. Lee el estado actual de la tabla con get_user_constants.
  2. Si --dry-run, para aqu\xed (solo reporta).
  3. Llama gateway.update_user_constant_name(plc_name, table_name,
     current_name, new_name) en una sola transaccion COM.
  4. Verifica el cambio releyendo la tabla.
  5. Imprime instrucciones de rollback para TIA Portal.

El usuario es responsable de hacer el rollback manual en TIA
(revertir el nombre "ED_DESDE_SCRIPT" -> "ED_001" en la tabla
"2000_Disp_ED"). El script NO llama a tia_save_project.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para la consola Windows.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass


# A\u00f1adir el directorio ra\u00edz al path para que `from application...` funcione.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


from infrastructure.gateway import TIAProcessGateway


# Constantes del test (ajustables via CLI en el futuro).
PLC_NAME = "ZC_PLC_STD"
TABLE_NAME = "2000_Disp_ED"
OLD_NAME = "ED_001"
NEW_NAME = "ED_DESDE_SCRIPT"


async def main(plc_name: str, dry_run: bool) -> int:
    print("=" * 70)
    print("=== Test directo: rename de PlcUserConstant en tabla de devices ===")
    print("=" * 70)
    print(f"PLC:               {plc_name}")
    print(f"Table:             {TABLE_NAME}")
    print(f"Constant rename:   {OLD_NAME}  -->  {NEW_NAME}")
    print(f"Mode:              {'DRY-RUN (read only)' if dry_run else 'APPLY'}")
    print()

    gateway = TIAProcessGateway(timeout=120.0)

    # 1. Leer estado actual.
    print(f"[1/3] Leyendo estado actual de '{TABLE_NAME}'...")
    try:
        before = await gateway.get_user_constants(plc_name, TABLE_NAME)
    except RuntimeError as exc:
        print(f"  \u274c Error leyendo la tabla: {exc}")
        return 1
    print(f"  {len(before)} PlcUserConstants en la tabla.")
    if OLD_NAME in before:
        print(f"  \u2713 '{OLD_NAME}' ESTA en la tabla (valor={before[OLD_NAME]}).")
    else:
        print(f"  \u26a0\ufe0f  '{OLD_NAME}' NO esta en la tabla.")
        if NEW_NAME in before:
            print(f"     (pero '{NEW_NAME}' SI esta, con valor={before[NEW_NAME]}).")
            print("     El rename anterior ya estubo aplicado. Aborta para evitar duplicar.")
        else:
            print("     Ni el nombre viejo ni el nuevo estan. Algo no encaja.")
        return 1
    if NEW_NAME in before:
        print(f"  \u26a0\ufe0f  '{NEW_NAME}' YA esta en la tabla (valor={before[NEW_NAME]}).")
        print("     Ya fue renombrado en un test anterior. Aborta para evitar duplicar.")
        return 1

    # 2. Aplicar (o solo reportar en dry-run).
    if dry_run:
        print()
        print(f"[2/3] DRY-RUN: no se aplica el rename.")
        print(f"  Se renombraria '{OLD_NAME}' -> '{NEW_NAME}' en '{TABLE_NAME}'.")
        return 0

    print()
    print(f"[2/3] Renombrando '{OLD_NAME}' -> '{NEW_NAME}'...")
    print("      (esto invoca update_user_constant_name del worker, que")
    print("       hace start_transaction + set_property + end_transaction).")
    try:
        ok = await gateway.update_user_constant_name(
            plc_name=plc_name,
            table_name=TABLE_NAME,
            current_name=OLD_NAME,
            new_name=NEW_NAME,
        )
        print(f"  Resultado del worker: {ok}")
        if not ok:
            return 1
    except RuntimeError as exc:
        print(f"  \u274c RuntimeError: {exc}")
        return 1

    # 3. Verificar.
    print()
    print("[3/3] Verificando cambio (releyendo la tabla)...")
    try:
        after = await gateway.get_user_constants(plc_name, TABLE_NAME)
    except RuntimeError as exc:
        print(f"  \u274c Error releyendo: {exc}")
        return 1
    if NEW_NAME in after:
        print(f"  \u2705 '{NEW_NAME}' AHORA existe (valor={after[NEW_NAME]}).")
        if OLD_NAME in after:
            print(f"  \u26a0\ufe0f  '{OLD_NAME}' SIGUE existiendo (inesperado).")
            return 1
        else:
            print(f"  \u2705 '{OLD_NAME}' ya no esta (correcto).")
    else:
        print(f"  \u274c '{NEW_NAME}' no aparece. El rename fallo silenciosamente.")
        return 1

    print()
    print("=" * 70)
    print(f"  RENAME COMPLETADO en '{TABLE_NAME}': {OLD_NAME} -> {NEW_NAME}")
    print()
    print("  Para revertir en TIA Portal (rollback manual):")
    print(f"    1. Abrir TIA Portal, proyecto del PLC '{plc_name}'.")
    print(f"    2. Navegar a '{TABLE_NAME}' (en la carpeta 2000_Dispositivos).")
    print(f"    3. Localizar la constante '{NEW_NAME}'.")
    print(f"    4. Renombrarla a '{OLD_NAME}'.")
    print("    5. (Opcional) Ctrl+S para guardar el .apxx.")
    print()
    print("  NOTA: el script NO llama a tia_save_project (politica: la app")
    print("        no guarda el .apxx sin confirmacion del operario).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    plc = sys.argv[1] if len(sys.argv) > 1 else PLC_NAME
    dry = "--dry-run" in sys.argv
    raise SystemExit(asyncio.run(main(plc, dry)))
