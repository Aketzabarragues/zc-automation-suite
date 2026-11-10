"""tia_ops — operaciones contra TIA Portal.

Cada modulo expone funciones que reciben el portal (o el ``PlcSoftware``) como
primer argumento y devuelven solo tipos primitivos: ``dict``, ``list``,
``str``, ``int``, ``bool``. Ningun objeto .NET sale de este paquete.

Modulos:

- ``proyecto.py``  abrir y guardar el proyecto; resolver PLC y tablas.
- ``exportar.py``  exportar bloques, tags y tablas a disco.
- ``importar.py``  importar bloques y tags desde disco.
- ``compilar.py``  compilar el software del PLC.
- ``constantes.py`` nombres de tablas y carpetas por defecto.
- ``bloques.py``   recorrido y clasificacion de bloques.

Los helpers que resuelven objetos .NET son privados (``.`` con guion bajo) y
se usan entre modulos del paquete. Lo publico de cada modulo es siempre
primitivo.
"""
from __future__ import annotations

from zc_suite.tia import TIAError


class OperacionError(TIAError):
    """Fallo esperado de una operacion contra TIA.

    No hay proyecto abierto, el PLC no existe, el fichero no esta... Son
    fallos que el operario puede corregir: se registran como warning, sin
    traceback, a diferencia de lo inesperado.
    """


__all__ = ["OperacionError"]
