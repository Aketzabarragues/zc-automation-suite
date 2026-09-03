"""DEPRECATED: shim de back-compat para ``DispMLCRegistry``.

La clase ``DispMLCRegistry`` se renombró a ``MLCRegistry`` y se
movió a ``areas/alimentacion.infrastructure.sd.mlc_registry``.
Este módulo se conserva **solo** para no romper imports legacy
(``disp_comment_updater.py``, tests ``test_disp_mlc_registry.py``,
etc.). La nueva ubicación canónica es:

    from areas.alimentacion.infrastructure.sd.mlc_registry import (
        MLCRegistry, DispMLCRegistry
    )

Las dos clases exportadas (``MLCRegistry`` y el alias
``DispMLCRegistry``) son **la misma** — usar el alias es
back-compat puro, no añade valor. Las áreas deben migrar al nombre
canónico en próximas refactorizaciones.

Historia
--------
Originalmente este módulo contenía la implementación completa de
``DispMLCRegistry``. Tras la introducción de
``ProcCommentUpdater`` (que también necesita un registro de MLCs
para los DBs de procesos PReal / PInt / ALM), se decidió unificar
la implementación en ``MLCRegistry`` (nombre neutral al área) y
dejar este archivo como shim.

API pública idéntica a la original
-----------------------------------
``MLCRegistry`` (y su alias ``DispMLCRegistry``) exponen los 5
métodos públicos + 1 dunder:

  - ``reserve(used_ids)``             – añade IDs al set.
  - ``is_used(mlc_id)``               – True si está registrado.
  - ``__contains__`` (== ``is_used``) – azúcar.
  - ``release(mlc_id)``               – saca un ID del set.
  - ``next_mlc_id()``                 – genera MLC nuevo no colisionante.
  - ``__len__()``                     – nº de IDs en uso.

Nota técnica
------------
Reexportamos también ``random`` (el módulo de stdlib) como atributo
de este shim. Razón: el test legacy
``test_disp_mlc_registry.py::test_runtime_error_si_no_hay_ids_disponibles``
parchea la ruta ``areas.alimentacion.infrastructure.sd.disp_mlc_registry.random``
para forzar colisiones deterministas. Como ``random`` es un singleton
de la stdlib, exponerlo aquí vía ``import random`` lo hace visible
bajo la ruta legacy y el patch sigue funcionando aunque la
implementación real viva en ``mlc_registry.py``.
"""
import random

from areas.alimentacion.infrastructure.sd.mlc_registry import (
    DispMLCRegistry,
    MLCRegistry,
)


__all__ = ["MLCRegistry", "DispMLCRegistry", "random"]
