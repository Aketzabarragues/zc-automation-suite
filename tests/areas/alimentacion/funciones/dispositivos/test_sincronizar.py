"""El FB que sincroniza los dispositivos contra TIA.

Las tres transacciones van en su orden, cada una se comprueba, y el resultado
dice cual se confirmo, cual se revirtio y cual no se ejecuto.
"""
from __future__ import annotations

from typing import Any

import pytest

from zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar import (
    CONFIRMADA,
    NO_EJECUTADA,
)
from zc_suite.nucleo.sesion import Sesion


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

    def _falla(**_kwargs: Any) -> None:
        raise RuntimeError("TIA no deja importar")

    monkeypatch.setattr(entorno_sync.plc, "import_plc_tags", _falla)

    evento = entorno_sync.sincronizar()

    assert evento["estado"] == "error"
    error = evento["error"]
    assert "N_MAX y renombres: confirmada" in error
    assert "Dispositivos: revertida" in error
    assert "Comentarios: no ejecutada" in error


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
