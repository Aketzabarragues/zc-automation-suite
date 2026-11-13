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
    assert compilacion["ok"] is False
    assert "errores de compilacion" in compilacion["error"]


def test_los_comentarios_no_se_ejecutan_en_tia_v18(entorno_sync_v18: Any) -> None:
    """La transaccion de comentarios necesita TIA V21: antes no se ejecuta."""
    evento = entorno_sync_v18.sincronizar()

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    comentarios = _transaccion_por_nombre(resultado, "Comentarios")
    assert comentarios["estado"] == NO_EJECUTADA
    assert "V21" in comentarios["detalle"]
    assert entorno_sync_v18.plc.importaciones_bloques == []


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
