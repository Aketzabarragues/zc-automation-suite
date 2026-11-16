"""El FB que sincroniza los dispositivos contra TIA.

Las tres transacciones van en su orden, cada una se comprueba, y el resultado
dice cual se confirmo, cual se revirtio y cual no se ejecuto.
"""
from __future__ import annotations

from typing import Any

import pytest

from zc_suite.areas.alimentacion.funciones.dispositivos import (
    sincronizar as modulo_sync,
)
from zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar import (
    CONFIRMADA,
    NO_EJECUTADA,
)
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError


def _transaccion_por_nombre(resultado: dict[str, Any], nombre: str) -> dict[str, Any]:
    """La transaccion del resultado que tiene ese nombre."""
    for transaccion in resultado["transacciones"]:
        if transaccion["nombre"] == nombre:
            return transaccion
    raise AssertionError(f"No hay ninguna transaccion llamada '{nombre}'.")


def test_el_sync_aplica_los_n_max_los_renombres_y_los_dispositivos(
    entorno_sync: Any,
) -> None:
    """Lo que dice el Excel llega a TIA: los N_MAX, el renombrado y el alta."""
    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]

    assert resultado["n_max"]["actualizados"] == 3
    assert resultado["n_max"]["renombres"] == 1
    assert resultado["dispositivos"]["agregados"] == 1
    assert resultado["dispositivos"]["eliminados"] == 1

    # El N_MAX del Excel (10) gana al de TIA (5).
    constantes = {
        constante.get_property("Name"): constante.get_property("Value")
        for tabla in entorno_sync.plc.get_plc_tag_tables()
        for constante in tabla.get_user_constants()
    }
    assert constantes["N_MAX_DISP_ED"] == "10"
    assert constantes["N_MAX_DISP_TQ"] == "90"
    assert constantes["N_MAX_DISP_PID"] == "120"
    # Un N_MAX que no existe en TIA no se toca: no se puede cambiar su valor.
    assert "N_MAX_DISP_SA" not in constantes
    # El renombrado: el numero 2 ahora se llama ED_002_NUEVO.
    assert constantes["ED_002_NUEVO"] == "2"
    assert "ED_002" not in constantes
    # El alta: ED_004 con el valor 4.
    assert constantes["ED_004"] == "4"
    # La baja: ED_099 ya no esta.
    assert "ED_099" not in constantes


def test_la_importacion_de_las_tablas_va_desde_la_raiz_sin_carpeta_destino(
    entorno_sync: Any,
) -> None:
    """El import va desde la raiz de ``modified/`` y sin carpeta destino."""
    entorno_sync.sincronizar()

    assert len(entorno_sync.plc.importaciones_tablas) == 1
    importacion = entorno_sync.plc.importaciones_tablas[0]
    assert importacion["directorio"].replace("\\", "/").endswith(
        "sincronizar/variables/modified"
    )
    assert importacion["carpeta_destino"] is None


