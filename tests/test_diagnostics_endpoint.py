"""Tests del endpoint ``GET /api/v1/state/dispositivos`` con la extensión Fase 6.

Cubre la integración de los 4 dominios de software (Procesos /
Parametros Int / Parametros Real / Alarmas) y el flag
``software_parsers_implemented`` en el response del endpoint de
diagnóstico.

Plan canónico de referencia:
``_plan/04_excel_cache_phased_plan.md`` §10 (Fase 6).

Casos cubiertos:
  1. Sin upload previo (cache ``None``) → arrays vacíos y flag ``false``.
  2. Tras upload (cache populado) → 4 arrays con datos y flag ``true``.
  3. Back-compat: ``dispositivos`` y ``dimensiones`` mantienen la
     forma legacy.
  4. El response completo es JSON-serializable.
  5. Modo degradado: ``state.dimensiones`` ``None`` → ``{}``.

Patrón: TestClient con gateway mockeado + ``AppState`` con
``excel_cache`` mockeado (porque ``excel_cache`` es ``Any`` en
``AppState`` y se resuelve en runtime contra el ``ExcelCache`` del
área de alimentación).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.application.state import AppState, get_app_state  # noqa: E402
from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402
from interfaces.web_server.app import create_app  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def state_clean() -> AppState:
    """AppState Singleton reseteado para que cada test vea estado limpio.

    Importante: el ``AppState`` es un Singleton global
    (``get_app_state``). Hay que limpiar los campos mutables
    (``excel_cache``, ``excel_path``, ``dimensiones``,
    ``_dispositivos``) entre tests para que el resultado de un test
    no contamine al siguiente.
    """
    state = get_app_state()
    state.reset()
    state.excel_cache = None
    state.excel_path = None
    state.dimensiones = None
    yield state
    # Cleanup post-test.
    state.reset()
    state.excel_cache = None
    state.excel_path = None
    state.dimensiones = None


@pytest.fixture
def client(state_clean: AppState) -> TestClient:
    """TestClient con gateway mockeado y ``AppState`` limpio."""
    gateway = MagicMock(spec=TIAProcessGateway)
    app = create_app(gateway)
    return TestClient(app)


def _make_mock_excel_cache(
    *,
    procesos: tuple = (),
    parametros_int: tuple = (),
    parametros_real: tuple = (),
    alarmas: tuple = (),
    software_parsers_implemented: bool = True,
) -> MagicMock:
    """Construye un mock de ``ExcelCache`` con los atributos esperados.

    El endpoint accede a ``cache.procesos``, ``cache.parametros_int``,
    ``cache.parametros_real``, ``cache.alarmas`` y
    ``cache.software_parsers_implemented``. El helper ``_extract_software_from_cache``
    hace ``dataclasses.asdict`` sobre cada elemento, así que los
    elementos deben ser dataclasses o similares con campos
    representables.

    Para tests simples, basta con pasar tuplas vacías. Para tests
    con datos, usar las dataclasses reales (``ProcesoPLC``,
    ``ParamIntPLC``, etc.) del módulo ``excel_cache`` del área.
    """
    cache = MagicMock()
    cache.procesos = procesos
    cache.parametros_int = parametros_int
    cache.parametros_real = parametros_real
    cache.alarmas = alarmas
    cache.software_parsers_implemented = software_parsers_implemented
    return cache


# ── Tests del endpoint Fase 6 ────────────────────────────────────────────


def test_state_dispositivos_devuelve_software_vacio_si_no_hay_cache(
    client: TestClient, state_clean: AppState
) -> None:
    """Sin upload previo: 4 arrays vacíos y flag ``false``.

    El operario aún no ha subido ningún Excel, así que
    ``state.excel_cache`` es ``None``. La SPA debe ver arrays
    vacíos y ``software_parsers_implemented=false`` para mostrar
    el banner ámbar.
    """
    # Sanity: el cache empieza vacío.
    assert state_clean.excel_cache is None

    r = client.get("/api/v1/state/dispositivos")
    assert r.status_code == 200
    body = r.json()

    assert body["ok"] is True
    assert body["procesos"] == []
    assert body["parametros_int"] == []
    assert body["parametros_real"] == []
    assert body["alarmas"] == []
    assert body["software_parsers_implemented"] is False


def test_state_dispositivos_devuelve_software_despues_de_upload(
    client: TestClient, state_clean: AppState
) -> None:
    """Con cache populado: 4 arrays con datos y flag ``true``.

    Mockeamos ``state.excel_cache`` con un MagicMock que tiene
    tuplas de 1 elemento de cada dominio. Como los elementos
    son MagicMock (no dataclasses reales), usamos un mock anidado
    con atributos para verificar que ``dataclasses.asdict`` se
    llama y produce un dict con los campos del DTO.
    """
    # Construimos 4 DTOs reales para verificar la serialización.
    from areas.alimentacion.domain.models.excel_cache import (
        AlarmaPLC,
        ParamIntPLC,
        ParamRealPLC,
        ProcesoPLC,
    )

    procesos = (
        ProcesoPLC(uid=1, nombre="Proceso 1", codigo="PR1",
                   preal=3, index_preal=0, pint=2, index_pint=0, alarmas=5),
    )
    parametros_int = (
        ParamIntPLC(uid="PI_1_001", numero="001", proceso="Proceso 1",
                    codigo="PR1", num_db=3001, producto="prod",
                    tipo="tipo", descripcion="desc PI",
                    comentario_db="", visibilidad="Si",
                    num_lista=0, txt_lista=""),
    )
    parametros_real = (
        ParamRealPLC(uid="PR_1_001", numero="001", proceso="Proceso 1",
                     codigo="PR1", num_db=3000, producto="prod",
                     tipo="tipo", descripcion="desc PR",
                     comentario_db="", visibilidad="Si",
                     num_lista=0, txt_lista=""),
    )
    alarmas = (
        AlarmaPLC(uid="AL_1_001", numero="001", proceso="Proceso 1",
                  num_db=5000, descripcion="desc ALM",
                  comentario_db=""),
    )

    state_clean.excel_cache = _make_mock_excel_cache(
        procesos=procesos,
        parametros_int=parametros_int,
        parametros_real=parametros_real,
        alarmas=alarmas,
        software_parsers_implemented=True,
    )

    r = client.get("/api/v1/state/dispositivos")
    assert r.status_code == 200
    body = r.json()

    assert body["ok"] is True
    assert body["software_parsers_implemented"] is True

    # Procesos.
    assert len(body["procesos"]) == 1
    assert body["procesos"][0]["uid"] == 1
    assert body["procesos"][0]["codigo"] == "PR1"
    assert body["procesos"][0]["nombre"] == "Proceso 1"
    assert body["procesos"][0]["preal"] == 3
    assert body["procesos"][0]["alarmas"] == 5

    # Parametros Int.
    assert len(body["parametros_int"]) == 1
    assert body["parametros_int"][0]["uid"] == "PI_1_001"
    assert body["parametros_int"][0]["num_db"] == 3001
    assert body["parametros_int"][0]["descripcion"] == "desc PI"

    # Parametros Real.
    assert len(body["parametros_real"]) == 1
    assert body["parametros_real"][0]["uid"] == "PR_1_001"
    assert body["parametros_real"][0]["num_db"] == 3000

    # Alarmas.
    assert len(body["alarmas"]) == 1
    assert body["alarmas"][0]["uid"] == "AL_1_001"
    assert body["alarmas"][0]["num_db"] == 5000
    assert body["alarmas"][0]["descripcion"] == "desc ALM"


def test_state_dispositivos_sigue_devolviendo_legacy(
    client: TestClient, state_clean: AppState
) -> None:
    """Back-compat: ``dispositivos`` y ``dimensiones`` mantienen la forma legacy.

    El endpoint de Fase 6 NO debe romper la forma legacy: las claves
    ``dispositivos`` (dict por tipo) y ``dimensiones`` (los 6
    ``num_disp_*``) siguen saliendo igual que antes del refactor.
    """
    # Estado vacío: igual que un operario que abre la SPA por
    # primera vez sin haber subido Excel.
    r = client.get("/api/v1/state/dispositivos")
    body = r.json()

    # ``dimensiones``: dict (vacío o con los 6 ``num_disp_*``).
    assert isinstance(body["dimensiones"], dict)
    # ``dispositivos``: dict (con los 6 tipos cuando hay cache,
    # vacío en estado degradado).
    assert isinstance(body["dispositivos"], dict)
    # ``ok`` y las 4 listas de software + el flag también.
    assert body["ok"] is True
    for k in ("procesos", "parametros_int", "parametros_real", "alarmas"):
        assert k in body, f"Falta la clave de software {k!r}"
        assert isinstance(body[k], list)
    assert "software_parsers_implemented" in body
    assert isinstance(body["software_parsers_implemented"], bool)


def test_state_dispositivos_response_es_json_serializable(
    client: TestClient, state_clean: AppState
) -> None:
    """El response completo es JSON-serializable (defensa contra schema drift)."""
    r = client.get("/api/v1/state/dispositivos")
    assert r.status_code == 200
    # ``json.dumps`` es el contrato definitivo de la API: si algo
    # del response NO se serializa, esto lanza ``TypeError`` y el
    # test falla, señalando drift del shape.
    payload = r.json()
    serialized = json.dumps(payload)
    assert isinstance(serialized, str)
    # Round-trip: re-parsear y verificar que las 4 keys siguen.
    reparsed = json.loads(serialized)
    assert set(reparsed.keys()) == {
        "ok", "dimensiones", "dispositivos",
        "procesos", "parametros_int", "parametros_real", "alarmas",
        "software_parsers_implemented",
    }


def test_state_dispositivos_dimensiones_none_devuelve_vacio(
    client: TestClient, state_clean: AppState
) -> None:
    """Defensiva: ``state.dimensiones`` ``None`` → ``{}`` en el response.

    Caso back-compat: un operario que abre la SPA sin haber subido
    Excel, o que se queda sin dimensiones tras un clear, debe ver
    ``dimensiones: {}`` (no un 500 por ``'NoneType' has no
    attribute 'to_api_dict'``). Ya estaba cubierto antes de Fase 6
    pero se re-verifica para confirmar que el cambio no rompió el
    modo degradado.
    """
    # Sanity: dimensiones es None.
    assert state_clean.dimensiones is None

    r = client.get("/api/v1/state/dispositivos")
    body = r.json()
    assert body["dimensiones"] == {}
    # Las 4 listas siguen siendo arrays vacíos y el flag false.
    assert body["procesos"] == []
    assert body["parametros_int"] == []
    assert body["parametros_real"] == []
    assert body["alarmas"] == []
    assert body["software_parsers_implemented"] is False


def test_state_dispositivos_cache_sin_flag_devuelve_false(
    client: TestClient, state_clean: AppState
) -> None:
    """Defensiva: cache sin atributo ``software_parsers_implemented`` → ``false``.

    Si un backend antiguo (sin Fase 5) aún deja un cache en
    ``state.excel_cache`` pero ese cache no tiene el flag
    (atributo ausente), el endpoint debe caer a ``False`` y NO
    explotar. Esto cubre el caso real de un upgrade de Fase 6
    antes de un upgrade de Fase 5.
    """
    # Mock que NO tiene ``software_parsers_implemented``.
    cache = MagicMock(spec=[])  # spec=[] → no atributos
    cache.procesos = ()
    cache.parametros_int = ()
    cache.parametros_real = ()
    cache.alarmas = ()
    # NO se setea ``software_parsers_implemented``.
    state_clean.excel_cache = cache

    r = client.get("/api/v1/state/dispositivos")
    body = r.json()
    # ``getattr(cache, 'software_parsers_implemented', False)`` → False.
    assert body["software_parsers_implemented"] is False
    # Los arrays están vacíos (tuplas vacías → []).
    assert body["procesos"] == []
    assert body["parametros_int"] == []
    assert body["parametros_real"] == []
    assert body["alarmas"] == []
