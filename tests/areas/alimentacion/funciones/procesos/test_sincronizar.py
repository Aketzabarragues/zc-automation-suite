"""El FB que sincroniza un proceso contra TIA.

Dos transacciones, en su orden (los N_MAX en linea y los comentarios
offline), cada una se comprueba, y el resultado dice cual se confirmo, cual
se revirtio y cual no se ejecuto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zc_suite.areas.alimentacion.funciones.procesos.sincronizar import (
    CONFIRMADA,
    NO_EJECUTADA,
)
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError

from .conftest import (
    DB_ALM,
    DB_PARAM,
    NOMBRE_PLC,
    PROC_UID,
    TABLA_PROCESO,
)


def _transaccion_por_nombre(resultado: dict[str, Any], nombre: str) -> dict[str, Any]:
    """La transaccion del resultado que tiene ese nombre."""
    for transaccion in resultado["transacciones"]:
        if transaccion["nombre"] == nombre:
            return transaccion
    raise AssertionError(f"No hay ninguna transaccion llamada '{nombre}'.")


def _constantes_de(entorno: Any, tabla: str) -> dict[str, str]:
    """Las constantes de usuario de una tabla, como estan ahora en el PLC."""
    for t in entorno.plc.get_plc_tag_tables():
        if t.get_name() != tabla:
            continue
        return {
            constante.get_property("Name"): constante.get_property("Value")
            for constante in t.get_user_constants()
        }
    raise AssertionError(f"No hay ninguna tabla llamada '{tabla}'.")


def _n_max(entorno: Any) -> dict[str, str]:
    """Los N_MAX que hay ahora en la tabla del proceso."""
    return _constantes_de(entorno, TABLA_PROCESO)


def _db_compilados(entorno: Any) -> dict[str, int]:
    """Cuantas veces se ha compilado cada DB del fixture."""
    return {b.get_name(): b.n_compilaciones for b in entorno.plc.get_program_blocks()}


def test_el_sync_aplica_el_n_max_y_los_comentarios(entorno_sync: Any) -> None:
    """Lo que dice el Excel llega a TIA: los N_MAX y los comentarios."""
    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    # El PREAL (3->2) y el ALM_HMI (1->2) del Excel ganan a los de TIA.
    assert resultado["n_max"]["actualizados"] == 2
    n_max = _n_max(entorno_sync)
    assert n_max[f"{PROC_UID}_N_MAX_PREAL"] == "2"
    assert n_max[f"{PROC_UID}_N_MAX_ALM_HMI"] == "2"
    # El PINT (1 == 1) y el ALM (2 == 2) ya estaban al dia: no se tocan.
    assert n_max[f"{PROC_UID}_N_MAX_PINT"] == "1"
    assert n_max[f"{PROC_UID}_N_MAX_ALM"] == "2"


def test_la_importacion_de_las_bloques_va_desde_la_raiz_sin_carpeta_destino(
    entorno_sync: Any,
) -> None:
    """El import va desde la raiz de ``modified/`` y sin carpeta destino."""
    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    assert len(entorno_sync.plc.importaciones_bloques) == 1
    importacion = entorno_sync.plc.importaciones_bloques[0]
    assert importacion["directorio"].replace("\\", "/").endswith(
        "sincronizar/bloques/modified"
    )
    assert importacion["carpeta_destino"] is None


def test_lo_que_se_importa_es_la_copia_modified_no_el_export(entorno_sync: Any) -> None:
    """La edicion offline se hace en la copia: el import trae esa copia."""
    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    # La carpeta importada lleva los ficheros del fixture, editados offline.
    directorio = Path(entorno_sync.plc.importaciones_bloques[0]["directorio"])
    assert (directorio / f"{DB_PARAM}.s7res").is_file()
    assert (directorio / f"{DB_ALM}.s7res").is_file()


def test_las_dos_transacciones_se_confirman(entorno_sync: Any) -> None:
    """Cuando todo va bien, las dos transacciones quedan confirmadas."""
    evento = entorno_sync.sincronizar(PROC_UID)

    resultado = evento["resultado"]
    n_max = _transaccion_por_nombre(resultado, "N_MAX")
    comentarios = _transaccion_por_nombre(resultado, "Comentarios")
    assert n_max["estado"] == CONFIRMADA, n_max
    assert comentarios["estado"] == CONFIRMADA, comentarios
    assert resultado["prevision"] is not None


def test_el_db_se_compila_entre_transacciones(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con N_MAX y con cambios de comentarios, los DBs se compilan."""
    # Inconsistentes al principio (TIA los compila) y consistentes despues.
    for bloque in entorno_sync.plc.get_program_blocks():
        estado = {"ok": False}

        def _is_consistent(estado=estado) -> bool:
            return estado["ok"]

        def _compile(estado=estado, bloque=bloque) -> bool:
            estado["ok"] = True
            bloque.n_compilaciones += 1
            return True

        monkeypatch.setattr(bloque, "is_consistent", _is_consistent)
        monkeypatch.setattr(bloque, "compile", _compile)
    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    compilados = _db_compilados(entorno_sync)
    assert compilados[DB_PARAM] == 1
    assert compilados[DB_ALM] == 1
    assert evento["resultado"]["compilacion"].startswith("compile=OK")


