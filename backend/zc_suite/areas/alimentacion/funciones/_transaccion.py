"""zc_suite.areas.alimentacion.funciones._transaccion — la transaccion comun.

El helper de transaccion de los FB de sync de las areas: ejecuta la
operacion dentro de ``transaccion`` y anota en el resumen del sync si se
confirmo o se revirtio. Vive en ``funciones/`` (no en
``sincronizacion_comun.py``) porque es lo unico comun que recibe el
``job`` y toca ``zc_suite.nucleo.tia``: el resto de ``sincronizacion_comun``
es puro respecto a TIA.
"""
from __future__ import annotations

from typing import Any

from zc_suite.areas.alimentacion.sincronizacion_comun import (
    estado_confirmada,
    estado_revertida,
    resumen_transacciones,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.tia.errores import CanceladoError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion


def _transaccion(
    job: Job,
    transacciones: dict[str, dict[str, Any]],
    clave: str,
    texto: str,
    operacion: Any,
    resumen: str,
) -> None:
    """Ejecuta una transaccion y anota si se confirmo o se revirtio.

    Args:
        job: el trabajo en curso.
        transacciones: el estado de las transacciones del sync.
        clave: la clave de la transaccion dentro de ``transacciones``.
        texto: el texto de la transaccion en TIA.
        operacion: lo que se hace dentro de la transaccion.
        resumen: lo que se cuenta en el detalle del paso.

    Raises:
        Exception: lo que falle dentro de la transaccion, con el estado de
            las transacciones anadido al mensaje.
    """
    try:
        with transaccion(job, texto):
            operacion()
    except CanceladoError:
        # La cancelacion del operario no es un fallo: sale tal cual para que
        # el trabajo termine como cancelado y no como error.
        estado_revertida(transacciones, clave, "el trabajo fue cancelado")
        raise
    except Exception as exc:
        estado_revertida(transacciones, clave, str(exc))
        raise OperacionError(
            f"{exc}. {resumen_transacciones(transacciones)}"
        ) from exc
    estado_confirmada(transacciones, clave, resumen)
