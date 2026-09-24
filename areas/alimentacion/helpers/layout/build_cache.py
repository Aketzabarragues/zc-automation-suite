"""Workdir layout del área alimentación: dispositivos y procesos.

Punto de entrada único para resolver los workdirs del área:

  - ``dispositivos``: ciclo de export/modify/import de los DBs de dispositivos del área (data-driven vía ``config.json``).
    dispositivos + tabla N_MAX (estructura DispLayout).
  - ``procesos``: ciclo análogo para PReal, PInt, ALM (estructura
    ProcDbLayout).

Convenio de uso
===============

.. code-block:: python

    from areas.alimentacion.helpers.build_cache import build_cache

    # Contexto de dispositivos
    disp = build_cache().dispositivos
    disp.clean_preview()         # antes del preview

    # Contexto de proc_db
    proc = build_cache().procesos
    proc.clean_sincronizar()     # antes del apply

Constantes
==========

- ``DEFAULT_BUILD_CACHE_ROOT``: ``<cwd>/.build_cache``. Fallback único
  cuando nadie inyecta ``root=`` o ``build_cache=``. Evaluada en
  import time; el launcher de la app no cambia CWD despues del
  bootstrap, asi que el valor es estable durante toda la vida del
  proceso.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from areas.alimentacion._area_id import AREA_ID
from areas.alimentacion.helpers.disp._workdir_layout import (
    DispLayout,
    build_disp_layout,
)
from areas.alimentacion.helpers.proc._workdir_layout import (
    ProcDbLayout,
    build_proc_db_layout,
)


DEFAULT_BUILD_CACHE_ROOT: Path = Path(os.getcwd()) / ".build_cache"


@dataclass(frozen=True)
class AlimentacionAreaLayout:
    """Workdir layout del área alimentación con sus contextos.

    Atributos:
        area_id: Identificador del área (siempre ``"alimentacion"``).
        root:    Directorio raíz del área (``<build_cache>/alimentacion``).

    Propiedades:
        dispositivos: ``DispLayout`` apuntando a ``<root>/disp/``.
        procesos:     ``ProcDbLayout`` apuntando a ``<root>/proc_db/``.
    """

    area_id: str
    root: Path

    @cached_property
    def dispositivos(self) -> DispLayout:
        """Contexto de dispositivos (DispLayout, sept-2026).

        Layout::

            .build_cache/alimentacion/disp/
            +-- preview/
            |   +-- config/                  # N_MAX (FLAT, 1 archivo)
            |   +-- disp/                    # 6 tag tables (FLAT)
            +-- sincronizar/
                +-- variables/{export,modified}
                +-- bloques/{export,modified}

        Metodos de limpieza granulares:
          - clean_preview(): borra preview/.
          - clean_sincronizar(): borra sincronizar/.
          - clean_all(): borra todo el disp/.
        """
        return build_disp_layout(root=self.root / "disp")

    @cached_property
    def procesos(self) -> ProcDbLayout:
        """Contexto de proc_db (ProcDbLayout, sept-2026).

        Layout::

            .build_cache/alimentacion/proc_db/
            +-- preview/
            |   +-- bloques/                 # DBs (FLAT)
            |   +-- variables/               # tag tables (FLAT, N_MAX aqui)
            +-- sincronizar/
                +-- variables/{export,modified}
                +-- bloques/{export,modified}

        Metodos de limpieza granulares:
          - clean_preview(): borra preview/.
          - clean_sincronizar(): borra sincronizar/.
          - clean_all(): borra todo el proc_db/.

        NO incluye ``proceso_nuevo`` (su propio layout, fuera de scope).
        """
        return build_proc_db_layout(root=self.root / "proc_db")


def build_cache(root: Path | None = None) -> AlimentacionAreaLayout:
    """Atajo: devuelve el layout de alimentación ya configurado.

    Por defecto, ``base = <cwd>/.build_cache`` y el layout vive en
    ``<base>/alimentacion/``. Tests pueden inyectar un ``tmp_path``
    directamente:

    .. code-block:: python

        def test_x(tmp_path):
            ctx = build_cache(root=tmp_path).dispositivos
            assert ctx.preview_config == tmp_path / "alimentacion" / "disp" / "preview" / "config"

    Returns:
        ``AlimentacionAreaLayout`` con ``.dispositivos`` y ``.procesos``
        listos para usar.
    """
    base = root if root is not None else DEFAULT_BUILD_CACHE_ROOT
    return AlimentacionAreaLayout(area_id=AREA_ID, root=base / "alimentacion")


__all__ = ["AlimentacionAreaLayout", "DEFAULT_BUILD_CACHE_ROOT", "build_cache"]
