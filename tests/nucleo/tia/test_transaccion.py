"""La transaccion nativa de TIA: commit, rollback y como se distinguen.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios (los define ``conftest.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.nucleo.tia.errores import (
    SinProyectoError,
    TIAError,
)
from zc_suite.nucleo.tia.transaccion import transaccion

RAIZ = Path(__file__).resolve().parents[3]


def test_transaccion_confirma_con_rollback_false(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    esperar_job(eventos, job_id)

    transacciones = ts.portal.proyecto.transacciones
    assert ("start", "Importar") in transacciones
    assert ("end", False) in transacciones


def test_transaccion_hace_rollback_si_falla(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert ("end", True) in ts.portal.proyecto.transacciones
    assert ("end", False) not in ts.portal.proyecto.transacciones


def test_transaccion_informa_si_el_rollback_falla(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto.fallar_rollback = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "rollback" in str(evento["error"]).lower()


def test_transaccion_sin_portal_falla(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "conexion" in str(evento["error"]).lower()


def test_transaccion_sin_proyecto_lanza_sin_proyecto_error(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    """Hay conexion, pero no hay proyecto abierto."""
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto = None

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "SinProyectoError" in str(evento["error"])
    assert "No hay ningun proyecto abierto" in str(evento["error"])


def test_el_error_sin_proyecto_es_un_error_esperado() -> None:
    """Se registra como warning, sin traceback."""

    assert issubclass(SinProyectoError, TIAError)


def test_transaccion_con_commit_fallido_hace_rollback(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "commit" in str(evento["error"]).lower()
    assert ("end", True) in ts.portal.proyecto.transacciones


def test_transaccion_con_commit_fallido_y_rollback_fallido(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True
    ts.portal.proyecto.fallar_rollback = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"]).lower()
    assert evento["estado"] == "error"
    assert "commit" in error
    assert "rollback" in error


def test_el_mensaje_distingue_operacion_de_commit(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    """El fallo de la operacion y el del commit se describen distinto."""
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo_que_falla(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            raise ValueError("fallo de escritura")
        return {}

    job_id = servicio.lanzar(trabajo_que_falla)
    evento_operacion = esperar_job(eventos, job_id)
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
    evento_commit = esperar_job(eventos, job_id)
    error_commit = str(evento_commit["error"]).lower()
    assert evento_commit["estado"] == "error"
    assert "commit" in error_commit
    assert "fallo de la operacion" not in error_commit


def test_transaccion_con_file_not_found_conserva_el_mensaje(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    """Con un OSError, el mensaje original no se pierde al añadir la nota."""
    servicio, _ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["leer"])
        with job.paso("leer"), transaccion(job, "Importar"):
            raise FileNotFoundError(2, "No such file or directory", "datos.xml")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"])
    assert evento["estado"] == "error"
    assert "FileNotFoundError" in error
    assert "No such file or directory" in error
    assert "Rollback ejecutado" in error


def test_transaccion_con_key_error_conserva_el_mensaje(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    """Con un KeyError, la clave se sigue viendo en el mensaje."""
    servicio, _ts, eventos = entorno
    conectar(servicio, eventos)

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["leer"])
        with job.paso("leer"), transaccion(job, "Importar"):
            raise KeyError("columna_inexistente")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"])
    assert evento["estado"] == "error"
    assert "KeyError" in error
    assert "columna_inexistente" in error
    assert "Rollback ejecutado" in error


def test_el_commit_fallido_con_rollback_bueno_dice_que_no_se_confirmo_nada(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"])
    assert evento["estado"] == "error"
    assert "no se confirmó nada" in error.lower()
    assert "puede haber quedado a medias" not in error


def test_el_commit_fallido_con_rollback_fallido_avisa_del_proyecto(
    entorno: Any,
    esperar_job: Callable[..., Any],
    conectar: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    conectar(servicio, eventos)
    ts.portal.proyecto.fallar_commit = True
    ts.portal.proyecto.fallar_rollback = True

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["escribir"])
        with job.paso("escribir"), transaccion(job, "Importar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    error = str(evento["error"]).lower()
    assert evento["estado"] == "error"
    assert "commit" in error
    assert "puede haber quedado a medias" in error
