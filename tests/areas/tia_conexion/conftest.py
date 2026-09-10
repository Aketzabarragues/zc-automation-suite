"""Conftest de tests del area ``tia_conexion``.

Proposito:
    El ``area_registry`` es un singleton en memoria
    (``core.application.area_registry._REGISTRY``). Los tests de
    registry (``test_area_registry.py``) usan un fixture ``autouse``
    que llama a ``reg.reset()`` antes y despues de cada test para
    garantizar aislamiento. Esto deja el registry vacio al final
    de la suite de registry, lo que rompe los tests del router
    (``test_router_areas.py``) que esperan ver el area
    ``tia_conexion`` registrada.

Solucion:
    Esta conftest instala un fixture ``autouse=True`` de **setup
    unico** que se ejecuta ANTES de cualquier test del directorio
    (incluidos los de registry). Su unica responsabilidad es
    registrar el area ``tia_conexion`` si no esta ya en el
    registry. Asi:
      - Los tests de registry ven el registry vacio (su propio
        fixture ``_clean_registry`` corre DESPUES y resetea).
      - Los tests del router ven el area registrada (su fixture
        no toca el registry).

Por que autouse=True:
    Para que los tests del router no tengan que declarar
    explicitamente la dependencia del area. Es el mismo patron
    que usan las demas conftests del proyecto (ver
    ``tests/conftest.py`` en Fase 1).

Por que setup-only (no teardown):
    El fixture de los tests de registry (``_clean_registry``) ya
    hace teardown con ``reg.reset()``. Si esta conftest hiciera
    teardown, el orden seria: setup conftest, setup test, test,
    teardown test, teardown conftest. Y el teardown conftest
    dejaria el registry en un estado conocido (con el area
    registrada), lo cual contaminaria los tests que esperan
    empezar con registry vacio.

    La forma mas simple y robusta: esta conftest solo hace setup.
    Si un test dejo el registry vacio, el siguiente test del
    directorio lo vera asi (y su propio fixture o setup hara
    lo que necesite).
"""
from __future__ import annotations

import pytest

from areas.tia_conexion import AREA_SPEC
from core.application import area_registry as reg


@pytest.fixture(autouse=True)
def _ensure_tia_conexion_registered() -> None:
    """Asegura que ``tia_conexion`` esta en el registry antes del test.

    Comportamiento:
      - Si el area YA esta registrada (caso normal: ``create_app()``
        la registro al importar ``core.web.app``), no hace nada.
      - Si NO esta registrada (caso: un test anterior hizo
        ``reg.reset()`` y no la restauro), la registra.

    Note:
        Este fixture corre en el SETUP. Si el test quiere un
        registry vacio (caso de los tests de registry), su propio
        fixture ``_clean_registry`` (``autouse=True`` en
        ``test_area_registry.py``) corre DESPUES y resetea.
    """
    if not any(a.key == AREA_SPEC.key for a in reg.get_areas()):
        reg.register(AREA_SPEC)
