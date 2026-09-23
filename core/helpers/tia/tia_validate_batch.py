"""Validador del resultado de ``execute_batch`` (best-effort).

``execute_batch`` es best-effort: si un sub-comando falla, el handler
anota el error en su entrada de ``details`` y CONTINUA con los
siguientes. Nunca raise. Esto es util para regenerar un preview
aunque fallen algunos exports, pero significa que el CALLER tiene que
validar ``result["success"]`` explicitamente.

Sin validacion, el FB sigue adelante asumiendo que todo OK y produce
resultados inconsistentes. ``validate_execute_batch_result`` levanta
excepcion detallada si alguna op fallo, propagando el error al caller
para que el FB lo capture en su ``except`` propio.

Reglas arquitectonicas:
  - Helper transversal (sin estado).
  - NO importa ``siemens_tia_scripting``.
  - Levanta ``RuntimeError`` (consistente con el resto de helpers de TIA).
"""
from __future__ import annotations

from typing import Any


def validate_execute_batch_result(
    result: Any,
    *,
    undo_text: str = "",
    plc_name: str = "",
    log: Any = None,
) -> None:
    """Valida ``result`` de un ``execute_batch`` y raise si hubo fallos.

    Args:
        result: el ``result`` del dispatch (dict con ``success``,
            ``operations_executed``, ``operations_failed``, ``details``).
        undo_text: nombre de la operacion (para el mensaje de error).
        plc_name: nombre del PLC (para el mensaje de error).
        log: logger opcional. Si se pasa y hubo fallos, emite WARNING
            antes de raise.

    Raises:
        RuntimeError: si ``result["success"] is False``. El mensaje
            incluye el numero de operaciones ejecutadas y falladas,
            los comandos que fallaron y el primer error de cada uno
            (truncado a 200 chars).
    """
    if not isinstance(result, dict):
        # No-op si el handler devolvio algo raro (no deberia, pero defensivo).
        return

    # ``success`` puede faltar (handler antiguo, resultado parcial).
    # Si esta presente y True, OK. Si esta presente y False, raise.
    # Si falta, derivamos: no hay failures en details ni en
    # ``operations_failed`` -> OK. En otro caso raise.
    if "success" in result:
        if result["success"] is True:
            return
    else:
        details_inspect = result.get("details") or []
        all_ok = all(
            isinstance(d, dict) and d.get("ok") is True
            for d in details_inspect
        ) if details_inspect else True
        if all_ok and result.get("operations_failed", 0) == 0:
            return

    details = result.get("details") or []
    executed = result.get("operations_executed", 0)
    failed = result.get("operations_failed", 0)

    failed_lines: list[str] = []
    for d in details:
        if not isinstance(d, dict) or d.get("ok") is True:
            continue
        step = d.get("step", "?")
        cmd = d.get("command", "?")
        err = (d.get("error") or "").replace("\n", " ")[:200]
        failed_lines.append(f"  step {step} '{cmd}': {err}")

    failure_summary = "\n".join(failed_lines) if failed_lines else "  (sin detalle)"

    prefix_parts = []
    if undo_text:
        prefix_parts.append(f"'{undo_text}'")
    if plc_name:
        prefix_parts.append(f"plc={plc_name}")
    prefix = " ".join(prefix_parts)
    prefix_block = f"[{prefix}] " if prefix else ""

    msg = (
        f"{prefix_block}execute_batch fallo: {failed}/{executed} ops "
        f"con error.\n{failure_summary}"
    )

    if log is not None:
        try:
            log.warning(msg)
        except Exception:
            pass

    raise RuntimeError(msg)


__all__ = ["validate_execute_batch_result"]
