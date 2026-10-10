"""core.infrastructure.tia.tia_state_cache - cache de state del worker TIA.

Caches distintos de ``plc_blocks`` (que viven en ``tia_cache.py``):
  - ``plc_list``: lista de PLCs descubiertos por el worker.
  - ``plc_project``: info del proyecto TIA activo (keyed por plc_name).
  - ``plc_user_constants``: N_MAX del PLC (keyed por plc_name).

Helpers puros: operan sobre ``AppCache`` sin guardar estado propio. Las
mutaciones van siempre bajo ``app_cache.mutate()`` (lock atomico).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from core.data.data_plc_info import PlcInfo, PlcProject
from core.runtime.app_cache import AppCache


# plc_list ----------------------------------------------------------------

def plc_list_get(app_cache: AppCache) -> tuple[PlcInfo, ...]:
    """Devuelve la tupla de PLCs cacheados (vacia si nunca se escaneo)."""
    return app_cache.get_state().plc_list


def plc_list_set(
    app_cache: AppCache,
    plcs: tuple[PlcInfo, ...] | list[PlcInfo],
) -> None:
    """Reemplaza la lista de PLCs."""
    payload = tuple(plcs)
    app_cache.mutate(
        lambda s: dataclasses.replace(s, plc_list=payload),
    )


def plc_list_clear(app_cache: AppCache) -> None:
    """Vacia la lista de PLCs."""
    app_cache.mutate(lambda s: dataclasses.replace(s, plc_list=()))


# plc_project -------------------------------------------------------------

def plc_project_get(
    app_cache: AppCache,
    plc_name: str,
) -> PlcProject | None:
    """Devuelve el proyecto TIA asociado a ``plc_name`` o ``None``."""
    return app_cache.get_state().plc_project.get(plc_name)


def plc_project_set(
    app_cache: AppCache,
    plc_name: str,
    project: PlcProject,
) -> None:
    """Guarda el proyecto TIA bajo la clave ``plc_name``."""
    app_cache.mutate(
        lambda s: dataclasses.replace(
            s,
            plc_project={**s.plc_project, plc_name: project},
        ),
    )


def plc_project_clear(
    app_cache: AppCache,
    plc_name: str | None = None,
) -> None:
    """Borra proyectos del cache.

    - ``plc_name=None`` -> borra TODOS.
    - ``plc_name="X"`` -> borra solo el de ``X``.
    """
    if plc_name is None:
        app_cache.mutate(
            lambda s: dataclasses.replace(s, plc_project={}),
        )
        return

    def _clear(state: Any) -> Any:
        d = dict(state.plc_project)
        d.pop(plc_name, None)
        return dataclasses.replace(state, plc_project=d)

    app_cache.mutate(_clear)


# plc_user_constants ------------------------------------------------------

def plc_user_constants_get(
    app_cache: AppCache,
    plc_name: str,
) -> Mapping[str, int]:
    """Devuelve el mapping de N_MAX del PLC ``as TIA`` (vacio si no existe)."""
    return app_cache.get_state().plc_user_constants.get(plc_name, {})


def plc_user_constants_set(
    app_cache: AppCache,
    plc_name: str,
    constants: Mapping[str, int],
) -> None:
    """Guarda el mapping de N_MAX bajo ``plc_name``."""
    app_cache.mutate(
        lambda s: dataclasses.replace(
            s,
            plc_user_constants={**s.plc_user_constants, plc_name: dict(constants)},
        ),
    )


def plc_user_constants_clear(
    app_cache: AppCache,
    plc_name: str | None = None,
) -> None:
    """Borra N_MAX del cache.

    - ``plc_name=None`` -> borra TODOS.
    - ``plc_name="X"`` -> borra solo el de ``X``.
    """
    if plc_name is None:
        app_cache.mutate(
            lambda s: dataclasses.replace(s, plc_user_constants={}),
        )
        return

    def _clear(state: Any) -> Any:
        d = dict(state.plc_user_constants)
        d.pop(plc_name, None)
        return dataclasses.replace(state, plc_user_constants=d)

    app_cache.mutate(_clear)


__all__ = [
    "plc_list_get",
    "plc_list_set",
    "plc_list_clear",
    "plc_project_get",
    "plc_project_set",
    "plc_project_clear",
    "plc_user_constants_get",
    "plc_user_constants_set",
    "plc_user_constants_clear",
]