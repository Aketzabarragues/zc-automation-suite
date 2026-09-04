"""Identificador can\u00f3nico del \u00e1rea de alimentaci\u00f3n.

M\u00f3dulo deliberadamente minimal: una sola constante, sin imports
del paquete. Esto evita el **circular import** que se producir\u00eda si
cualquier subm\u00f3dulo del \u00e1rea (p. ej.
``infrastructure/build_cache.py``) importase ``AREA_ID`` desde
``areas/alimentacion/__init__.py``: el ``__init__`` carga muchos
subm\u00f3dulos, y si uno de ellos vuelve a pedirle ``AREA_ID`` antes
de que termine de inicializarse, Python lanza
``ImportError: cannot import name 'X' from partially initialized
module``.

Convenci\u00f3n
--------------

* El \u00fanico sitio donde vive la verdad es ESTE archivo.
* ``areas/alimentacion/__init__.py`` re-exporta ``AREA_ID`` para
  consumo externo (otros paquetes, tests, entrypoints).
* Cualquier subm\u00f3dulo del \u00e1rea que necesite el id importa
  directamente de aqu\u00ed (``from areas.alimentacion._area_id
  import AREA_ID``), NO del ``__init__``.
* ``AREA_SPEC.id`` en ``__init__.py`` debe coincidir con esta
  constante (validado a ojo; en el futuro se puede a\u00f1adir un
  assert en el arranque).

Mañana, ``areas/trazabilidad/_area_id.py`` tendr\u00e1 su propio
``AREA_ID = "trazabilidad"`` siguiendo el mismo patr\u00f3n (un
m\u00f3dulo por \u00e1rea, sin acoplamiento entre \u00e1reas).
"""
from __future__ import annotations


AREA_ID: str = "alimentacion"


__all__ = ["AREA_ID"]
