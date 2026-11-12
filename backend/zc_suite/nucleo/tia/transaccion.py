"""zc_suite.nucleo.tia.transaccion — la transaccion nativa de TIA.

``transaccion(job, texto)`` envuelve las escrituras en TIA: hace
``start_transaction`` -> yield -> ``end_transaction(rollback=False)``. Si
salta cualquier excepcion, hace ``end_transaction(rollback=True)`` y vuelve a
lanzarla. Si el commit falla, tambien intenta el rollback y lanza
``TransaccionError`` diciendo que fallo el commit.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from zc_suite.nucleo.tia.errores import SinProyectoError, TransaccionError
from zc_suite.nucleo.tia.job import Job

logger = logging.getLogger(__name__)


# ── transaccion ────────────────────────────────────────────────────────────


def proyecto_activo(portal: Any) -> Any:
    """Devuelve el proyecto abierto del portal.

    Es el unico sitio donde se resuelve el proyecto: las operaciones de
    ``tia_ops`` lo reutilizan.

    Raises:
        SinProyectoError: si no hay ningun proyecto abierto.
    """
    proyecto = portal.get_project()
    if not proyecto:
        raise SinProyectoError(
            "No hay ningun proyecto abierto en TIA Portal. Abre el proyecto y repite."
        )
    return proyecto


def _revertir(proyecto: Any, texto: str) -> tuple[bool, str]:
    """Ejecuta el rollback de la transaccion.

    Returns:
        Tupla ``(ok, descripcion)``. ``ok`` es ``False`` si el rollback
        fallo; la descripcion dice que paso.
    """
    try:
        proyecto.end_transaction(rollback=True)
    except Exception as exc:
        logger.error(
            "Rollback fallido tras abortar '%s': %s: %s",
            texto,
            type(exc).__name__,
            exc,
        )
        return (
            False,
            f"Rollback NO completado ({type(exc).__name__}: {exc}): "
            "el proyecto puede haber quedado a medias.",
        )
    return True, "Rollback ejecutado."

@contextmanager
def transaccion(job: Job, texto: str) -> Iterator[None]:
    """Envuelve las escrituras en TIA en una transaccion nativa.

    Hace ``start_transaction`` -> yield -> ``end_transaction(rollback=False)``.

    Si la operacion falla, hace ``end_transaction(rollback=True)`` y vuelve a
    lanzar la misma excepcion con una nota que dice que fallo la operacion y
    si el rollback se pudo completar.

    Si el commit falla, tambien intenta el rollback y lanza
    ``TransaccionError`` diciendo que fallo el commit.

    Raises:
        TransaccionError: si fallo el commit, o si fallo la operacion y su
            rollback tampoco se pudo completar.
    """
    proyecto = proyecto_activo(job.tia.portal)
    proyecto.start_transaction(undo_text=texto, dialog_text=texto)
    try:
        yield
    except BaseException as exc:
        ok_rollback, rollback_txt = _revertir(proyecto, texto)
        if not ok_rollback:
            raise TransaccionError(
                f"Fallo de la operacion en la transaccion '{texto}': "
                f"{type(exc).__name__}: {exc}. {rollback_txt}"
            ) from exc
        exc.add_note(f"Transaccion '{texto}': fallo de la operacion. {rollback_txt}")
        raise
    else:
        try:
            proyecto.end_transaction(rollback=False)
        except Exception as exc_commit:
            ok_rollback, rollback_txt = _revertir(proyecto, texto)
            if ok_rollback:
                detalle = "No se confirmó nada: el rollback dejó el proyecto como estaba."
            else:
                detalle = rollback_txt
            raise TransaccionError(
                f"Fallo del commit de la transaccion '{texto}': "
                f"{type(exc_commit).__name__}: {exc_commit}. {detalle}"
            ) from exc_commit
