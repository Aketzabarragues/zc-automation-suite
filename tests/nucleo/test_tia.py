"""Tests del hilo de TIA: Job, transacciones, conexion y estado.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from zc_suite import tia
from zc_suite.tia import (
    FueraDelHiloError,
    OcupadoError,
    ServicioTIA,
    SinPortalError,
    transaccion,
)

RAIZ = Path(__file__).resolve().parents[2]


# ── dobles de test ─────────────────────────────────────────────────────────


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

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        self.llamadas.append("attach_portal")
        self.modos.append(portal_mode or "")
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        self.llamadas.append("open_portal")
        self.modos.append(portal_mode or "")
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        self.logging.append((path, console))


# ── fixture ────────────────────────────────────────────────────────────────


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


# ── encolado ───────────────────────────────────────────────────────────────


def test_lanzar_devuelve_el_job_id(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(lambda job: {"ok": True})

    assert isinstance(job_id, str)
    assert job_id
    _esperar_job(eventos, job_id)


def test_lanzar_ejecuta_la_funcion_con_sus_parametros(entorno: Any) -> None:
    servicio, _ts, eventos = entorno
    recibidos: dict[str, Any] = {}

    def trabajo(job: Any, valor: int) -> dict[str, Any]:
        recibidos["valor"] = valor
        recibidos["id"] = job.id
        return {"ok": True}

    job_id = servicio.lanzar(trabajo, valor=7)

    evento = _esperar_job(eventos, job_id)
    assert recibidos["valor"] == 7
    assert recibidos["id"] == job_id
    assert evento["estado"] == "ok"
    assert evento["resultado"] == {"ok": True}
    assert evento["error"] is None


def test_lanzar_con_trabajo_en_curso_lanza_ocupado(entorno: Any) -> None:
    servicio, _ts, eventos = entorno
    arranque = threading.Event()
    seguir = threading.Event()

    def trabajo_lento(job: Any) -> dict[str, Any]:
        arranque.set()
        seguir.wait(5.0)
        return {}

    job_id = servicio.lanzar(trabajo_lento)
    assert arranque.wait(5.0)

    with pytest.raises(OcupadoError):
        servicio.lanzar(lambda job: {})

    seguir.set()
    _esperar_job(eventos, job_id)


def test_lanzar_libera_el_servicio_al_terminar(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(lambda job: {})
    _esperar_job(eventos, job_id)

    assert servicio.ocupado is False
    assert servicio.lanzar(lambda job: {})  # no lanza


# ── Job: pasos y progreso ──────────────────────────────────────────────────


def test_empezar_declara_todos_los_pasos(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(_trabajo_con_pasos)
    _esperar_job(eventos, job_id)

    avances = _eventos_de(eventos, "progress")
    inicial = avances[0]
    assert inicial["active"] is True
    assert inicial["total"] == 2
    assert inicial["current"] == 0
    assert inicial["percent"] == 0
    assert [etapa["id"] for etapa in inicial["stages"]] == ["exportar", "comparar"]
    assert all(etapa["status"] == "pending" for etapa in inicial["stages"])


def test_los_pasos_avanzan_de_running_a_done(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(_trabajo_con_pasos)
    _esperar_job(eventos, job_id)

    estados = [
        (etapa["id"], etapa["status"])
        for carga in _eventos_de(eventos, "progress")
        for etapa in carga["stages"]
    ]
    assert ("exportar", "running") in estados
    assert ("exportar", "done") in estados
    assert ("comparar", "done") in estados


def test_el_detalle_del_paso_se_publica(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(_trabajo_con_pasos)
    _esperar_job(eventos, job_id)

    detalles = [
        etapa["detail"]
        for carga in _eventos_de(eventos, "progress")
        for etapa in carga["stages"]
        if etapa["id"] == "exportar"
    ]
    assert "3 bloques" in detalles


def test_el_progreso_final_cierra_el_trabajo(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(_trabajo_con_pasos)
    _esperar_job(eventos, job_id)

    finales = [carga for carga in _eventos_de(eventos, "progress") if carga["active"] is False]
    assert finales
    assert finales[-1]["finished_at"] is not None
    assert finales[-1]["current"] == 2
    assert finales[-1]["percent"] == 100


def test_un_paso_no_declarado_falla(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("otro"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "otro" in str(evento["error"])


def test_la_excepcion_de_un_paso_marca_error_y_relanza(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("reventon")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "reventon" in str(evento["error"])
    etapas = evento["resultado"] if evento["resultado"] else None
    assert etapas is None
    estados = [
        etapa["status"]
        for carga in _eventos_de(eventos, "progress")
        for etapa in carga["stages"]
        if etapa["id"] == "uno"
    ]
    assert "error" in estados


def test_la_cancelacion_se_respeta_entre_pasos(entorno: Any) -> None:
    servicio, _ts, eventos = entorno
    arranque = threading.Event()

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno", "dos"])
        with job.paso("uno"):
            arranque.set()
            job.cancelar()
        with job.paso("dos"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert arranque.wait(5.0)
    assert evento["estado"] == "cancelado"


def test_el_log_del_trabajo_se_publica(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        job.log("mensaje de operario")
        with job.paso("uno"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    _esperar_job(eventos, job_id)

    logs = _eventos_de(eventos, "log")
    assert any(carga["mensaje"] == "mensaje de operario" for carga in logs)


# ── transacciones ──────────────────────────────────────────────────────────


def test_transaccion_confirma_con_rollback_false(entorno: Any) -> None:
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    _esperar_job(eventos, job_id)

    transacciones = ts.portal.proyecto.transacciones
    assert ("start", "Importar") in transacciones
    assert ("end", False) in transacciones


def test_transaccion_hace_rollback_si_falla(entorno: Any) -> None:
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert ("end", True) in ts.portal.proyecto.transacciones
    assert ("end", False) not in ts.portal.proyecto.transacciones


def test_transaccion_informa_si_el_rollback_falla(entorno: Any) -> None:
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)
    ts.portal.proyecto.fallar_rollback = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "rollback" in str(evento["error"]).lower()


def test_transaccion_sin_portal_falla(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "conexion" in str(evento["error"]).lower()


# ── conexion ───────────────────────────────────────────────────────────────


def test_conectar_engancha_el_portal_y_silencia_el_log(entorno: Any) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas == ["attach_portal"]
    assert ts.logging
    assert ts.logging[0][1] is False
    assert servicio.conectado is True


def test_conectar_en_modo_open_abre_una_instancia_nueva(entorno: Any) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar, modo="open")
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas == ["open_portal"]


def test_desconectar_libera_el_portal(entorno: Any) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, job_id)
    job_id = servicio.lanzar(tia.desconectar)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.portal.desenganchado is True
    assert servicio.conectado is False


def test_el_portal_inexistente_lanza_sin_portal(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    with pytest.raises(SinPortalError):
        _ = servicio.portal


def test_un_modo_de_portal_invalido_falla(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar, modo="inventado")
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"


# ── estado ─────────────────────────────────────────────────────────────────


def test_el_estado_no_cambia_por_un_fallo_de_trabajo(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, job_id)

    def trabajo_fallido(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("fallo de negocio")
        return {}

    job_id = servicio.lanzar(trabajo_fallido)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    estado = servicio.estado()
    assert estado["conectado"] is True
    assert estado["ultimo_error"] is not None


def test_el_estado_detecta_el_portal_caido(entorno: Any) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, job_id)

    ts.portal.vivo = False
    job_id = servicio.lanzar(lambda job: {})
    _esperar_job(eventos, job_id)

    assert servicio.estado()["conectado"] is False


def test_el_estado_no_toca_el_portal(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    servicio.estado()
    servicio.estado()

    assert servicio.estado()["conectado"] is False


# ── robustez ───────────────────────────────────────────────────────────────


def test_un_publicador_roto_no_tumba_el_trabajo(entorno: Any) -> None:
    ts = TsFalso()
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: (_ for _ in ()).throw(RuntimeError("bus roto")),
        cargador=lambda: ts,
    )
    try:
        job_id = servicio.lanzar(lambda job: {"ok": True})
        limite = time.monotonic() + 5.0
        while servicio.ocupado and time.monotonic() < limite:
            time.sleep(0.005)
        assert servicio.ocupado is False
        assert job_id
    finally:
        servicio.parar()


def test_el_sdk_de_siemens_no_se_importa_fuera_del_hilo(entorno: Any) -> None:
    """El wrapper de Siemens no se importa al importar el modulo del nucleo."""
    codigo = (
        "import sys; import zc_suite.tia; "
        "print('siemens_tia_scripting' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        cwd=RAIZ,
        env={"PYTHONPATH": str(RAIZ / "backend"), "PATH": ""},
        check=True,
    )
    assert resultado.stdout.strip() == "False"


# ── cancelacion de un trabajo en ejecucion ─────────────────────────────────


def test_cancelar_un_trabajo_en_ejecucion(entorno: Any) -> None:
    """Cancelar durante el primer paso impide que se ejecute el segundo."""
    servicio, _ts, eventos = entorno
    en_el_primer_paso = threading.Event()
    continuar = threading.Event()
    pasos_ejecutados: list[str] = []

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno", "dos"])
        with job.paso("uno"):
            en_el_primer_paso.set()
            continuar.wait(5.0)
        with job.paso("dos"):
            pasos_ejecutados.append("dos")
        return {}

    job_id = servicio.lanzar(trabajo)
    assert en_el_primer_paso.wait(5.0)

    assert servicio.cancelar(job_id) is True
    continuar.set()
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "cancelado"
    assert pasos_ejecutados == []


def test_cancelar_un_trabajo_inexistente_devuelve_false(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    assert servicio.cancelar("no-existe") is False


# ── fallo del commit de la transaccion ─────────────────────────────────────


def test_transaccion_con_commit_fallido_hace_rollback(entorno: Any) -> None:
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "commit" in str(evento["error"]).lower()
    assert ("end", True) in ts.portal.proyecto.transacciones


def test_transaccion_con_commit_fallido_y_rollback_fallido(entorno: Any) -> None:
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True
    ts.portal.proyecto.fallar_rollback = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    error = str(evento["error"]).lower()
    assert evento["estado"] == "error"
    assert "commit" in error
    assert "rollback" in error


def test_el_mensaje_distingue_operacion_de_commit(entorno: Any) -> None:
    """El fallo de la operacion y el del commit se describen distinto."""
    servicio, ts, eventos = entorno
    _conectar(servicio, eventos)

    def trabajo_que_falla(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo_que_falla)
    evento_operacion = _esperar_job(eventos, job_id)
    error_operacion = str(evento_operacion["error"]).lower()
    assert evento_operacion["estado"] == "error"
    assert "operacion" in error_operacion
    assert "commit" not in error_operacion
    assert "rollback ejecutado" in error_operacion

    ts.portal.proyecto.fallar_commit = True

    def trabajo_con_commit(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo_con_commit)
    evento_commit = _esperar_job(eventos, job_id)
    error_commit = str(evento_commit["error"]).lower()
    assert evento_commit["estado"] == "error"
    assert "commit" in error_commit
    assert "fallo de la operacion" not in error_commit


# ── deteccion de desconexion en reposo ─────────────────────────────────────


def test_el_portal_caido_se_detecta_en_reposo() -> None:
    """Sin lanzar trabajos, el hilo de TIA detecta que el portal ha muerto."""
    ts = TsFalso()
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: ts,
        intervalo_ping=0.05,
    )
    try:
        job_id = servicio.lanzar(tia.conectar)
        _esperar_job(eventos, job_id)
        assert servicio.conectado is True

        ts.portal.vivo = False

        limite = time.monotonic() + 5.0
        while servicio.conectado and time.monotonic() < limite:
            time.sleep(0.01)

        assert servicio.conectado is False
        estados = [carga for tipo, carga in eventos if tipo == "tia"]
        assert estados[-1]["conectado"] is False
    finally:
        servicio.parar()


# ── ultimo_error ───────────────────────────────────────────────────────────


def test_el_ultimo_error_se_limpia_al_empezar_un_trabajo(entorno: Any) -> None:
    servicio, _ts, eventos = entorno

    def trabajo_fallido(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("fallo de negocio")
        return {}

    job_id = servicio.lanzar(trabajo_fallido)
    _esperar_job(eventos, job_id)
    assert servicio.estado()["ultimo_error"] is not None

    job_id = servicio.lanzar(lambda job: {})
    _esperar_job(eventos, job_id)

    assert servicio.estado()["ultimo_error"] is None


# ── el portal solo se usa desde el hilo de TIA ─────────────────────────────


def test_el_portal_no_se_lee_desde_otro_hilo(entorno: Any) -> None:
    servicio, _ts, eventos = entorno
    _conectar(servicio, eventos)

    with pytest.raises(FueraDelHiloError):
        _ = servicio.portal


def test_el_portal_se_lee_dentro_del_hilo_de_tia(entorno: Any) -> None:
    servicio, _ts, eventos = entorno
    _conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["leer"])
        with job.paso("leer"):
            pid = job.tia.portal.get_process_id()
        return {"pid": pid}

    job_id = servicio.lanzar(trabajo)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"] == {"pid": 4242}


# ── ayudas ─────────────────────────────────────────────────────────────────


def _trabajo_con_pasos(job: Any) -> dict[str, Any]:
    job.empezar("Trabajo de prueba", ["exportar", "comparar"])
    with job.paso("exportar") as paso:
        paso["detail"] = "3 bloques"
    with job.paso("comparar"):
        pass
    return {"cambios": 0}
