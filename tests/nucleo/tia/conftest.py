"""Los dobles de TIA, las ayudas y las fixtures del subsistema TIA.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.servicio import ServicioTIA


class ProyectoFalso:
    """Doble de test del ``Project`` de TIA."""

    def __init__(self) -> None:
        self.transacciones: list[tuple[str, Any]] = []
        self.fallar_rollback = False
        self.fallar_commit = False

    def start_transaction(self, undo_text: str, dialog_text: str) -> None:
        self.transacciones.append(("start", undo_text))
        self.transacciones.append(("dialog", dialog_text))

    def end_transaction(self, rollback: bool | None = None) -> None:
        self.transacciones.append(("end", rollback))
        if rollback and self.fallar_rollback:
            raise RuntimeError("El rollback no se pudo completar.")
        if not rollback and self.fallar_commit:
            raise RuntimeError("El commit no se pudo confirmar.")


class _Bundle:
    """Doble de un bundle de producto instalado."""

    def __init__(self, titulo: str) -> None:
        self._titulo = titulo

    def get_title(self) -> str:
        return self._titulo


class PortalFalso:
    """Doble de test del ``Portal`` de TIA."""
    def __init__(self) -> None:
        self.proyecto = ProyectoFalso()
        self.pid = 4242
        self.vivo = True
        self.desenganchado = False
        self.cerrado = False

    def get_process_id(self) -> int:
        if not self.vivo:
            raise RuntimeError("El portal ya no responde.")
        return self.pid

    def get_project(self) -> ProyectoFalso:
        return self.proyecto

    def detach(self) -> None:
        self.desenganchado = True

    def close_portal(self) -> None:
        self.cerrado = True


class TsFalso:
    """Doble de test del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier_interfaz"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self) -> None:
        self.portal = PortalFalso()
        self.llamadas: list[str] = []
        self.modos: list[str] = []
        self.logging: list[tuple[str, bool]] = []
        self.error_attach: str | None = None
        self.version_instalada = ""

    def get_installed_bundles(self) -> list[Any]:
        if not self.version_instalada:
            return []
        return [_Bundle(f"Siemens TIA Portal {self.version_instalada}")]

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        self.llamadas.append("attach_portal")
        self.modos.append(portal_mode or "")
        if self.error_attach is not None:
            raise ValueError(self.error_attach)
        # Cada enganche devuelve un portal nuevo, como en el SDK real.
        self.portal = PortalFalso()
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        self.llamadas.append("open_portal")
        self.modos.append(portal_mode or "")
        self.portal = PortalFalso()
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        self.logging.append((path, console))


class _HiloMuerto:
    """Doble de un hilo de TIA que ha muerto."""

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        pass

    def start(self) -> None:
        pass


def _trabajo_con_pasos(job: Any) -> dict[str, Any]:
    job.empezar("Trabajo de prueba", ["exportar", "comparar"])
    with job.paso("exportar") as paso:
        paso["detail"] = "3 bloques"
    with job.paso("comparar"):
        pass
    return {"cambios": 0}


def _esperar_job(eventos: list[tuple[str, dict[str, Any]]], job_id: str) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in list(eventos):
            if tipo == "job" and carga["job"] == job_id:
                return carga
        time.sleep(0.005)
    raise AssertionError(f"El trabajo {job_id} no termino.")


def _eventos_de(eventos: list[tuple[str, dict[str, Any]]], tipo: str) -> list[dict[str, Any]]:
    return [carga for t, carga in eventos if t == tipo]


def _conectar(servicio: Any, eventos: list[tuple[str, dict[str, Any]]]) -> None:
    """Conecta el portal falso y espera a que termine."""
    job_id = servicio.lanzar(tia.conectar)
    evento = _esperar_job(eventos, job_id)
    assert evento["estado"] == "ok"


def _servicio_con_ping(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Servicio con ping rapido y modulo falso, para las pruebas del hilo."""
    ts = TsFalso()
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: ts,
        intervalo_ping=0.05,
    )
    servicio._hilo_para_test = ts  # type: ignore[attr-defined]
    servicio._eventos_para_test = eventos  # type: ignore[attr-defined]
    return servicio


@pytest.fixture
def entorno() -> Any:
    """Servicio con modulo falso, recolector de eventos y limpieza."""
    ts = TsFalso()
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: ts,
    )
    yield servicio, ts, eventos
    servicio.parar()




@pytest.fixture
def esperar_job() -> Callable[..., Any]:
    """Espera al evento de fin de un trabajo."""
    return _esperar_job


@pytest.fixture
def eventos_de() -> Callable[..., Any]:
    """Los eventos de un tipo dado."""
    return _eventos_de


@pytest.fixture
def conectar() -> Callable[..., Any]:
    """Conecta el portal falso y espera a que termine."""
    return _conectar


@pytest.fixture
def trabajo_con_pasos() -> Callable[..., Any]:
    """Un trabajo que declara dos pasos."""
    return _trabajo_con_pasos


@pytest.fixture
def hilo_muerto() -> type:
    """El doble de un hilo de TIA que ha muerto."""
    return _HiloMuerto


@pytest.fixture
def servicio_con_ping() -> Callable[..., Any]:
    """Un servicio con ping rapido, para las pruebas del hilo."""
    return _servicio_con_ping


@pytest.fixture
def ts_falso() -> type:
    """El doble del modulo ``siemens_tia_scripting``."""
    return TsFalso
