"""tia_ops — operaciones contra TIA Portal.

Cada modulo expone funciones que reciben el portal (o el ``PlcSoftware``) como
primer argumento y devuelven solo tipos primitivos: ``dict``, ``list``,
``str``, ``int``, ``bool``. Ningun objeto .NET sale de este paquete.

Modulos:

- ``proyecto.py``  abrir el proyecto de TIA Portal.
- ``exportar.py``  exportar bloques, tags y tablas a disco.
- ``importar.py``  importar bloques y tags desde disco.
- ``compilar.py``  compilar el software del PLC.
- ``constantes.py`` constantes de usuario del PLC: leer, cambiar el valor y
  renombrar.
- ``bloques.py``  bloques del PLC: listarlos con sus propiedades y cambiar su
  nombre o su numero.

Los helpers que resuelven objetos .NET viven en ``_resolver.py`` y se usan
entre modulos del paquete. Lo publico de cada modulo es siempre primitivo.
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
