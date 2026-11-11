"""La lectura del Excel maestro: del ``.xlsx`` al modelo de la SPA.

El parser es **uno solo** y es data-driven: cada dominio (los doce tipos de
dispositivo, los cuatro de software, las entidades, los PLCs y las
dimensiones) declara donde vive y que campos tiene, y el parser recorre el
modelo.

Criterio de las filas:

- Una celda vacia vale ``""`` (o ``0`` si el campo es numero).
- Una celda con basura donde toca un numero es una **fila mala**: el parseo
  falla con un error que dice la hoja, la tabla y el numero de fila, sin
  traza.
- Una hoja o una tabla que no existe **no** es un error: ese dominio sale
  vacio y con un aviso.

Este modulo es **offline**: no habla con el portal ni importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from zc_suite.areas.alimentacion.excel import columnas as modulo_columnas
from zc_suite.areas.alimentacion.excel import tablas
from zc_suite.areas.alimentacion.excel.modelo import (
    DECIMAL,
    ENTERO,
    NUM_LISTA,
    TEXTO,
    Campo,
    Dominio,
)
from zc_suite.tia_ops import OperacionError

logger = logging.getLogger(__name__)


def leer_excel(ruta: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    """Parsea el Excel maestro y devuelve el modelo completo.

    Args:
        ruta: el fichero ``.xlsx`` o ``.xlsm`` a leer.
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict con ``archivo``, ``plcs``, ``configuracion``,
        ``dispositivos``, ``procesos``, ``entidades`` y ``avisos``. Las filas
        llevan el modelo completo del dominio; las columnas que se ensenan
        las decide el ``display_order`` del ``config.json``.

    Raises:
        OperacionError: si el fichero no existe o si hay una fila mala.
    """
    path = Path(ruta)
    if not path.is_file():
        raise OperacionError(f"No se encontro el Excel: '{path}'.")

    libro = load_workbook(filename=str(path), read_only=False, data_only=True)
    try:
        dispositivos, avisos = _leer_dispositivos(libro, config)
        procesos, avisos_software = _leer_software(libro, config)
        entidades, aviso_entidades = _leer_vista(libro, tablas.ENTIDADES, config)
        plcs, aviso_plcs = _leer_dominio(libro, tablas.PLCS)
        dimensiones, aviso_dimensiones = _leer_dimensiones(libro, config)
    finally:
        libro.close()

    return {
        "archivo": path.name,
        "plcs": plcs,
        "configuracion": dimensiones,
        "dispositivos": dispositivos,
        "procesos": procesos,
        "entidades": entidades,
        "avisos": [
            aviso
            for aviso in [*avisos, *avisos_software, aviso_entidades, aviso_plcs, aviso_dimensiones]
            if aviso
        ],
    }


# ── los dominios ────────────────────────────────────────────────────────────


def _leer_dispositivos(
    libro: Any,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Los doce tipos de dispositivo, en el orden del modelo."""
    vistas: list[dict[str, Any]] = []
    avisos: list[str] = []
    for clave, dominio in tablas.DISPOSITIVOS.items():
        hoja, tabla, canonico = tablas.destino_de_dispositivo(clave, config)
        destino = replace(dominio, hoja=hoja, tabla=tabla)
        registros, aviso = _leer_dominio(libro, destino)
        if aviso:
            avisos.append(aviso)
        columnas = modulo_columnas.columnas_de_dispositivo(canonico, config)
        vistas.append(
            {
                "tipo": canonico,
                "columnas": columnas,
                "etiquetas": modulo_columnas.etiquetas_de("disp", config, columnas),
                "filas": registros,
            }
        )
    return vistas, avisos