def test_con_n_max_y_sin_cambios_de_comentarios_compila_antes_de_reexportar(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con N_MAX pero sin cambios de comentarios, los DBs se compilan igual
    (TIA no exporta bloques inconsistentes) y la compilacion va antes del
    segundo export, como en ``main``.
    """
    for bloque in entorno_sync.plc.get_program_blocks():
        estado = {"ok": False}
        nombre_bloque = bloque.get_name()

        def _is_consistent(estado=estado) -> bool:
            return estado["ok"]

        def _compile(estado=estado, bloque=bloque, nombre=nombre_bloque) -> bool:
            estado["ok"] = True
            bloque.n_compilaciones += 1
            if bloque._orden is not None:
                bloque._orden.append(f"compile:{nombre}")
            return True

        monkeypatch.setattr(bloque, "is_consistent", _is_consistent)
        monkeypatch.setattr(bloque, "compile", _compile)

    # Sin cambios de comentarios: la edicion offline no modifica nada.
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    monkeypatch.setattr(mod, "proc_confirmar_db", lambda *a, **k: 0)

    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    # Sin cambios de comentarios: ni import ni transaccion de comentarios.
    assert entorno_sync.plc.importaciones_bloques == []
    comentarios = _transaccion_por_nombre(evento["resultado"], "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA

    # Pero los DBs se han compilado igual: el N_MAX redimensiono los arrays.
    compilados = _db_compilados(entorno_sync)
    assert compilados[DB_PARAM] == 1
    assert compilados[DB_ALM] == 1

    # La compilacion ocurre ANTES del segundo export (el de la reexportacion):
    # la primera export es la inicial, la segunda la re-export; la compilacion
    # entra entre las dos (la tercera es la de la prevision post-sync).
    orden = entorno_sync.plc.orden
    for nombre in (DB_PARAM, DB_ALM):
        exporta = [i for i, e in enumerate(orden) if e == f"export:{nombre}"]
        compila = [i for i, e in enumerate(orden) if e == f"compile:{nombre}"]
        assert len(exporta) >= 2, orden
        assert compila, orden
        assert exporta[0] < compila[0] < exporta[1], orden


def test_sin_cambios_no_hay_transaccion_de_comentarios(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la edicion offline no se ejecuta, tampoco hay transaccion."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    monkeypatch.setattr(mod, "soporta_simaticsd", lambda version: False)

    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    comentarios = _transaccion_por_nombre(evento["resultado"], "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA
    assert entorno_sync.plc.importaciones_bloques == []


def test_el_export_del_sync_pide_mantener_estructura(
    entorno_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El sync exporta con la carpeta de TIA conservada (UPDATE al importar)."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    exportar_bloques = mod.exportar_bloques
    exportar_tablas = mod.exportar_tablas
    llamadas = {"bloques": [], "tablas": []}

    def _bloques(portal: Any, plc: str, destino: Any, nombres: Any, **kwargs: Any) -> Any:
        llamadas["bloques"].append(kwargs.get("mantener_estructura"))
        return exportar_bloques(portal, plc, destino, nombres, **kwargs)

    def _tablas(portal: Any, plc: str, destino: Any, nombres: Any, **kwargs: Any) -> Any:
        llamadas["tablas"].append(kwargs.get("mantener_estructura"))
        return exportar_tablas(portal, plc, destino, nombres, **kwargs)

    monkeypatch.setattr(mod, "exportar_bloques", _bloques)
    monkeypatch.setattr(mod, "exportar_tablas", _tablas)

    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    # La tabla y los bloques se exportan (y re-exportan) con estructura.
    assert llamadas["bloques"], "no se han exportado bloques"
    assert all(estructura is True for estructura in llamadas["bloques"])
    assert llamadas["tablas"], "no se han exportado tablas"
    assert all(estructura is True for estructura in llamadas["tablas"])


def test_el_db_de_subcarpeta_conserva_su_carpeta_en_modified(
    entorno_sync: Any,
) -> None:
    """Un DB en una subcarpeta del PLC conserva esa subcarpeta en modified/."""
    for bloque in entorno_sync.plc.get_program_blocks():
        bloque._jerarquia = "0_Procesos"

    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")
    assert entorno_sync.plc.importaciones_bloques

    directorio = Path(
        entorno_sync.plc.importaciones_bloques[0]["directorio"]
    )
    for db in (DB_PARAM, DB_ALM):
        assert (directorio / "0_Procesos" / f"{db}.s7dcl").is_file()
        assert (directorio / "0_Procesos" / f"{db}.s7res").is_file()


def test_solo_se_importa_el_db_que_ha_cambiado(
    entorno_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si solo cambia el DB_ALM, en modified/ no queda el DB_PARAM."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    def _solo_alm(base: Any, db: str, *args: Any, **kwargs: Any) -> int:
        return 3 if db == DB_ALM else 0

    monkeypatch.setattr(mod, "proc_confirmar_db", _solo_alm)

    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    directorio = Path(entorno_sync.plc.importaciones_bloques[0]["directorio"])
    assert (directorio / f"{DB_ALM}.s7res").is_file()
    assert not any(directorio.rglob(f"{DB_PARAM}.s7res"))
    assert not any(directorio.rglob(f"{DB_PARAM}.s7dcl"))


def test_la_prevision_post_sync_se_recopila_y_se_guarda(entorno_sync: Any) -> None:
    """Al terminar, la prevision se recalcula y queda en la sesion."""
    sesion = entorno_sync.sesion
    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    assert evento["resultado"]["prevision"] is not None
    guardada = sesion.datos_area("alimentacion")
    assert "prevision_procesos" in guardada


def test_el_fallo_de_la_tx_de_comentarios_dice_lo_que_quedo_confirmado(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la importacion falla, el error dice que se confirmo y que no."""

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(entorno_sync.plc, "import_blocks", _falla)

    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "N_MAX: confirmada" in error
    assert "Comentarios: revertida" in error
    # Lo confirmado en la primera transaccion se queda confirmado.
    n_max = _n_max(entorno_sync)
    assert n_max[f"{PROC_UID}_N_MAX_PREAL"] == "2"


def test_el_fallo_de_la_tx_de_n_max_revuelve_solo_a_si_misma(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la Tx A falla, se revierte ella y no se toca la Tx B."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja cambiar el N_MAX")

    monkeypatch.setattr(mod, "cambiar_valor", _falla)
    monkeypatch.setattr(entorno_sync.plc, "import_blocks", _falla)

    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "N_MAX: revertida" in error
    assert "Comentarios: no ejecutada" in error
    # El N_MAX no se aplico.
    assert _n_max(entorno_sync)[f"{PROC_UID}_N_MAX_PREAL"] == "3"


def test_la_cancelacion_no_se_confunde_con_un_error(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el operario cancela, el trabajo termina como cancelado."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    def _cancela(*_args: Any, **_kwargs: Any) -> None:
        raise CanceladoError("El trabajo fue cancelado.")

    monkeypatch.setattr(mod, "cambiar_valor", _cancela)

    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "cancelado"


def test_el_sync_en_tia_v18_no_exporta_bloques(
    entorno_sync_v18: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En V18 el sync no exporta bloques: solo la tabla y la tx de N_MAX."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    exportados: list[str] = []

    def _bloques(portal: Any, plc: str, destino: Any, nombres: Any, **kwargs: Any) -> Any:
        exportados.extend(nombres or [])
        return mod.exportar_bloques(portal, plc, destino, nombres, **kwargs)

    monkeypatch.setattr(mod, "exportar_bloques", _bloques)

    evento = entorno_sync_v18.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    # Ni export ni re-export de bloques en V18.
    assert exportados == []
    # El doble V18 lanza si se le pide export SimaticSD: si el sync llegara
    # a exportar, el trabajo fallaria.
    resultado = evento["resultado"]
    assert _transaccion_por_nombre(resultado, "N_MAX")["estado"] == CONFIRMADA
    comentarios = _transaccion_por_nombre(resultado, "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA
    assert "V21" in comentarios["detalle"]
    assert entorno_sync_v18.plc.importaciones_bloques == []


def test_los_comentarios_no_se_ejecutan_en_tia_v18(entorno_sync_v18: Any) -> None:
    """La transaccion de comentarios necesita TIA V21: antes no se ejecuta."""
    evento = entorno_sync_v18.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    comentarios = _transaccion_por_nombre(resultado, "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA
    assert "V21" in comentarios["detalle"]
    assert entorno_sync_v18.plc.importaciones_bloques == []
    # El N_MAX, en cambio, si se aplico: no depende de SimaticSD.
    assert _transaccion_por_nombre(resultado, "N_MAX")["estado"] == CONFIRMADA


def test_sin_escaneo_fresco_no_hay_sync(entorno_sync: Any) -> None:
    """Sin un escaneo fresco del PLC, el sync no se lanza."""
    sesion_vacia = Sesion()

    evento = entorno_sync.sincronizar(PROC_UID, sesion=sesion_vacia)

    assert evento["estado"] == "error"
    assert "escaneo" in evento["error"].lower()


def test_las_transacciones_se_abren_y_se_cierran(entorno_sync: Any) -> None:
    """Cada transaccion abierta se cierra con commit."""
    evento = entorno_sync.sincronizar(PROC_UID)
    assert evento["estado"] == "ok", evento.get("error")

    transacciones = entorno_sync.proyecto.transacciones
    inicios = [t for t in transacciones if "inicio" in t]
    cierres = [t for t in transacciones if "rollback" in t]
    assert len(inicios) == len(cierres)
    assert cierres
    assert all(t["rollback"] is False for t in cierres)


def test_el_dict_completo_fija_claves_y_valores(entorno_sync: Any) -> None:
    """El resultado de exito fija sus claves de primer nivel y el valor exacto
    de cada transaccion: los nombres publicos que el faceplate y el mensaje de
    fallo comparten vienen de ``_transacciones_iniciales``.
    """
    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    # Las claves de primer nivel, sin mas ni menos.
    assert set(resultado) == {
        "plc",
        "proc_uid",
        "operaciones",
        "n_max",
        "comentarios",
        "transacciones",
        "compilacion",
        "prevision",
    }
    assert resultado["plc"] == NOMBRE_PLC
    assert resultado["proc_uid"] == PROC_UID
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert list(transacciones) == ["N_MAX", "Comentarios"]
    assert transacciones["N_MAX"]["estado"] == CONFIRMADA
    assert transacciones["N_MAX"]["detalle"] == "2 N_MAX"
    assert transacciones["Comentarios"]["estado"] == CONFIRMADA
    assert transacciones["Comentarios"]["detalle"] == "DBs del proceso"
    # Los contadores: dos N_MAX (PREAL 3->2, ALM_HMI 1->2) y el resumen de
    # comentarios (``proc_resumen``), que cuenta agregados, renombrados y
    # eliminados por array.
    assert resultado["n_max"] == {"actualizados": 2}
    assert set(resultado["comentarios"]) == {
        "total",
        "agregados",
        "renombrados",
        "eliminados",
        "sin_cambios",
    }
    # Sin cambios de N_MAX la compilacion seria un no-op; aqui hay dos, pero
    # los bloques del doble se quedan consistentes y no se recompilan.
    assert resultado["compilacion"] == "compile=OK (0 compilados, 2 sin cambios)"
    assert resultado["prevision"] is not None
    assert "total" in resultado["prevision"]["summary"]
    # El numero de operaciones suma N_MAX mas las operaciones de comentarios.
    resumen = resultado["comentarios"]
    assert resultado["operaciones"] == (
        2 + resumen["agregados"] + resumen["renombrados"] + resumen["eliminados"]
    )


def test_la_compilacion_con_errores_no_tumba_y_fija_su_dict(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un DB que sigue inconsistente deja ``compile=WARN``: el sync termina en
    ok y el aviso del log lista el bloque con el mensaje de TIA recortado
    (sin la ruta del bloque)."""
    from tests.tia_ops.test_compilar import ResultadoFalso

    for bloque in entorno_sync.plc.get_program_blocks():
        nombre = bloque.get_name()
        monkeypatch.setattr(bloque, "is_consistent", lambda: False)
        monkeypatch.setattr(
            bloque, "compile", lambda nombre=nombre: ResultadoFalso(nombre, tiene_errores=True)
        )

    with caplog.at_level("WARNING"):
        evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    assert evento["resultado"]["compilacion"] == "compile=WARN"
    # El fallo de compilacion no revierte las transacciones.
    for transaccion in evento["resultado"]["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion
    # El aviso lleva el cuerpo exacto: el bloque con el mensaje recortado y
    # la cola final de los procesos (singular: ese bloque).
    avisos = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.getMessage().startswith("Compilacion con errores")
    ]
    assert len(avisos) == 1, avisos
    aviso = avisos[0]
    assert aviso.startswith(
        "Compilacion con errores (los cambios ya estan aplicados): "
        "TIA reporta errores de compilacion: "
    )
    nombre = entorno_sync.plc.get_program_blocks()[0].get_name()
    assert f"{nombre} (Interface > Data type Boo is unknown.)" in aviso
    assert aviso.endswith(
        " Revisa ese bloque en TIA Portal: puede haber quedado con "
        "un tamano inconsistente tras el cambio de N_MAX."
    )


def test_si_la_compilacion_lanza_los_cambios_se_quedan(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``compilar_bloques`` lanza: el sync termina en ok con ``compile=WARN``
    y el log lleva la excepcion (los cambios ya estan aplicados)."""
    import zc_suite.areas.alimentacion.funciones.procesos.sincronizar as mod

    def _compilar_falla(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("TIA no deja compilar")

    monkeypatch.setattr(mod, "compilar_bloques", _compilar_falla)

    with caplog.at_level("WARNING"):
        evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    # El detalle del paso es un string; la excepcion solo va al log.
    assert evento["resultado"]["compilacion"] == "compile=WARN"
    avisos = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.getMessage().startswith("La compilacion fallo")
    ]
    assert avisos == [
        "La compilacion fallo (los cambios ya estan aplicados): TIA no deja compilar"
    ]
    # El sync se quedo: las transacciones siguen confirmadas.
    for transaccion in evento["resultado"]["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion


def test_si_falla_la_importacion_de_comentarios_fija_el_error(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si TIA no deja importar los DBs, la tx de comentarios se revierte y el
    mensaje fija el resumen exacto de transacciones; un trabajo en error no
    devuelve resultado."""

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(entorno_sync.plc, "import_blocks", _falla)

    evento = entorno_sync.sincronizar(PROC_UID)

    assert evento["estado"] == "error"
    assert evento["resultado"] is None
    error = evento["error"]
    assert "TIA no deja importar" in error
    # El mensaje termina con el resumen de transacciones, en su orden.
    assert error.endswith(
        "Transacciones: N_MAX: confirmada; "
        "Comentarios: revertida."
    )
    # Lo confirmado en la primera transaccion se queda confirmado.
    assert _n_max(entorno_sync)[f"{PROC_UID}_N_MAX_PREAL"] == "2"


def test_en_v18_el_dict_fija_el_estado_de_cada_transaccion(
    entorno_sync_v18: Any,
) -> None:
    """En V18 el dict completo fija: N_MAX confirmada, Comentarios no ejecutada
    (falta SimaticSD), la compilacion como no-op y ni export ni import de
    bloques."""
    evento = entorno_sync_v18.sincronizar(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert transacciones["N_MAX"]["estado"] == CONFIRMADA
    assert transacciones["N_MAX"]["detalle"] == "2 N_MAX"
    assert transacciones["Comentarios"]["estado"] == NO_EJECUTADA
    assert transacciones["Comentarios"]["detalle"] == (
        "los comentarios por instancia necesitan TIA Portal V21 o superior"
    )
    # Sin comentarios no hay compilacion: el no-op se conserva como string.
    assert resultado["compilacion"] == "compile=no-op"
    # El N_MAX, en cambio, si se aplico: no depende de SimaticSD.
    assert _n_max(entorno_sync_v18)[f"{PROC_UID}_N_MAX_PREAL"] == "2"
    assert _n_max(entorno_sync_v18)[f"{PROC_UID}_N_MAX_ALM_HMI"] == "2"
    # Ni export ni import de bloques en V18.
    assert entorno_sync_v18.plc.importaciones_bloques == []
    assert resultado["prevision"] is not None
