"""zc_suite.errores — el contrato de errores de la app.

``TIAError`` es la base de todos los fallos del subsistema TIA.
``OperacionError`` es el fallo esperado de una operacion: los que el
operario puede corregir (no hay proyecto abierto, el PLC no existe, el
fichero no esta...). Se registran como warning, sin traceback, a diferencia de
lo inesperado.

Vive aqui, y no en ``nucleo/tia``, porque la **logica pura** de los dominios
tambien necesita lanzar fallos esperados sin depender de TIA.
"""
from __future__ import annotations


class TIAError(Exception):
    """Fallo del subsistema TIA."""


class OperacionError(TIAError):
    """Fallo esperado de una operacion.

    Son fallos que el operario puede corregir: se registran como warning, sin
    traceback, a diferencia de lo inesperado.
    """