def _leer_software(libro: Any, config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Los cuatro dominios del software: procesos, parametros y alarmas."""
    vistas: dict[str, Any] = {}
    avisos: list[str] = []
    for dominio in tablas.SOFTWARE:
        registros, aviso = _leer_dominio(libro, dominio)
        if aviso:
            avisos.append(aviso)
        columnas = modulo_columnas.columnas_de_procesos(dominio.clave, config)
        vistas[dominio.clave] = {
            "columnas": columnas,
            "etiquetas": modulo_columnas.etiquetas_de("proc", config, columnas),
            "filas": registros,
        }
    return vistas, avisos


def _leer_vista(
    libro: Any,
    dominio: Dominio,
    config: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Un dominio suelto, con sus columnas y sus etiquetas."""
    registros, aviso = _leer_dominio(libro, dominio)
    columnas = modulo_columnas.columnas_de_entidades(config)
    return (
        {
            "columnas": columnas,
            "etiquetas": modulo_columnas.etiquetas_de(dominio.catalogo, config, columnas),
            "filas": registros,
        },
        aviso,
    )


def _leer_dimensiones(libro: Any, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Los N_MAX por PLC.

    Las columnas salen del catalogo de N_MAX: cada entrada dice que columna
    del Excel la alimenta y cual es su nombre canonico.
    """
    dominio = tablas.DIMENSIONES
    aviso = ""
    if dominio.hoja not in libro.sheetnames:
        aviso = f"No se encuentra la hoja {dominio.hoja} en el Excel"
    elif not _tiene_tabla(libro, dominio.hoja, dominio.tabla):
        aviso = f"No se encuentra la tabla {dominio.tabla} en la hoja {dominio.hoja}"

    mapa = _mapa_n_max(config)
    columnas = modulo_columnas.columnas_de_configuracion(config)
    filas: list[dict[str, Any]] = []
    if not aviso:
        for numero, fila in _filas(libro, dominio.hoja, dominio.tabla):
            registro = _registro_dimensiones(fila, mapa, dominio, numero)
            if registro is not None:
                filas.append(registro)
    return {"columnas": columnas, "etiquetas": {}, "filas": filas}, aviso


def _mapa_n_max(config: dict[str, Any]) -> dict[str, str]:
    """``{cabecera_normalizada: nombre_canonico}`` de los N_MAX."""
    mapa: dict[str, str] = {}
    for entrada in config.get("n_max_catalog", []):
        columna = str(entrada.get("excel_column", "")).strip()
        nombre = str(entrada.get("name", "")).strip()
        if columna and nombre:
            mapa[columna.upper()] = nombre
    return mapa


def _registro_dimensiones(
    fila: dict[str, Any],
    mapa: dict[str, str],
    dominio: Dominio,
    numero: int,
) -> dict[str, Any] | None:
    """El registro de N_MAX de una fila, o ``None`` si se descarta."""
    plc = _texto(fila.get("PLC"))
    if not plc:
        return None
    registro: dict[str, Any] = {"PLC": plc}
    leidos = 0
    for cabecera, valor in fila.items():
        canonico = mapa.get(str(cabecera).strip().upper())
        if canonico is None:
            continue
        registro[canonico] = _entero_estricto(valor, dominio, numero, cabecera)
        leidos += 1
    if tablas.COLUMNA_N_MAX_ENTIDADES in fila:
        registro[tablas.N_MAX_ENTIDADES] = _entero_estricto(
            fila[tablas.COLUMNA_N_MAX_ENTIDADES], dominio, numero, tablas.COLUMNA_N_MAX_ENTIDADES
        )
        leidos += 1
    if not leidos:
        return None
    return registro


# ── la lectura de una tabla ─────────────────────────────────────────────────


def _leer_dominio(libro: Any, dominio: Dominio) -> tuple[list[dict[str, Any]], str]:
    """Los registros de un dominio y el aviso si su tabla no esta.

    Args:
        libro: el workbook abierto.
        dominio: el dominio a leer.

    Returns:
        La tupla ``(registros, aviso)``. El aviso va vacio si la tabla
        existe.
    """
    if dominio.hoja not in libro.sheetnames:
        return [], f"No se encuentra la hoja {dominio.hoja} en el Excel"
    if not _tiene_tabla(libro, dominio.hoja, dominio.tabla):
        return [], f"No se encuentra la tabla {dominio.tabla} en la hoja {dominio.hoja}"

    registros: list[dict[str, Any]] = []
    for numero, fila in _filas(libro, dominio.hoja, dominio.tabla):
        registro = _registro(fila, dominio, numero)
        if registro is not None:
            registros.append(registro)
    return registros, ""


def _registro(fila: dict[str, Any], dominio: Dominio, numero: int) -> dict[str, Any] | None:
    """El registro de una fila del dominio, o ``None`` si se descarta.

    Las filas se descartan por las reglas del dominio (sin UID, sin PLC...),
    igual que en ``main``. Los descartes no son errores: una fila mala si
    es cuando un numero no se puede leer.
    """
    crudos = {campo.nombre: _bruto(fila, campo) for campo in dominio.campos}
    if _se_descarta(crudos, dominio):
        return None
    return {
        campo.nombre: _valor(
            crudo=crudos[campo.nombre],
            campo=campo,
            dominio=dominio,
            numero=numero,
        )
        for campo in dominio.campos
    }


def _se_descarta(crudos: dict[str, Any], dominio: Dominio) -> bool:
    """Si la fila se descarta por las reglas del dominio."""
    if dominio.descartar_si_vacias and all(
        _vacio(crudos.get(campo)) for campo in dominio.descartar_si_vacias
    ):
        return True
    if any(_vacio(crudos.get(campo)) for campo in dominio.exigir_no_vacias):
        return True
    if dominio.exigir_plc and _vacio(crudos.get("plc_name")):
        return True
    return any(
        _entero_suave(crudos.get(campo)) < 0 for campo in dominio.exigir_no_negativo
    )


def _tiene_tabla(libro: Any, hoja: str, tabla: str) -> bool:
    """Si la hoja tiene la tabla nombrada."""
    if hoja not in libro.sheetnames:
        return False
    tablas_hoja = getattr(libro[hoja], "tables", None) or {}
    return tabla in tablas_hoja


def _filas(libro: Any, hoja: str, tabla: str) -> list[tuple[int, dict[str, Any]]]:
    """Las filas de una tabla nombrada, con su numero de fila en la hoja."""
    if hoja not in libro.sheetnames:
        return []
    hoja_obj = libro[hoja]
    tablas_obj = getattr(hoja_obj, "tables", None) or {}
    tabla_obj = tablas_obj.get(tabla)
    if tabla_obj is None:
        return []
    ref = getattr(tabla_obj, "ref", None)
    if not isinstance(ref, str) or ":" not in ref:
        return []
    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
    except (ValueError, TypeError):
        return []

    cabeceras = next(
        hoja_obj.iter_rows(
            min_row=min_row,
            max_row=min_row,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        )
    )
    nombres = [
        str(valor).strip() if valor is not None and str(valor).strip() else ""
        for valor in cabeceras
    ]

    filas: list[tuple[int, dict[str, Any]]] = []
    for desplazamiento, fila in enumerate(
        hoja_obj.iter_rows(
            min_row=min_row + 1,
            max_row=max_row,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        )
    ):
        if fila is None or all(celda is None for celda in fila):
            continue
        valores = {
            nombre: valor
            for nombre, valor in zip(nombres, fila, strict=False)
            if nombre
        }
        if valores:
            filas.append((min_row + 1 + desplazamiento, valores))
    return filas


# ── los valores ─────────────────────────────────────────────────────────────


def _bruto(fila: dict[str, Any], campo: Campo) -> Any:
    """El valor bruto de un campo en la fila.

    Gana la primera cabecera que este en la fila. Un valor ``None`` no
    cuenta: se sigue mirando la siguiente cabecera.
    """
    for cabecera in campo.cabeceras():
        if cabecera in fila and fila[cabecera] is not None:
            return fila[cabecera]
    return None


def _valor(crudo: Any, campo: Campo, dominio: Dominio, numero: int) -> Any:
    """El valor de un campo, con su tipo."""
    if campo.tipo == ENTERO:
        return _entero_estricto(crudo, dominio, numero, campo.cabeceras()[0])
    if campo.tipo == DECIMAL:
        return _decimal_estricto(crudo, dominio, numero, campo.cabeceras()[0])
    if campo.tipo == NUM_LISTA:
        return _num_lista(crudo)
    if campo.tipo == TEXTO:
        return _texto(crudo)
    return _texto(crudo)


def _texto(bruto: Any) -> str:
    """El texto de una celda. Los vacios se normalizan a ``""``."""
    if bruto is None:
        return ""
    texto = str(bruto).strip()
    if texto.lower() in ("nan", "none", "null"):
        return ""
    return texto


def _vacio(bruto: Any) -> bool:
    """Si un valor bruto esta vacio."""
    if bruto is None:
        return True
    texto = str(bruto).strip()
    return texto == "" or texto.lower() in ("nan", "none", "null")


def _entero_suave(bruto: Any) -> int:
    """El entero de una celda, o ``0`` si no se puede."""
    if bruto is None:
        return 0
    if isinstance(bruto, bool):
        return int(bruto)
    if isinstance(bruto, int):
        return bruto
    texto = str(bruto).strip()
    if texto == "" or texto.lower() in ("nan", "none", "null"):
        return 0
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return int(float(texto))
    except ValueError:
        return 0


def _entero_estricto(bruto: Any, dominio: Dominio, numero: int, cabecera: str) -> int:
    """El entero de una celda.

    Raises:
        OperacionError: si la celda no es un numero.
    """
    if bruto is None:
        return 0
    if isinstance(bruto, bool):
        return int(bruto)
    if isinstance(bruto, int):
        return bruto
    texto = str(bruto).strip()
    if texto == "" or texto.lower() in ("nan", "none", "null"):
        return 0
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return int(float(texto))
    except ValueError:
        raise OperacionError(
            f"Fila {numero} invalida en la tabla '{dominio.tabla}' "
            f"(hoja '{dominio.hoja}'): el valor de '{cabecera}' no es un numero."
        ) from None


def _decimal_estricto(bruto: Any, dominio: Dominio, numero: int, cabecera: str) -> float:
    """El decimal de una celda.

    Acepta coma decimal: el Excel del operario la usa en algunas hojas.

    Raises:
        OperacionError: si la celda no es un numero.
    """
    if bruto is None:
        return 0.0
    if isinstance(bruto, bool):
        return float(bruto)
    if isinstance(bruto, (int, float)):
        return float(bruto)
    texto = str(bruto).strip().replace(",", ".")
    if texto == "" or texto.lower() in ("nan", "none", "null"):
        return 0.0
    try:
        return float(texto)
    except ValueError:
        raise OperacionError(
            f"Fila {numero} invalida en la tabla '{dominio.tabla}' "
            f"(hoja '{dominio.hoja}'): el valor de '{cabecera}' no es un numero."
        ) from None


def _num_lista(bruto: Any) -> int | str:
    """El indice de lista de una celda.

    La columna ``Num.Lista`` del Excel puede traer un numero (el indice de
    la lista del HMI) o un texto (``"N/A"``, ``"TODOS"``): el texto se
    conserva tal cual.
    """
    texto = _texto(bruto)
    if not texto:
        return 0
    try:
        return int(float(texto))
    except ValueError:
        return texto
