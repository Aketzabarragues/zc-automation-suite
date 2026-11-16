"""El FB que sincroniza las entidades contra TIA.

Las tres transacciones van en su orden, cada una se comprueba, y el resultado
dice cual se confirmo, cual se revirtio y cual no se ejecuto.
"""
from __future__ import annotations

from typing import Any

import pytest

from zc_suite.areas.alimentacion.funciones.entidades import (
    sincronizar as modulo_sync,
)
from zc_suite.areas.alimentacion.funciones.entidades.sincronizar import (
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


def _constantes(entorno: Any) -> dict[str, str]:
    """Las constantes de usuario que hay ahora en el PLC."""
    return {
        constante.get_property("Name"): constante.get_property("Value")
        for tabla in entorno.plc.get_plc_tag_tables()
        for constante in tabla.get_user_constants()
    }


def test_el_sync_aplica_el_n_max_las_constantes_y_los_comentarios(
    entorno_sync: Any,
) -> None:
    """Lo que dice el Excel llega a TIA."""
    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["n_max"]["actualizados"] == 1
    assert resultado["constantes"]["operaciones"] > 0

    constantes = _constantes(entorno_sync)
    # El N_MAX del Excel (6) gana al de TIA (3).
    assert constantes["N_MAX_ENTIDAD"] == "6"
    # Los renombres: el valor 2 ahora se llama ENT_002_NUEVO y el 99 ENT_099.
    assert constantes["ENT_002_NUEVO"] == "2"
    assert "ENT_002" not in constantes
    assert constantes["ENT_099"] == "99"
    assert "Constant_1" not in constantes
    # El alta: ENT_004 con el valor 4.
    assert constantes["ENT_004"] == "4"
    # La baja: ENT_050 ya no esta.
    assert "ENT_050" not in constantes


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


def test_la_tabla_de_n_max_no_llega_al_import(entorno_sync: Any, tmp_path: Any) -> None:
    """La tabla del N_MAX no se copia a ``modified/``: ya se aplico en linea."""
    from pathlib import Path

    entorno_sync.sincronizar()

    modified = Path(entorno_sync.plc.importaciones_tablas[0]["directorio"])
    assert not (modified / "6_Entidades" / "0_Config_Generales.xml").exists()
    assert (modified / "6_Entidades" / "6_Entidades.xml").is_file()


def test_las_tres_transacciones_se_confirman(entorno_sync: Any) -> None:
    """Cuando todo va bien, las tres transacciones quedan confirmadas."""
    evento = entorno_sync.sincronizar()

    resultado = evento["resultado"]
    for transaccion in resultado["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion
    assert resultado["prevision"] is not None


def test_el_db_se_importa_con_los_comentarios(entorno_sync: Any) -> None:
    """La transaccion de comentarios importa el DB de entidades."""
    entorno_sync.sincronizar()

    assert len(entorno_sync.plc.importaciones_bloques) == 1
    importacion = entorno_sync.plc.importaciones_bloques[0]
    assert importacion["directorio"].replace("\\", "/").endswith(
        "sincronizar/bloques/modified"
    )
    assert importacion["carpeta_destino"] is None


def test_la_prevision_se_recalcula_y_se_guarda_en_la_sesion(entorno_sync: Any) -> None:
    """Al terminar, la prevision se vuelve a calcular y queda en la sesion."""
    sesion = Sesion()

    evento = entorno_sync.sincronizar(sesion=sesion)

    assert evento["estado"] == "ok", evento.get("error")
    guardada = sesion.datos_area("alimentacion")["prevision_entidades"]
    assert guardada["plc"] == "ZC_PLC_STD"


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
    assert "N_MAX: confirmada" in error
    assert "Constantes: revertida" in error
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
    """La compilacion se avisa, pero lo que ya esta aplicado se queda."""
    for bloque in entorno_sync.plc.get_program_blocks():
        monkeypatch.setattr(bloque, "is_consistent", lambda: False)
        monkeypatch.setattr(bloque, "compile", lambda: True)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion == "compile=WARN"


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
    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert list(transacciones) == ["N_MAX", "Constantes", "Comentarios"]
    assert transacciones["N_MAX"]["estado"] == CONFIRMADA
    assert transacciones["N_MAX"]["detalle"] == "1 N_MAX"
    assert transacciones["Constantes"]["estado"] == CONFIRMADA
    # El detalle cuenta las operaciones de constantes (alta, bajas,
    # renombres, borrado de sobrantes).
    assert transacciones["Constantes"]["detalle"].endswith("operaciones")
    assert transacciones["Constantes"]["detalle"].split(" ", 1)[0].isdigit()
    assert transacciones["Comentarios"]["estado"] == CONFIRMADA
    assert transacciones["Comentarios"]["detalle"] == "DB de entidades"
    # Las claves de primer nivel del resultado, sin mas ni menos.
    assert set(resultado) == {
        "plc",
        "operaciones",
        "n_max",
        "constantes",
        "comentarios",
        "transacciones",
        "compilacion",
        "prevision",
    }
    assert resultado["n_max"] == {"actualizados": 1}
    assert resultado["constantes"]["operaciones"] == int(
        transacciones["Constantes"]["detalle"].split(" ", 1)[0]
    )
    # La prevision se recalcula y tiene la forma de la vista (sin el PLC).
    assert resultado["prevision"]["precondiciones_ok"] is True
    assert "total" in resultado["prevision"]["summary"]


def test_la_compilacion_con_errores_no_tumba_y_fija_su_dict(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El DB que sigue inconsistente deja ``compile=WARN``: el sync termina
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
    assert compilacion == "compile=WARN"
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
    import zc_suite.areas.alimentacion.funciones.entidades.sincronizar as mod

    def _compilar_falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja compilar")

    monkeypatch.setattr(mod, "compilar_bloques", _compilar_falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    compilacion = evento["resultado"]["compilacion"]
    assert compilacion == "compile=WARN"
    # El sync se quedo: las transacciones anteriores siguen confirmadas.
    for transaccion in evento["resultado"]["transacciones"]:
        assert transaccion["estado"] == CONFIRMADA, transaccion


def test_si_falla_la_importacion_de_comentarios_se_revierte(
    entorno_sync: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si TIA no deja importar el DB de entidades, la tx de comentarios se
    revierte, las anteriores se quedan confirmadas y el mensaje lo dice."""

    def _falla(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(modulo_sync, "importar_bloques", _falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "TIA no deja importar" in error
    assert "N_MAX: confirmada" in error
    assert "Constantes: confirmada" in error
    assert "Comentarios: revertida" in error
    # El mensaje termina con el resumen de transacciones, en su orden.
    assert error.endswith(
        "Transacciones: N_MAX: confirmada; Constantes: confirmada; "
        "Comentarios: revertida."
    )
    # Un trabajo en error no devuelve resultado.
    assert evento["resultado"] is None


def test_en_v18_el_dict_fija_el_estado_de_cada_transaccion(
    entorno_sync_v18: Any,
) -> None:
    """En V18 el dict completo fija: N_MAX y Constantes confirmadas,
    Comentarios no ejecutada por falta de SimaticSD, y el paso de compilacion
    (el DB del fixture esta consistente: no se recompila)."""
    evento = entorno_sync_v18.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    transacciones = {t["nombre"]: t for t in resultado["transacciones"]}
    assert transacciones["N_MAX"]["estado"] == CONFIRMADA
    assert transacciones["N_MAX"]["detalle"] == "1 N_MAX"
    assert transacciones["Constantes"]["estado"] == CONFIRMADA
    assert transacciones["Comentarios"]["estado"] == NO_EJECUTADA
    assert transacciones["Comentarios"]["detalle"] == (
        "los comentarios por instancia necesitan TIA Portal V21 o superior"
    )
    assert resultado["compilacion"] == "compile=OK (0 compilados, 1 sin cambios)"
    # Sin SimaticSD no se importa ningun bloque.
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
