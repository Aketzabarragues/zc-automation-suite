"""zc_suite.nucleo.tia.errores — los errores propios del subsistema TIA.

Los fallos son **excepciones**, nunca un ``{"ok": False}`` que alguien tenga
que comprobar. Todas cuelgan de ``TIAError`` (que vive en ``zc_suite.errores``,
junto a ``OperacionError``), para que quien llame pueda pillarlas de una vez.
"""
from __future__ import annotations

import logging

from zc_suite.errores import TIAError

logger = logging.getLogger(__name__)


# ── errores ────────────────────────────────────────────────────────────────


class OcupadoError(TIAError):
    """Hay un trabajo en curso: no se puede encolar otro."""


class SinPortalError(TIAError):
    """No hay conexion con TIA Portal."""


class SinProyectoError(TIAError):
    """No hay ningun proyecto abierto en TIA Portal."""


class CanceladoError(TIAError):
    """El trabajo fue cancelado por el operario."""


class TransaccionError(TIAError):
    """Fallo en una transaccion de TIA.

    El mensaje distingue si fallo la operacion o el commit de la
    transaccion, y si el rollback se pudo completar.
    """


class FueraDelHiloError(TIAError):
    """El portal se ha usado desde un hilo que no es el de TIA."""

def texto_error(exc: BaseException) -> str:
    """Texto del error de un trabajo: tipo, mensaje y notas.

    Las notas las anade ``transaccion`` con ``add_note``. No se tocan los
    ``args`` de la excepcion: para ``OSError`` y ``KeyError`` el mensaje se
    construye a partir de ellos y se perderia.
    """
    texto = f"{type(exc).__name__}: {exc}"
    notas = getattr(exc, "__notes__", None)
    if notas:
        texto = f"{texto} [{' | '.join(notas)}]"
    return texto
