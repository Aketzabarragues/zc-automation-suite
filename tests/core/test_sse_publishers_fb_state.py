"""Tests del publisher SSE ``fb_state`` (``make_fb_state_publisher``).

Cubre:

- El payload ``fb_state`` incluye siempre la clave ``job_id``, con el
  identificador del trabajo del OB1 en curso (``engine.current_job_for``).
- Sin job en curso, ``job_id`` es ``None`` y el resto del payload
  permanece intacto.
- Un fallo al resolver el job_id (engine que no soporta la consulta,
  o consulta que lanza) no tumb la retransmision del estado del FB.
- ``result`` viaja serializado via ``to_jsonable`` y ``error_msg``
  se propaga.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from core.runtime.sse.sse_event_bus_sync import EventBusSync
from core.runtime.sse.sse_publishers import make_fb_state_publisher


@dataclass(frozen=True)
class _FakeJob:
    """Job del dispatcher OB1 (subset de ``core.composition.plc_engine.Job``)."""

    job_id: str
    fb_name: str
    status: str = "running"


def _make_fb(
    nStep: int = 0,
    result: Any = None,
    error_msg: str | None = None,
    terminal: bool = False,
) -> MagicMock:
    """FB stub con los atributos que lee el publisher."""
    fb = MagicMock()
    fb.nStep = nStep
    fb.result = result
    fb.error_msg = error_msg
    fb.is_terminal.return_value = terminal
    return fb


def _make_engine(job: _FakeJob | None = None) -> MagicMock:
    """Engine stub: ``current_job_for`` devuelve el job dado."""
    engine = MagicMock()
    engine.current_job_for.return_value = job
    return engine


def _published(bus: MagicMock) -> dict[str, Any]:
    """Ultimo dict publicado en el bus."""
    bus.publish.assert_called_once()
    return bus.publish.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────
# job_id
# ─────────────────────────────────────────────────────────────────────


def test_fb_state_incluye_el_job_id_del_job_en_curso() -> None:
    """El payload lleva el job_id del job en curso de ese FB."""
    bus = MagicMock()
    engine = _make_engine(_FakeJob(job_id="abc123", fb_name="excel_cargar"))
    publish = make_fb_state_publisher(bus, engine)

    publish("excel_cargar", _make_fb(nStep=3))

    evt = _published(bus)
    assert evt["job_id"] == "abc123"
    engine.current_job_for.assert_called_once_with("excel_cargar")


def test_fb_state_lleva_job_id_none_sin_job_en_curso() -> None:
    """Sin job en curso: ``job_id`` es None y el resto sigue intacto."""
    bus = MagicMock()
    engine = _make_engine(None)
    publish = make_fb_state_publisher(bus, engine)

    publish("excel_cargar", _make_fb(nStep=7, result="ok", terminal=True))

    evt = _published(bus)
    assert evt["type"] == "fb_state"
    assert evt["name"] == "excel_cargar"
    assert evt["nStep"] == 7
    assert evt["is_terminal"] is True
    assert evt["result"] == "ok"
    assert evt["error_msg"] is None
    assert evt["job_id"] is None


def test_fb_state_publica_aunque_el_job_no_se_pueda_resolver() -> None:
    """Si ``current_job_for`` lanza, el evento se publica con job_id=None."""
    bus = MagicMock()
    engine = MagicMock()
    engine.current_job_for.side_effect = RuntimeError("boom")
    publish = make_fb_state_publisher(bus, engine)

    publish("excel_cargar", _make_fb(nStep=2))

    evt = _published(bus)
    assert evt["job_id"] is None
    assert evt["name"] == "excel_cargar"
    assert evt["nStep"] == 2


def test_fb_state_publica_aunque_el_engine_no_tenga_current_job_for() -> None:
    """Engine sin ``current_job_for``: no revienta, job_id=None."""
    for engine in (object(), MagicMock(spec=[])):
        bus = MagicMock()
        publish = make_fb_state_publisher(bus, engine)

        publish("excel_cargar", _make_fb(nStep=1))

        evt = _published(bus)
        assert evt["job_id"] is None
        assert evt["type"] == "fb_state"


# ─────────────────────────────────────────────────────────────────────
# result / error_msg
# ─────────────────────────────────────────────────────────────────────


def test_fb_state_incluye_el_result_del_fb() -> None:
    """``result`` viaja serializado y ``error_msg`` se propaga."""
    @dataclass(frozen=True)
    class _Payload:
        ok: bool
        n: int

    bus = MagicMock()
    engine = _make_engine(_FakeJob(job_id="job-9", fb_name="excel_cargar"))
    publish = make_fb_state_publisher(bus, engine)

    publish(
        "excel_cargar",
        _make_fb(
            nStep=4,
            result=_Payload(ok=True, n=2),
            error_msg="fallo parcial",
            terminal=True,
        ),
    )

    evt = _published(bus)
    assert evt["result"] == {"ok": True, "n": 2}
    assert evt["error_msg"] == "fallo parcial"
    assert evt["job_id"] == "job-9"


# ─────────────────────────────────────────────────────────────────────
# Integracion con el bus real
# ─────────────────────────────────────────────────────────────────────


def test_fb_state_llega_al_suscriptor_del_bus_real() -> None:
    """Round-trip: el evento ``fb_state`` con job_id llega al suscriptor."""
    bus = EventBusSync()
    engine = _make_engine(_FakeJob(job_id="deadbeef", fb_name="excel_cargar"))
    publish = make_fb_state_publisher(bus, engine)

    q = bus.subscribe()
    publish("excel_cargar", _make_fb(nStep=1, terminal=True))

    evt = q.get_nowait()
    assert evt["type"] == "fb_state"
    assert evt["job_id"] == "deadbeef"
    assert evt["is_terminal"] is True
