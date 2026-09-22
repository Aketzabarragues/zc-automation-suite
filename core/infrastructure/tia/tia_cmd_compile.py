"""core.infrastructure.tia.tia_cmd_compile - comandos de compilación del PLC.

Dos comandos para compilar software PLC en TIA Portal:

  - compile_plc:    compila TODO el software del PLC.
  - compile_blocks: compila SOLO una lista explicita de bloques (mas rapido).

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Restricciones arquitectónicas:
  - Solo mutacion: compila bloques en el PLC. NO exporta, NO importa.
  - El retorno es siempre primitivo (``bool``/``dict`` con shape estable).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import (
    _find_plc,
    _get_active_project,
    _safe_get_block_name,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_compile_plc(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila el software del PLC y retorna el booleano nativo de Siemens.

    Returns:
        ``{"had_errors": bool}``:
          - True  -> compilacion TIENE errores.
          - False -> compilacion NO tiene errores (exito).
    """
    plc_name: str = args.get("plc_name", "")
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    had_errors = bool(target_plc.compile_software())
    return {"had_errors": had_errors}


def _h_compile_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila una lista explicita de bloques del PLC (no todo el software).

    Mas rapido que compile_plc cuando solo se han tocado unos DBs
    concretos. Por bloque:
      - is_consistent()=True  -> se SALTA.
      - is_consistent()=False -> se COMPILA.
      - bloque no encontrado  -> se SALTA (no falla el handler entero).

    Returns:
        ``{
            "compiled":         [{"name", "had_errors", "was_inconsistent"}],
            "skipped_unchanged": [name, ...],
            "not_found":        [name, ...],
            "errors":           [{"name", "error"}],
        }``
    """
    plc_name: str = args.get("plc_name", "")
    block_names = args.get("block_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_names:
        raise ValueError(
            "Se requiere 'block_names' (lista no vacia de bloques a compilar). "
            "Si quieres compilar todo el PLC, usa el comando 'compile_plc'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Indexar bloques del PLC por nombre para busqueda O(1).
    all_blocks = target_plc.get_program_blocks()
    by_name: dict = {}
    for b in all_blocks:
        name = _safe_get_block_name(b)
        if name is not None:
            by_name.setdefault(name, b)  # primero que aparece gana

    compiled: list[dict] = []
    skipped_unchanged: list[str] = []
    not_found: list[str] = []
    errors: list[dict] = []

    for name in block_names:
        block = by_name.get(name)
        if block is None:
            not_found.append(name)
            continue
        # is_consistent(): True si ya esta compilado y sin cambios.
        try:
            is_consistent = bool(block.is_consistent())
        except Exception:
            # Defensivo: si lanza (raro), asumimos NO consistente y compilamos.
            is_consistent = False
        if is_consistent:
            skipped_unchanged.append(name)
            continue
        # .compile() retorna True si hay errores (semantica Siemens §2.2.11).
        try:
            had_errors = bool(block.compile())
            compiled.append({
                "name": name,
                "had_errors": had_errors,
                "was_inconsistent": True,
            })
        except Exception as exc:
            errors.append({
                "name": name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {
        "compiled": compiled,
        "skipped_unchanged": skipped_unchanged,
        "not_found": not_found,
        "errors": errors,
        # Campos top-level para que ``_summarize_result`` (en
        # ``tia_helpers.py``) los incluya en el log del decorador
        # ``@log_ot_command``. Asi el operario ve en la consola web
        # ``n_compiled_ok=5, n_compiled_err=2, n_skipped=10, ...`` sin
        # tener que abrir el dict completo.
        "n_compiled_ok": sum(
            1 for c in compiled if not c["had_errors"]
        ),
        "n_compiled_err": sum(
            1 for c in compiled if c["had_errors"]
        ) + len(errors),
        "n_skipped": len(skipped_unchanged),
        "n_not_found": len(not_found),
        "n_errors": len(errors),
    }


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 2 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "compile_plc": _h_compile_plc,
    "compile_blocks": _h_compile_blocks,
}


__all__ = [
    "COMMANDS",
    "_h_compile_plc",
    "_h_compile_blocks",
]
