"""El hilo de TIA: encolado, conexion, estado y robustez.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios (los define ``conftest.py``).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.errores import (
    FueraDelHiloError,
    OcupadoError,
    SinPortalError,
)
from zc_suite.nucleo.tia.servicio import ServicioTIA, version_tia_instalada

RAIZ = Path(__file__).resolve().parents[3]


def test_lanzar_devuelve_el_job_id(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(lambda job: {"ok": True})

    assert isinstance(job_id, str)
    assert job_id
    esperar_job(eventos, job_id)


def test_lanzar_ejecuta_la_funcion_con_sus_parametros(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno
    recibidos: dict[str, Any] = {}

    def trabajo(job: Any, valor: int) -> dict[str, Any]:
        recibidos["valor"] = valor
        recibidos["id"] = job.id
        return {"ok": True}

    job_id = servicio.lanzar(trabajo, valor=7)

    evento = esperar_job(eventos, job_id)
    assert recibidos["valor"] == 7
    assert recibidos["id"] == job_id
    assert evento["estado"] == "ok"
    assert evento["resultado"] == {"ok": True}
    assert evento["error"] is None


def test_lanzar_con_trabajo_en_curso_lanza_ocupado(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
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
    esperar_job(eventos, job_id)


def test_lanzar_libera_el_servicio_al_terminar(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(lambda job: {})
    esperar_job(eventos, job_id)

    assert servicio.ocupado is False
    assert servicio.lanzar(lambda job: {})  # no lanza


def test_se_detecta_la_version_de_tia_instalada() -> None:

    class Bundle:
        def __init__(self, titulo: str) -> None:
            self._titulo = titulo

        def get_title(self) -> str:
            return self._titulo

    class Ts:
        @staticmethod
        def get_installed_bundles() -> list[Bundle]:
            return [
                Bundle("S7-PLCSIM Advanced V5.0 Upd1"),
                Bundle("Siemens TIA Portal V18.0 Upd5"),
                Bundle("SIMATIC TIA Portal V18 WinCC Prof Ed"),
            ]

    assert version_tia_instalada(Ts()) == "V18.0"


def test_se_queda_con_la_version_mayor() -> None:

    class Bundle:
        def __init__(self, titulo: str) -> None:
            self._titulo = titulo

        def get_title(self) -> str:
            return self._titulo

    class Ts:
        @staticmethod
        def get_installed_bundles() -> list[Bundle]:
            return [
                Bundle("Siemens TIA Portal V18.0 Upd5"),
                Bundle("Siemens TIA Portal V21.1"),
            ]

    assert version_tia_instalada(Ts()) == "V21.1"


def test_sin_tia_instalada_la_version_es_vacia() -> None:

    class Ts:
        @staticmethod
        def get_installed_bundles() -> list[Any]:
            return []

    assert version_tia_instalada(Ts()) == ""


def test_el_estado_incluye_la_version_de_tia(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    assert servicio.estado()["version_tia"] == ""


def test_conectar_devuelve_la_version_de_tia(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, ts, eventos = entorno
    ts.version_instalada = "V21.1"

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"]["version_tia"] == "V21.1"
    assert servicio.estado()["version_tia"] == "V21.1"


def test_conectar_engancha_el_portal_y_silencia_el_log(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas == ["attach_portal"]
    assert ts.logging
    assert ts.logging[0][1] is False
    assert servicio.conectado is True


def test_conectar_en_modo_open_abre_una_instancia_nueva(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar, modo="open")
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas == ["open_portal"]


def test_desconectar_libera_el_portal(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)
    job_id = servicio.lanzar(tia.desconectar)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.portal.desenganchado is True
    assert servicio.conectado is False


def test_el_portal_inexistente_lanza_sin_portal(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    with pytest.raises(SinPortalError):
        _ = servicio.portal


def test_desconectar_avisa_de_que_tia_se_perdio(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    """Al desconectar se avisa: la sesion invalida sus escaneos."""
    servicio, _ts, eventos = entorno
    perdidos: list[str] = []
    servicio.enganchar_perdida_tia(lambda: perdidos.append("tia"))

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)
    job_id = servicio.lanzar(tia.desconectar)
    esperar_job(eventos, job_id)

    assert perdidos == ["tia"]


def test_perder_el_portal_avisa_de_que_tia_se_perdio(entorno: Any) -> None:
    """Perder el portal tambien invalida los escaneos."""
    servicio, _ts, _eventos = entorno
    perdidos: list[str] = []
    servicio.enganchar_perdida_tia(lambda: perdidos.append("tia"))

    servicio._perder_portal("se ha perdido el portal")

    assert perdidos == ["tia"]


def test_un_aviso_roto_no_tumba_el_hilo(entorno: Any) -> None:
    """Si el aviso falla, el hilo de TIA sigue en pie."""
    servicio, _ts, _eventos = entorno

    def fallar() -> None:
        raise RuntimeError("fallo al invalidar")

    servicio.enganchar_perdida_tia(fallar)

    servicio._perder_portal("se ha perdido el portal")

    assert servicio.conectado is False


def test_un_modo_de_portal_invalido_falla(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar, modo="inventado")
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"


def test_el_estado_no_cambia_por_un_fallo_de_trabajo(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    def trabajo_fallido(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("fallo de negocio")
        return {}

    job_id = servicio.lanzar(trabajo_fallido)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    estado = servicio.estado()
    assert estado["conectado"] is True
    assert estado["ultimo_error"] is not None


def test_el_estado_detecta_el_portal_caido(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    ts.portal.vivo = False
    job_id = servicio.lanzar(lambda job: {})
    esperar_job(eventos, job_id)

    assert servicio.estado()["conectado"] is False


def test_el_estado_no_toca_el_portal(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    servicio.estado()
    servicio.estado()

    assert servicio.estado()["conectado"] is False


def test_un_publicador_roto_no_tumba_el_trabajo(entorno: Any, ts_falso: type) -> None:
    ts = ts_falso()
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
        "import sys; import zc_suite.nucleo.tia.servicio; "
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


def test_cancelar_un_trabajo_en_ejecucion(entorno: Any, esperar_job: Callable[..., Any]) -> None:
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
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "cancelado"
    assert pasos_ejecutados == []


def test_cancelar_un_trabajo_inexistente_devuelve_false(entorno: Any) -> None:
    servicio, _ts, _eventos = entorno

    assert servicio.cancelar("no-existe") is False


def test_el_portal_caido_se_detecta_en_reposo(
    esperar_job: Callable[..., Any],
    ts_falso: type,
) -> None:
    """Sin lanzar trabajos, el hilo de TIA detecta que el portal ha muerto."""
    ts = ts_falso()
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: ts,
        intervalo_ping=0.05,
    )
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)
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


def test_el_ultimo_error_se_limpia_al_empezar_un_trabajo(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo_fallido(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("fallo de negocio")
        return {}

    job_id = servicio.lanzar(trabajo_fallido)
    esperar_job(eventos, job_id)
    assert servicio.estado()["ultimo_error"] is not None

    job_id = servicio.lanzar(lambda job: {})
    esperar_job(eventos, job_id)

    assert servicio.estado()["ultimo_error"] is None


def test_el_portal_no_se_lee_desde_otro_hilo(entorno: Any, conectar: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno
    conectar(servicio, eventos)

    with pytest.raises(FueraDelHiloError):
        _ = servicio.portal


def test_el_portal_se_lee_dentro_del_hilo_de_tia(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["leer"])
        with job.paso("leer"):
            pid = job.tia.portal.get_process_id()
        return {"pid": pid}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"] == {"pid": 4242}


def test_un_trabajo_con_resultado_no_serializable_termina_en_error(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    """Un Path en el resultado no puede viajar al navegador."""
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            pass
        return Path("resultado.txt")

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"])
    assert evento["estado"] == "error"
    assert "no es serializable a JSON" in error
    assert "Path" in error
    assert "Devuelve tipos primitivos" in error
    assert evento["resultado"] is None


def test_un_trabajo_con_resultado_serializable_termina_en_ok(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        return {"cambios": 3, "ok": True}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"] == {"cambios": 3, "ok": True}


def test_el_aviso_de_tia_cerrado_no_enseña_el_error_del_sdk(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    esperar_job: Callable[..., Any],
    servicio_con_ping: Callable[..., Any],
) -> None:
    """El aviso es para el operario; el error del SDK se queda en el log."""
    servicio = servicio_con_ping(monkeypatch)
    eventos = servicio._eventos_para_test  # type: ignore[attr-defined]
    ts = servicio._hilo_para_test  # type: ignore[attr-defined]
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)
        assert servicio.conectado is True

        ts.portal.vivo = False
        with caplog.at_level(logging.WARNING):
            limite = time.monotonic() + 5.0
            while servicio.conectado and time.monotonic() < limite:
                time.sleep(0.01)

        assert servicio.conectado is False
        estados = [carga for tipo, carga in eventos if tipo == "tia"]
        assert estados[-1]["ultimo_error"] == "TIA Portal se ha cerrado o no responde"
        assert "exception set" not in estados[-1]["ultimo_error"]
        # El detalle tecnico, solo en el log.
        assert any(
            "El portal de TIA ya no responde" in registro.getMessage()
            for registro in caplog.records
        )
    finally:
        servicio.parar()


def test_el_aviso_de_tia_cerrado_tambien_llega_a_la_consola(
    monkeypatch: pytest.MonkeyPatch,
    esperar_job: Callable[..., Any],
    servicio_con_ping: Callable[..., Any],
) -> None:
    """El aviso sale como linea de log en la consola de la SPA."""
    servicio = servicio_con_ping(monkeypatch)
    eventos = servicio._eventos_para_test  # type: ignore[attr-defined]
    ts = servicio._hilo_para_test  # type: ignore[attr-defined]
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)

        ts.portal.vivo = False
        limite = time.monotonic() + 5.0
        while servicio.conectado and time.monotonic() < limite:
            time.sleep(0.01)

        lineas = [
            carga["mensaje"] for tipo, carga in eventos if tipo == "log"
        ]
        assert "TIA Portal se ha cerrado o no responde" in lineas
    finally:
        servicio.parar()


def test_el_hilo_aguanta_un_wait_que_falla(
    monkeypatch: pytest.MonkeyPatch,
    esperar_job: Callable[..., Any],
    servicio_con_ping: Callable[..., Any],
) -> None:
    """Un error que salta en el wait no puede tumbar el hilo."""
    servicio = servicio_con_ping(monkeypatch)
    eventos = servicio._eventos_para_test  # type: ignore[attr-defined]
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)
        assert servicio.conectado is True

        original = servicio._hay_trabajo.wait
        llamadas = {"n": 0}

        def wait_roto(timeout: float | None = None) -> bool:
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise SystemError("El wait ha reventado.")
            return original(timeout)

        monkeypatch.setattr(servicio._hay_trabajo, "wait", wait_roto)

        limite = time.monotonic() + 5.0
        while servicio.conectado and time.monotonic() < limite:
            time.sleep(0.01)

        assert servicio.conectado is False
        assert servicio._hilo_vivo() is True
        estados = [carga for tipo, carga in eventos if tipo == "tia"]
        assert estados[-1]["conectado"] is False
    finally:
        servicio.parar()


def test_el_hilo_aguanta_un_verificar_conexion_que_falla(
    monkeypatch: pytest.MonkeyPatch,
    esperar_job: Callable[..., Any],
    servicio_con_ping: Callable[..., Any],
) -> None:
    """Un fallo dentro de la comprobacion de vida no tumba el hilo."""
    servicio = servicio_con_ping(monkeypatch)
    eventos = servicio._eventos_para_test  # type: ignore[attr-defined]
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)

        def verificar_roto() -> None:
            raise SystemError("La verificacion ha reventado.")

        monkeypatch.setattr(servicio, "_verificar_conexion", verificar_roto)

        limite = time.monotonic() + 5.0
        while servicio.conectado and time.monotonic() < limite:
            time.sleep(0.01)

        assert servicio.conectado is False
        assert servicio._hilo_vivo() is True
    finally:
        servicio.parar()


def test_el_hilo_sigue_vivo_despues_de_un_fallo(
    monkeypatch: pytest.MonkeyPatch,
    esperar_job: Callable[..., Any],
    servicio_con_ping: Callable[..., Any],
) -> None:
    """Despues del fallo, el hilo sigue aceptando trabajos."""
    servicio = servicio_con_ping(monkeypatch)
    eventos = servicio._eventos_para_test  # type: ignore[attr-defined]
    try:
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)

        original = servicio._hay_trabajo.wait
        llamadas = {"n": 0}

        def wait_roto(timeout: float | None = None) -> bool:
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise SystemError("El wait ha reventado.")
            return original(timeout)

        monkeypatch.setattr(servicio._hay_trabajo, "wait", wait_roto)

        limite = time.monotonic() + 5.0
        while servicio.conectado and time.monotonic() < limite:
            time.sleep(0.01)

        job_id = servicio.lanzar(lambda job: {"ok": True})
        evento = esperar_job(eventos, job_id)
        assert evento["estado"] == "ok"
    finally:
        servicio.parar()


def test_el_estado_dice_desconectado_si_el_hilo_ha_muerto(
    entorno: Any,
    esperar_job: Callable[..., Any],
    hilo_muerto: type,
) -> None:
    servicio, _ts, _eventos = entorno
    job_id = servicio.lanzar(tia.conectar)
    esperar_job(_eventos, job_id)
    assert servicio.conectado is True

    servicio._hilo = hilo_muerto()

    assert servicio.estado()["conectado"] is False


def test_lanzar_reinicia_el_hilo_muerto_y_lo_avisa(
    entorno: Any,
    esperar_job: Callable[..., Any],
    hilo_muerto: type,
) -> None:
    servicio, _ts, eventos = entorno
    servicio._hilo = hilo_muerto()

    job_id = servicio.lanzar(lambda job: {"ok": True})

    evento = esperar_job(eventos, job_id)
    assert evento["estado"] == "ok"
    estados = [carga for tipo, carga in eventos if tipo == "tia"]
    assert any(
        carga.get("ultimo_error") == "El hilo de TIA se reinició tras un fallo"
        for carga in estados
    )


def test_lanzar_no_se_queda_ocupado_si_el_hilo_ha_muerto(
    entorno: Any,
    esperar_job: Callable[..., Any],
    hilo_muerto: type,
) -> None:
    """El trabajo perdido no puede bloquear la app para siempre."""
    servicio, _ts, eventos = entorno
    servicio._hilo = hilo_muerto()

    servicio.lanzar(lambda job: {})
    job_id = servicio.lanzar(lambda job: {})

    assert esperar_job(eventos, job_id)["estado"] == "ok"


def test_abrir_portal_descarta_un_portal_muerto(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)
    portal_muerto = ts.portal
    portal_muerto.vivo = False

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas.count("attach_portal") == 2
    assert ts.portal is not portal_muerto


def test_abrir_portal_reutiliza_el_portal_sano(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert ts.llamadas.count("attach_portal") == 1


def test_el_error_de_attach_se_traduce_para_el_operador(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    """El mensaje de Siemens se traduce a algo accionable."""
    servicio, ts, eventos = entorno
    ts.error_attach = (
        "OpennessAccessException: No matching TIA Portal version could be found."
    )

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"])
    assert evento["estado"] == "error"
    assert "No hay ningún TIA Portal abierto" in error
    assert "Abre TIA Portal con el proyecto" in error
    assert "No matching TIA Portal version" not in error


def test_el_log_conserva_el_texto_original_de_siemens(
    entorno: Any,
    caplog: pytest.LogCaptureFixture,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    ts.error_attach = (
        "OpennessAccessException: No matching TIA Portal version could be found."
    )

    with caplog.at_level(logging.WARNING):
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)

    assert "No matching TIA Portal version" in caplog.text


def test_un_error_desconocido_mantiene_su_texto(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    ts.error_attach = "Algo raro que no conozco"

    job_id = servicio.lanzar(tia.conectar)
    evento = esperar_job(eventos, job_id)

    assert "Algo raro que no conozco" in str(evento["error"])


def test_la_desconexion_se_publica_una_sola_vez(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    """Al perder el portal, el evento tia sale una vez, no dos."""
    servicio, ts, eventos = entorno
    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    ts.portal.vivo = False

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    esperar_job(eventos, job_id)

    estados = eventos_de(eventos, "tia")
    indice_vivo = max(i for i, e in enumerate(estados) if e["conectado"] is True)
    desconexiones = [e for e in estados[indice_vivo:] if e["conectado"] is False]
    assert len(desconexiones) == 1


def test_conectar_usa_etiquetas_legibles(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    avances = eventos_de(eventos, "progress")
    etapas = avances[0]["stages"]
    assert [e["label"] for e in etapas] == [
        "Cargar el SDK de Siemens",
        "Enganchar TIA Portal",
    ]


def test_desconectar_usa_etiquetas_legibles(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(tia.desconectar)
    esperar_job(eventos, job_id)

    avances = eventos_de(eventos, "progress")
    etapas = avances[0]["stages"]
    assert [e["label"] for e in etapas] == ["Cerrar el portal"]
