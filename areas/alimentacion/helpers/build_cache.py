"""Workdir layout del área alimentación: dispositivos y procesos.

Extiende ``core.infrastructure.tia.tia_workdir_layout.WorkdirAreaLayout``
con los contextos (bounded contexts del área) que necesita hoy:

* ``dispositivos``: ciclo de export/modify/import de los 6 DBs de
  dispositivos (ED, EA, SA, V, M, M_VF) + tabla N_MAX.
* ``procesos``: ciclo análogo para los bloques de proceso
  (PReal, PInt, ALM).

MaÃ±ana, ``areas/trazabilidad/infrastructure/build_cache.py`` aportará
su propio ``TrazabilidadAreaLayout`` con ``.lotes`` y ``.recetas``
siguiendo el mismo patrón â€” sin tocar ``core/``.

Convenio de uso
===============

.. code-block:: python

    from areas.alimentacion.helpers.build_cache import build_cache

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

from areas.alimentacion._area_id import AREA_ID
from core.infrastructure.tia.tia_workdir_layout import (
    TIAWorkdirLayout,
    WorkdirAreaLayout,
    WorkdirContextLayout,
)


@dataclass(frozen=True)
class AlimentacionAreaLayout(WorkdirAreaLayout):
    """Workdir layout del área alimentación con sus contextos.

    AÃ±ade ``.dispositivos`` y ``.procesos`` como ``cached_property``
    sobre la base genérica de ``core``. Si en el futuro el área gana
    más contextos (e.g. ``.recetas``), se aÃ±aden aquí como
    ``@cached_property`` adicionales â€” el core no se toca.
    """

    @cached_property
    def dispositivos(self) -> WorkdirContextLayout:
        """Contexto de dispositivos (N_MAX + 6 DBs de devices)."""
        return WorkdirContextLayout(self.root / "dispositivos")

    @cached_property
    def procesos(self) -> WorkdirContextLayout:
        """Contexto de procesos (PReal + PInt + ALM)."""
        return WorkdirContextLayout(self.root / "procesos")


def build_cache(root: Path | None = None) -> AlimentacionAreaLayout:
    """Atajo: devuelve el layout de alimentación ya configurado.

    Por defecto, ``root = <cwd>/.build_cache``. Tests pueden
    inyectar un ``tmp_path`` directamente:

    .. code-block:: python

        def test_x(tmp_path):
            ctx = build_cache(root=tmp_path).dispositivos
            assert ctx.exports == tmp_path / "alimentacion" / "dispositivos" / "exports"

    Returns:
        ``AlimentacionAreaLayout`` con ``.dispositivos`` y ``.procesos``
        listos para usar.
    """
    bc = TIAWorkdirLayout(
        area_id=AREA_ID,
        root=root if root is not None else Path(os.getcwd()) / ".build_cache",
    )
    return AlimentacionAreaLayout(area_id=bc.area_id, root=bc.area.root)


__all__ = ["AlimentacionAreaLayout", "build_cache"]
