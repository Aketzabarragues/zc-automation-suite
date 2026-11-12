"""zc_suite.errores — el contrato de errores de la app.

``ZCError`` es la base de todos los fallos **esperados**: los que el operario
puede corregir (no hay proyecto abierto, el PLC no existe, el fichero no
esta...). Se registran como warning, sin traceback, a diferencia de lo
inesperado.

``OperacionError`` es el fallo esperado de una operacion. Los errores propios
de TIA Portal cuelgan de ``TIAError`` (``zc_suite.nucleo.tia.errores``), que
tambien cuelga de aqui.

Vive en la raiz del paquete, y no en ``nucleo/tia``, porque la **logica pura**
de los dominios tambien necesita lanzar fallos esperados sin depender de TIA.
"""
from __future__ import annotations


class ZCError(Exception):
    """Fallo esperado de la app."""


class OperacionError(ZCError):
    """Fallo esperado de una operacion.

    Son fallos que el operario puede corregir: se registran como warning, sin
    traceback, a diferencia de lo inesperado.
    """