def test_las_tres_transacciones_se_confirman(entorno_sync: Any) -> None:
    """Cuando todo va bien, las tres transacciones quedan confirmadas."""
    evento = entorno_sync.sincronizar()

    resultado = evento["resultado"]
    for transaccion in resultado["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion
    assert resultado["prevision"] is not None


def test_la_prevision_se_recalcula_y_se_guarda_en_la_sesion(entorno_sync: Any) -> None:
    """Al terminar, la prevision se vuelve a calcular y queda en la sesion."""
    sesion = Sesion()

    evento = entorno_sync.sincronizar(sesion=sesion)

    assert evento["estado"] == "ok", evento.get("error")
    guardada = sesion.datos_area("alimentacion")["prevision_dispositivos"]
    assert guardada["plc"] == "ZC_PLC_STD"
    assert guardada["resultado"]["summary"]["total"] > 0


def test_sin_cambios_no_se_abre_ninguna_transaccion(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el Excel ya esta en TIA, ninguna transaccion se abre."""
    monkeypatch.setattr(
        entorno_sync.almacen,
        "dispositivos_de",
        lambda *args: [
            {"numero": 1, "plc_tag": "ED_001"},
            {"numero": 2, "plc_tag": "ED_002"},
            {"numero": 3, "plc_tag": "ED_003"},
            {"numero": 99, "plc_tag": "ED_099"},
        ],
    )
    monkeypatch.setattr(
        entorno_sync.almacen,
        "valores_n_max_de",
        lambda *args: {
            "N_MAX_DISP_ED": 5,
            "N_MAX_DISP_EA": 20,
            "N_MAX_DISP_M_VF": 70,
            "N_MAX_DISP_TQ": 80,
            "N_MAX_DISP_TOT": 110,
            "N_MAX_DISP_PID": 115,
        },
    )

    evento = entorno_sync.sincronizar()

    resultado = evento["resultado"]
    assert _transaccion_por_nombre(resultado, "N_MAX y renombres")["estado"] == NO_EJECUTADA
    assert _transaccion_por_nombre(resultado, "Dispositivos")["estado"] == NO_EJECUTADA
    assert entorno_sync.plc.importaciones_tablas == []


def test_el_fallo_de_una_transaccion_dice_lo_que_quedo_confirmado(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la importacion falla, el error dice que se confirmo y que no."""

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(entorno_sync.plc, "import_plc_tags", _falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "N_MAX y renombres: confirmada" in error
    assert "Dispositivos: revertida" in error
    assert "Comentarios: no ejecutada" in error


def test_la_cancelacion_no_se_confunde_con_un_error(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el operario cancela, el trabajo termina como cancelado."""

    def _cancela(*_args: Any, **_kwargs: Any) -> None:
        raise CanceladoError("El trabajo fue cancelado.")

    monkeypatch.setattr(modulo_sync, "importar_tablas", _cancela)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "cancelado"


def test_los_errores_de_compilacion_no_tumban_el_sync(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La compilacion se avisa, pero lo que ya esta aplicado se queda.

    Un bloque que sigue inconsistente tras compilar tiene errores, y el aviso
    lo nombra.
    """
    nombres = []
    for bloque in entorno_sync.plc.get_program_blocks():
        nombres.append(bloque.get_name())
        monkeypatch.setattr(bloque, "is_consistent", lambda: False)
        monkeypatch.setattr(bloque, "compile", lambda: True)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion["ok"] is False
    assert "errores de compilacion" in compilacion["error"]
    assert "con errores" in compilacion["error"]
    assert any(nombre in compilacion["error"] for nombre in nombres)


def test_el_aviso_trae_el_mensaje_de_tia(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El aviso dice que bloque falla y por que, sin la ruta del bloque."""
    from tests.tia_ops.test_compilar import ResultadoFalso

    bloques = entorno_sync.plc.get_program_blocks()
    for bloque in bloques:
        nombre = bloque.get_name()
        monkeypatch.setattr(bloque, "is_consistent", lambda: False)
        monkeypatch.setattr(
            bloque, "compile", lambda nombre=nombre: ResultadoFalso(nombre, tiene_errores=True)
        )

    evento = entorno_sync.sincronizar()

    error = evento["resultado"]["compilacion"]["error"]
    nombre = bloques[0].get_name()
    assert f"{nombre} (Interface > Data type Boo is unknown.)" in error


def test_compile_que_devuelve_true_y_deja_el_bloque_bien_no_es_un_error(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso real de TIA V21: compile() devuelve un valor verdadero y el bloque
    queda consistente. main lo avisaba como "10 bloques con errores"."""
    for bloque in entorno_sync.plc.get_program_blocks():
        estado = {"consistente": False}

        def compilar(estado: dict[str, bool] = estado) -> bool:
            estado["consistente"] = True
            return True

        monkeypatch.setattr(bloque, "is_consistent", lambda estado=estado: estado["consistente"])
        monkeypatch.setattr(bloque, "compile", compilar)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion["ok"] is True, compilacion.get("error")
    assert compilacion["detalle"].startswith("compile=OK")


def test_los_comentarios_no_se_ejecutan_en_tia_v18(entorno_sync_v18: Any) -> None:
    """La transaccion de comentarios necesita TIA V21: antes no se ejecuta."""
    evento = entorno_sync_v18.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    comentarios = _transaccion_por_nombre(resultado, "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA
    assert "V21" in comentarios["detalle"]
    assert entorno_sync_v18.plc.importaciones_bloques == []


def test_el_dict_completo_fija_los_nombres_y_valores_de_cada_transaccion(
    entorno_sync: Any,
) -> None:
    """El resultado fija el texto exacto de cada transaccion y su contador.

    Los nombres publicos que el faceplate y el resultado de error comparten
    vienen de ``_transacciones_iniciales``: si cambian, cambia el contrato
    de la vista y del mensaje de fallo.
    """
    from zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar import (
        CONFIRMADA as CONFIRMADA_CONST,
    )

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert list(transacciones) == ["N_MAX y renombres", "Dispositivos", "Comentarios"]
    assert transacciones["N_MAX y renombres"]["estado"] == CONFIRMADA_CONST
    assert transacciones["N_MAX y renombres"]["detalle"] == "3 N_MAX y 1 renombres"
    assert transacciones["Dispositivos"]["estado"] == CONFIRMADA_CONST
    assert transacciones["Dispositivos"]["detalle"] == "1 tablas"
    assert transacciones["Comentarios"]["estado"] == CONFIRMADA_CONST
    assert transacciones["Comentarios"]["detalle"] == "1 DBs con comentarios"
    # Las claves de primer nivel del resultado, sin mas ni menos.
    assert set(resultado) == {
        "plc",
        "operaciones",
        "n_max",
        "dispositivos",
        "transacciones",
        "compilacion",
        "prevision",
    }
    assert resultado["operaciones"] == 6
    assert resultado["n_max"] == {"actualizados": 3, "renombres": 1}
    assert resultado["dispositivos"] == {
        "tablas": 1,
        "agregados": 1,
        "eliminados": 1,
    }
    # La prevision se recalculo tras aplicar: todo queda sin cambios.
    assert resultado["prevision"]["summary"] == {
        "agregados": 0,
        "eliminados": 0,
        "renombrados": 0,
        "sin_cambios": 4,
        "total": 4,
    }


def test_la_compilacion_con_errores_no_tumba_y_fija_su_dict(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un DB que sigue inconsistente deja ``compile=WARN``: el sync termina
    en ok, la tx de comentarios se ejecuta igual y el aviso lista el bloque
    con el mensaje de TIA recortado (sin la ruta del bloque)."""
    from tests.tia_ops.test_compilar import ResultadoFalso

    for bloque in entorno_sync.plc.get_program_blocks():
        nombre = bloque.get_name()
        monkeypatch.setattr(bloque, "is_consistent", lambda: False)
        monkeypatch.setattr(
            bloque, "compile", lambda nombre=nombre: ResultadoFalso(nombre, tiene_errores=True)
        )

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion["ok"] is False
    assert compilacion["detalle"] == "compile=WARN"
    error = compilacion["error"]
    assert error.startswith("TIA reporta errores de compilacion: ")
    assert "1 bloque(s) con errores: " in error
    nombre = entorno_sync.plc.get_program_blocks()[0].get_name()
    assert f"{nombre} (Interface > Data type Boo is unknown.)" in error
    assert error.endswith(
        " Revisa esos bloques en TIA Portal: pueden haber quedado con "
        "un tamano inconsistente tras el cambio de N_MAX."
    )
    # La tx de comentarios no se salta por el fallo de compilacion.
    comentarios = _transaccion_por_nombre(evento["resultado"], "Comentarios")
    assert comentarios["estado"] == CONFIRMADA
    assert entorno_sync.plc.importaciones_bloques


def test_si_la_compilacion_lanza_los_cambios_se_quedan(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``compilar_bloques`` lanza (el PLC no existe en TIA): el sync termina
    en ok con ``compile=WARN`` y el error de compilacion lleva la excepcion."""
    import zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar as mod

    def _compilar_falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja compilar")

    monkeypatch.setattr(mod, "compilar_bloques", _compilar_falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion["ok"] is False
    assert compilacion["error"] == "TIA no deja compilar"
    assert compilacion["detalle"] == "compile=WARN"
    # El sync se quedo: las transacciones anteriores siguen confirmadas.
    for transaccion in evento["resultado"]["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion


def test_si_falla_la_importacion_de_comentarios_se_revierte(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si TIA no deja importar los bloques, la tx de comentarios se revierte,
    las anteriores se quedan confirmadas y el mensaje de error lo dice."""

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(modulo_sync, "importar_bloques", _falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "TIA no deja importar" in error
    assert "N_MAX y renombres: confirmada" in error
    assert "Dispositivos: confirmada" in error
    assert "Comentarios: revertida" in error
    # El mensaje termina con el resumen de transacciones, en su orden.
    assert error.endswith(
        "Transacciones: N_MAX y renombres: confirmada; "
        "Dispositivos: confirmada; "
        "Comentarios: revertida."
    )
    # Un trabajo en error no devuelve resultado.
    assert evento["resultado"] is None


def test_en_v18_el_dict_fija_el_estado_de_cada_transaccion(
    entorno_sync_v18: Any,
) -> None:
    """En V18 el dict completo fija: N_MAX y Dispositivos confirmadas,
    Comentarios no ejecutada por falta de SimaticSD, y el paso de compilacion
    (el DB del fixture esta consistente: no se recompila)."""
    evento = entorno_sync_v18.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert transacciones["N_MAX y renombres"]["estado"] == CONFIRMADA
    assert transacciones["N_MAX y renombres"]["detalle"] == "3 N_MAX y 1 renombres"
    assert transacciones["Dispositivos"]["estado"] == CONFIRMADA
    assert transacciones["Dispositivos"]["detalle"] == "1 tablas"
    assert transacciones["Comentarios"]["estado"] == NO_EJECUTADA
    assert transacciones["Comentarios"]["detalle"] == (
        "los comentarios por instancia necesitan TIA Portal V21 o superior"
    )
    compilacion = resultado["compilacion"]
    assert compilacion == {
        "ok": True,
        "error": None,
        "detalle": "compile=OK (0 compilados, 1 sin cambios)",
    }
    # Sin SimaticSD no se exporta ni importa ningun bloque.
    assert entorno_sync_v18.plc.importaciones_bloques == []
    assert resultado["prevision"] is not None


def test_el_proyecto_no_se_guarda(entorno_sync: Any) -> None:
    """El sync no guarda el proyecto: el doble de TIA no tiene ese metodo.

    Si el FB lo llamara, el trabajo reventaria con un ``AttributeError``.
    """
    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")


def test_las_transacciones_se_abren_y_se_cierran(entorno_sync: Any) -> None:
    """Cada transaccion abierta se cierra con commit."""
    entorno_sync.sincronizar()

    transacciones = entorno_sync.proyecto.transacciones
    inicios = [t for t in transacciones if "inicio" in t]
    cierres = [t for t in transacciones if "rollback" in t]
    assert len(inicios) == len(cierres)
    assert cierres
    assert all(t["rollback"] is False for t in cierres)
