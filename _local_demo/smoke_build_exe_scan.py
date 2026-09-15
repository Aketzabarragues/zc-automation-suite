"""Smoke para build_exe HIDDEN_IMPORTS_AREAS auto-scan."""
import importlib.util
from pathlib import Path

# Cargar build_exe.py como modulo (no es paquete, es script en raiz).
_spec = importlib.util.spec_from_file_location(
    "build_exe", Path(__file__).parent.parent / "build_exe.py",
)
_be = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_be)
HIDDEN_IMPORTS_AREAS = _be.HIDDEN_IMPORTS_AREAS
_scan_areas_for_hiddenimports = _be._scan_areas_for_hiddenimports

print("Total modulos escaneados:", len(HIDDEN_IMPORTS_AREAS))
print("\nPrimeros 10:")
for m in HIDDEN_IMPORTS_AREAS[:10]:
    print(" ", m)
print("\nUltimos 10:")
for m in HIDDEN_IMPORTS_AREAS[-10:]:
    print(" ", m)

# Modulos que DEBEN estar (refs nuevas de A.1, A.3, A.4, A.5).
must_have = [
    "areas.alimentacion.functions.function_SubirExcel",
    "areas.alimentacion.functions.function_DispGenerarPreview",
    "areas.alimentacion.functions.function_DispSincronizarDispositivos",
    "areas.alimentacion.helpers.sync.upload_excel",
    "areas.alimentacion.helpers.sync.disp_generate_preview",
    "areas.alimentacion.helpers.sync.disp_sync",
    "areas.alimentacion.helpers.sync.disp_comment_sync",
    "areas.alimentacion.helpers.sync.diff_constants",
    "areas.alimentacion.frontend.disp_preview_router",
    "areas.alimentacion.frontend.disp_sync_router",
    "areas.alimentacion.frontend.disp_comments_router",
    "areas.alimentacion.frontend.diff_constants_router",
]
print("\nCheck modulos esperados (DEBEN estar):")
all_ok = True
for m in must_have:
    present = m in HIDDEN_IMPORTS_AREAS
    status = "OK " if present else "MISSING"
    if not present:
        all_ok = False
    print(f"  [{status}] {m}")

# Modulos que NO deben estar (refs rotas a archivos borrados).
must_not_have = [
    "areas.alimentacion.application.use_cases.disp_diff_constants",
    "areas.alimentacion.application.use_cases.disp_sync_comentarios",
    "areas.alimentacion.interfaces",
    "areas.alimentacion.interfaces.web",
    "areas.alimentacion.interfaces.mcp",
    "areas.alimentacion.application.disp_slot_map_builder",
    "areas.alimentacion.application.proc_slot_map_builder",
    "areas.alimentacion.domain",
    "areas.alimentacion.domain.models",
]
print("\nCheck refs rotas (NO deben estar):")
for m in must_not_have:
    present = m in HIDDEN_IMPORTS_AREAS
    status = "FAIL" if present else "OK"
    if present:
        all_ok = False
    print(f"  [{status}] {m}")

print("\nResultado:", "TODO OK" if all_ok else "HAY FALLOS")
