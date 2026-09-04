"""BuildCache del área alimentación: dispositivos y procesos.

Extiende ``core.infrastructure.build_cache.AreaCache`` con los
contextos (bounded contexts del área) que necesita hoy:

* ``dispositivos``: ciclo de export/modify/import de los 6 DBs de
  dispositivos (ED, EA, SA, V, M, M_VF) + tabla N_MAX.
* ``procesos``: ciclo análogo para los bloques de proceso
  (PReal, PInt, ALM).

Mañana, ``areas/trazabilidad/infrastructure/build_cache.py`` aportará
su propio ``TrazabilidadAreaCache`` con ``.lotes`` y ``.recetas``
siguiendo el mismo patrón — sin tocar ``core/``.

Convenio de uso
===============

.. code-block:: python

    from areas.alimentacion.infrastructure.build_cache import build_cache

    # Contexto de dispositivos
    disp = build_cache().dispositivos
    s7dcl = SdPair(disp.exports, "DB2000_ED").dcl

    # Contexto de procesos
    proc = build_cache().procesos
    proc.clean()  # antes del apply
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from areas.alimentacion import AREA_ID
from core.infrastructure.build_cache import (
    AreaCache as _CoreAreaCache,
)
from core.infrastructure.build_cache import (
    BuildCache,
    ContextCache,
)


@dataclass(frozen=True)
class AlimentacionAreaCache(_CoreAreaCache):
    """``AreaCache`` del área alimentación con sus contextos.

    Añade ``.dispositivos`` y ``.procesos`` como ``cached_property``
    sobre la base genérica de ``core``. Si en el futuro el área gana
    más contextos (e.g. ``.recetas``), se añaden aquí como
    ``@cached_property`` adicionales — el core no se toca.
    """

    @cached_property
    def dispositivos(self) -> ContextCache:
        """Contexto de dispositivos (N_MAX + 6 DBs de devices)."""
        return ContextCache(self.root / "dispositivos")

    @cached_property
    def procesos(self) -> ContextCache:
        """Contexto de procesos (PReal + PInt + ALM)."""
        return ContextCache(self.root / "procesos")


def build_cache(root: Path | None = None) -> AlimentacionAreaCache:
    """Atajo: devuelve el ``AreaCache`` de alimentación ya configurado.

    Por defecto, ``root = <cwd>/.build_cache``. Tests pueden
    inyectar un ``tmp_path`` directamente:

    .. code-block:: python

        def test_x(tmp_path):
            ctx = build_cache(root=tmp_path).dispositivos
            assert ctx.exports == tmp_path / "alimentacion" / "dispositivos" / "exports"

    Returns:
        ``AlimentacionAreaCache`` con ``.dispositivos`` y ``.procesos``
        listos para usar.
    """
    bc = BuildCache(
        area_id=AREA_ID,
        root=root if root is not None else Path(os.getcwd()) / ".build_cache",
    )
    return AlimentacionAreaCache(area_id=bc.area_id, root=bc.area.root)


__all__ = ["AlimentacionAreaCache", "build_cache"]
