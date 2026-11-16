"""El modulo comun de los FB de sync de alimentacion.

Es pura logica: no hay portal de TIA ni transacciones aqui. El doble de
``compilar_bloques`` es un dict fijo: el modulo no toca TIA, recibe el
resultado a traves del callable.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

from zc_suite.areas.alimentacion.sincronizacion_comun import (
    ESTADO_CONFIRMADA,
    ESTADO_NO_EJECUTADA,
    ESTADO_REVIRTIDA,
    compilar_con_aviso,
    estado_confirmada,
    estado_no_ejecutada,
    estado_revertida,
    estados_iniciales,
    localizar_xml,
    mensaje_corto,
    resumen_transacciones,
    texto_errores_compilacion,
)

# ── el estado de las transacciones ──────────────────────────────────────────


def _nombres_tres() -> dict[str, str]:
    return {
        "n_max": "N_MAX y renombres",
        "dispositivos": "Dispositivos",
        "comentarios": "Comentarios",
    }


def test_estados_iniciales_data_driven_por_nombres() -> None:
    """Las transacciones salen de sus nombres, todas no ejecutadas."""
    transacciones = estados_iniciales(_nombres_tres())

    assert list(transacciones) == ["n_max", "dispositivos", "comentarios"]
    assert transacciones["n_max"] == {
        "nombre": "N_MAX y renombres",
        "estado": "no ejecutada",
        "detalle": "",
    }
    assert transacciones["dispositivos"]["nombre"] == "Dispositivos"
    assert transacciones["comentarios"]["nombre"] == "Comentarios"
    assert all(t["estado"] == ESTADO_NO_EJECUTADA for t in transacciones.values())
    assert all(t["detalle"] == "" for t in transacciones.values())


def test_estados_iniciales_con_una_sola_transaccion() -> None:
    transacciones = estados_iniciales({"importar": "Importar proceso"})

    assert transacciones == {
        "importar": {
            "nombre": "Importar proceso",
            "estado": "no ejecutada",
            "detalle": "",
        }
    }


def test_el_estado_se_pasa_por_cada_transaccion() -> None:
    """El llamador pasa cada transaccion; el modulo solo la anota."""
    transacciones = estados_iniciales(_nombres_tres())

    estado_confirmada(transacciones, "n_max", "3 N_MAX y 1 renombres")
    estado_revertida(transacciones, "dispositivos", "TIA no deja importar")
    # comentarios sigue sin tocar.

    assert transacciones["n_max"] == {
        "nombre": "N_MAX y renombres",
        "estado": "confirmada",
        "detalle": "3 N_MAX y 1 renombres",
    }
    assert transacciones["dispositivos"]["estado"] == "revertida"
    assert transacciones["dispositivos"]["detalle"] == "TIA no deja importar"
    assert transacciones["comentarios"]["estado"] == "no ejecutada"


def test_el_estado_no_ejecutada_lleva_su_detalle() -> None:
    transacciones = estados_iniciales(_nombres_tres())

    estado_no_ejecutada(
        transacciones,
        "comentarios",
        "los comentarios por instancia necesitan TIA Portal V21 o superior",
    )

    assert transacciones["comentarios"] == {
        "nombre": "Comentarios",
        "estado": "no ejecutada",
        "detalle": "los comentarios por instancia necesitan TIA Portal V21 o superior",
    }


def test_el_resumen_es_exacto_y_en_su_orden() -> None:
    """El resumen va al final del mensaje de fallo, en el orden de las txs."""
    transacciones = estados_iniciales(_nombres_tres())
    estado_confirmada(transacciones, "n_max", "3 N_MAX y 1 renombres")
    estado_confirmada(transacciones, "dispositivos", "1 tablas")
    estado_revertida(transacciones, "comentarios", "TIA no deja importar")

    assert resumen_transacciones(transacciones) == (
        "Transacciones: N_MAX y renombres: confirmada; "
        "Dispositivos: confirmada; "
        "Comentarios: revertida."
    )


def test_el_resumen_con_todas_no_ejecutadas() -> None:
    transacciones = estados_iniciales({"importar": "Importar proceso"})

    assert resumen_transacciones(transacciones) == (
        "Transacciones: Importar proceso: no ejecutada."
    )


def test_el_estado_confirmada_cambia_el_estado_inicial() -> None:
    transacciones = estados_iniciales(_nombres_tres())

    assert transacciones["n_max"]["estado"] == ESTADO_NO_EJECUTADA
    estado_confirmada(transacciones, "n_max", "resumen")

    assert transacciones["n_max"]["estado"] == ESTADO_CONFIRMADA
    assert transacciones["n_max"]["detalle"] == "resumen"


# ── la compilacion fuera de transaccion ─────────────────────────────────────


def _resultado_compilar(con_errores: bool = True) -> dict[str, object]:
    """El doble de ``tia_ops.compilar_bloques``: un dict fijo, sin TIA."""
    return {
        "compilados": [
            {
                "nombre": "DB2000_ED",
                "tiene_errores": con_errores,
                "mensajes": (
                    [
                        "ZC_PLC_STD > Program blocks > DB2000_ED (DB5) > "
                        "Interface > Data type Boo is unknown."
                    ]
                    if con_errores
                    else []
                ),
                "avisos": [],
                "era_inconsistente": True,
            },
            {
                "nombre": "DB2001_EA",
                "tiene_errores": False,
                "mensajes": [],
                "avisos": [],
                "era_inconsistente": True,
            },
        ],
        "sin_cambios": ["DB2006_SA"],
        "no_encontrados": [] if con_errores else ["DB_FANTASMA"],
        "errores": [
            {"nombre": "DB_FALLO", "error": "RuntimeError: TIA no deja compilar"}
        ]
        if con_errores
        else [],
        "con_errores": ["DB2000_ED"] if con_errores else [],
        "n_compilados_ok": 0 if con_errores else 2,
        "n_compilados_error": 1 if con_errores else 0,
        "n_sin_cambios": 1,
        "n_no_encontrados": 0 if con_errores else 1,
        "n_errores": 1 if con_errores else 0,
    }


def test_el_texto_errores_fija_el_aviso_sin_la_cola() -> None:
    """El cuerpo del aviso es exacto: la cola final la pone el llamador."""
    error = texto_errores_compilacion(_resultado_compilar())

    assert error == (
        "TIA reporta errores de compilacion: "
        "1 bloque(s) con errores: DB2000_ED (Interface > Data type Boo is unknown.); "
        "1 no se pudieron compilar: DB_FALLO"
    )


def test_el_texto_errores_con_bloques_no_encontrados() -> None:
    resultado = _resultado_compilar(con_errores=False)
    resultado["con_errores"] = []
    resultado["errores"] = []
    resultado["compilados"] = []

    assert texto_errores_compilacion(resultado) == (
        "TIA reporta errores de compilacion: 1 no encontrado(s): DB_FANTASMA"
    )


def _cola_prueba() -> str:
    return (
        " Revisa ese bloque en TIA Portal: puede haber quedado con "
        "un tamano inconsistente tras el cambio de N_MAX."
    )


def _logger_con_registro() -> tuple[logging.Logger, list[str]]:
    """Un logger con un handler que registra los mensajes formateados."""
    registro: list[str] = []
    logger = logging.getLogger("prueba")

    class _Registro(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            registro.append(record.getMessage())

    logger.addHandler(_Registro())
    return logger, registro


def test_compilar_con_aviso_devuelve_el_detalle_ok() -> None:
    """El exito devuelve el detalle con los valores del resultado, sin aviso."""
    logger, registro = _logger_con_registro()
    resultado = _resultado_compilar(con_errores=False)

    detalle = compilar_con_aviso(
        compilador=lambda: resultado,
        cola=_cola_prueba(),
        logger=logger,
    )

    assert detalle == "compile=OK (2 compilados, 1 sin cambios)"
    assert registro == []


def test_compilar_con_aviso_con_errores_da_warn_y_la_cola_exacta() -> None:
    """Errores de TIA: ``compile=WARN`` y el warning lleva el cuerpo mas la cola."""
    logger, registro = _logger_con_registro()
    resultado = _resultado_compilar()

    detalle = compilar_con_aviso(
        compilador=lambda: resultado,
        cola=_cola_prueba(),
        logger=logger,
    )

    assert detalle == "compile=WARN"
    assert registro == [
        "Compilacion con errores (los cambios ya estan aplicados): "
        + texto_errores_compilacion(resultado)
        + _cola_prueba()
    ]


def test_compilar_con_aviso_si_lanza_da_warn_y_avisa() -> None:
    """El compilador lanza: ``compile=WARN`` y el warning lleva la excepcion."""
    logger, registro = _logger_con_registro()

    def _compilador() -> dict[str, object]:
        raise RuntimeError("TIA no deja compilar")

    detalle = compilar_con_aviso(
        compilador=_compilador,
        cola=_cola_prueba(),
        logger=logger,
    )

    assert detalle == "compile=WARN"
    assert registro == [
        "La compilacion fallo (los cambios ya estan aplicados): TIA no deja compilar"
    ]


# ── los helpers de texto y rutas ────────────────────────────────────────────


def test_el_mensaje_corto_recorta_la_ruta_del_bloque() -> None:
    mensaje = (
        "ZC_PLC_STD > Program blocks > DB6_ENT (DB6) > Interface > "
        "Data type Boo is unknown."
    )

    assert (
        mensaje_corto(mensaje) == "Interface > Data type Boo is unknown."
    )


def test_el_mensaje_corto_sin_ruta_no_cambia() -> None:
    mensaje = "Interface > Data type Boo is unknown."

    assert mensaje_corto(mensaje) == mensaje


def test_el_mensaje_corto_sin_resto_no_cambia() -> None:
    """Un paréntesis al final no tiene resto: se devuelve el mensaje entero."""

    assert mensaje_corto("DB5 (DB5)") == "DB5 (DB5)"


def test_localizar_xml_en_plano(tmp_path: Path) -> None:
    (tmp_path / "6_Entidades.xml").write_text("<xml/>", encoding="utf-8")

    assert localizar_xml(tmp_path, "6_Entidades") == tmp_path / "6_Entidades.xml"


def test_localizar_xml_con_la_jerarquia_del_plc(tmp_path: Path) -> None:
    jerarquia = tmp_path / "ZC_PLC_STD" / "6_Entidades"
    jerarquia.mkdir(parents=True)
    (jerarquia / "6_Entidades.xml").write_text("<xml/>", encoding="utf-8")

    assert localizar_xml(tmp_path, "6_Entidades") == jerarquia / "6_Entidades.xml"


def test_localizar_xml_sin_la_tabla_da_el_ruta_plana(tmp_path: Path) -> None:
    """Sin la tabla, la ruta plana del export (que no existe)."""

    assert localizar_xml(tmp_path, "NoExiste") == tmp_path / "NoExiste.xml"


def test_el_mensaje_corto_y_localizar_xml_no_dependen_de_tia() -> None:
    """El modulo comun es puro: no importa nucleo.tia ni tia_ops."""
    import zc_suite.areas.alimentacion.sincronizacion_comun as modulo

    ruta = Path(modulo.__file__)
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    importados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module)
    for importado in importados:
        assert not importado.startswith("zc_suite.nucleo.tia"), importado
        assert not importado.startswith("zc_suite.tia_ops"), importado


def test_las_constantes_de_estado_no_cambian() -> None:
    """Los tres estados son el contrato del faceplate y del mensaje de fallo."""
    assert ESTADO_CONFIRMADA == "confirmada"
    assert ESTADO_REVIRTIDA == "revertida"
    assert ESTADO_NO_EJECUTADA == "no ejecutada"
