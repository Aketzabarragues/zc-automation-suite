"""La lectura del Excel maestro: del ``.xlsx`` a las vistas de la SPA.

El Excel del operario tiene **tablas nombradas**. Cada dominio se lee de su
tabla y sus columnas se renombran a los nombres de campo que usa la SPA.

Criterio de las filas:

- Una celda vacia vale ``""`` (o ``0`` si el campo es numero).
- Una celda con basura donde toca un numero es una **fila mala**: el parseo
  falla con un error que dice la hoja, la tabla y el numero de fila, sin
  traza.
- Una hoja o una tabla que no existe **no** es un error: ese dominio sale
  vacio. Un Excel a medias se ve, no se rompe.

Este modulo es **offline**: no habla con el portal ni importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from zc_suite.areas.alimentacion.excel import tablas
from zc_suite.tia_ops import OperacionError

logger = logging.getLogger(__name__)

#: Campo -> cabeceras del Excel que lo alimentan. La primera que este en la
#: fila gana.
CAMPOS_A_CABECERAS: dict[str, tuple[str, ...]] = {}
for _cabecera, _campo in tablas.CABECERAS.items():
    CAMPOS_A_CABECERAS.setdefault(_campo, ())
    CAMPOS_A_CABECERAS[_campo] = CAMPOS_A_CABECERAS[_campo] + (_cabecera,)


def leer_excel(ruta: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    """Parsea el Excel maestro y devuelve los datos de todas las vistas.

    Args:
        ruta: el fichero ``.xlsx`` a leer.
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict con ``archivo``, ``plcs``, ``configuracion``,
        ``dispositivos``, ``procesos`` y ``entidades``.

    Raises:
        OperacionError: si el fichero no existe o si hay una fila mala.
    """
    path = Path(ruta)
    if not path.is_file():
        raise OperacionError(f"No se encontro el Excel: '{path}'.")

    libro = load_workbook(filename=str(path), read_only=False, data_only=True)
    try:
        plcs = _leer_plcs(libro)
        configuracion = _leer_configuracion(libro, config)
        dispositivos = _leer_dispositivos(libro, config)
        procesos = _leer_procesos(libro, config)
        entidades = _leer_entidades(libro, config)
    finally:
        libro.close()

    return {
        "archivo": path.name,
        "plcs": plcs,
        "configuracion": configuracion,
        "dispositivos": dispositivos,
        "procesos": procesos,
        "entidades": entidades,
    }


# ── lectura de tablas ──────────────────────────────────────────────────────


def _filas(libro: Any, hoja: str, tabla: str) -> list[tuple[int, dict[str, Any]]]:
    """Las filas de una tabla nombrada, con su numero de fila en la hoja.

    Si la hoja o la tabla no existen, devuelve ``[]``.
    """
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


def _texto(bruto: Any) -> str:
    """El texto de una celda. Los vacios se normalizan a ``""``."""
    if bruto is None:
        return ""
    texto = str(bruto).strip()
    if texto.lower() in ("nan", "none", "null"):
        return ""
    return texto


def _entero(bruto: Any) -> int | None:
    """El entero de una celda, o ``None`` si no se puede.

    Una celda vacia vale ``0``. Un texto que no es un numero devuelve
    ``None``: eso es una fila mala.
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
        return None


def _decimal(bruto: Any) -> float | None:
    """El decimal de una celda, o ``None`` si no se puede.

    Acepta coma decimal: el Excel del operario la usa en algunas hojas.
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
        return None


def _valor_de_fila(fila: dict[str, Any], campo: str) -> Any:
    """El valor bruto de un campo en una fila del Excel."""
    for cabecera in CAMPOS_A_CABECERAS.get(campo, ()):
        if cabecera in fila:
            return fila[cabecera]
    return None


def _fila_de_vista(
    columnas: list[str],
    fila: dict[str, Any],
    numero_fila: int,
    hoja: str,
    tabla: str,
) -> dict[str, Any]:
    """Construye la fila de una vista con sus columnas ya casteadas.

    Args:
        columnas: los nombres de campo que se ensenan.
        fila: la fila del Excel, con las cabeceras literales.
        numero_fila: el numero de fila en la hoja.
        hoja: la hoja, para el mensaje de error.
        tabla: la tabla, para el mensaje de error.

    Returns:
        Un dict ``{campo: valor}`` con solo las columnas pedidas.

    Raises:
        OperacionError: si un campo numerico tiene un valor que no es un
            numero.
    """
    salida: dict[str, Any] = {}
    for columna in columnas:
        bruto = _valor_de_fila(fila, columna)
        if columna in tablas.CAMPOS_ENTEROS:
            valor = _entero(bruto)
        elif columna in tablas.CAMPOS_DECIMALES:
            valor = _decimal(bruto)
        else:
            valor = _texto(bruto)
        if valor is None:
            raise OperacionError(
                f"Fila {numero_fila} invalida en la tabla '{tabla}' "
                f"(hoja '{hoja}'): el valor de '{columna}' no es un numero."
            )
        salida[columna] = valor
    return salida


# ── los dominios ───────────────────────────────────────────────────────────


def _leer_plcs(libro: Any) -> list[str]:
    """Los PLCs del Excel.

    Vienen de la tabla de PLCs; si no existe, de la columna ``PLC`` de la
    tabla de N_MAX, que siempre esta.
    """
    nombres: list[str] = []
    for _numero, fila in _filas(libro, tablas.HOJA_CONFIG, tablas.TABLA_PLC):
        nombre = _texto(fila.get("PLC")) or _texto(fila.get("Nombre"))
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    if nombres:
        return nombres
    for _numero, fila in _filas(libro, tablas.HOJA_CONFIG, tablas.TABLA_N_MAX):
        nombre = _texto(fila.get("PLC"))
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return nombres


def _leer_configuracion(libro: Any, config: dict[str, Any]) -> dict[str, Any]:
    """La vista de configuracion: los N_MAX por PLC."""
    columnas = tablas.columnas_de_configuracion(config)
    filas: list[dict[str, Any]] = []
    for numero, fila in _filas(libro, tablas.HOJA_CONFIG, tablas.TABLA_N_MAX):
        plc = _texto(fila.get("PLC"))
        if not plc:
            raise OperacionError(
                f"Fila {numero} invalida en la tabla '{tablas.TABLA_N_MAX}' "
                f"(hoja '{tablas.HOJA_CONFIG}'): no tiene el PLC."
            )
        valores = tablas.valor_n_max_de_fila(fila, config)
        salida: dict[str, Any] = {"PLC": plc}
        for columna in columnas[1:]:
            bruto = valores.get(columna, 0)
            valor = _entero(bruto)
            if valor is None:
                raise OperacionError(
                    f"Fila {numero} invalida en la tabla '{tablas.TABLA_N_MAX}' "
                    f"(hoja '{tablas.HOJA_CONFIG}'): el valor de '{columna}' no es un numero."
                )
            salida[columna] = valor
        filas.append(salida)
    return {"columnas": columnas, "filas": filas}


def _leer_dispositivos(libro: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """La vista de dispositivos: una tabla por tipo, en el orden del config.

    Returns:
        Una lista de tablas ``{"tipo", "columnas", "filas"}``. Es una lista y
        no un diccionario porque el orden de las sub-pestanas lo marca el
        ``config.json``, y el JSON ordena las claves por nombre.
    """
    tablas_dispositivo: list[dict[str, Any]] = []
    for clave in config.get("Dispositivos", {}):
        hoja, tabla, canonico = tablas.destino_de_dispositivo(str(clave), config)
        columnas = tablas.columnas_de_dispositivo(canonico, config)
        filas: list[dict[str, Any]] = []
        for numero, fila in _filas(libro, hoja, tabla):
            filas.append(
                _fila_de_vista(columnas, fila, numero, hoja, tabla)
            )
        if filas:
            logger.debug("Dispositivos %s: %d filas", canonico, len(filas))
        tablas_dispositivo.append(
            {"tipo": canonico, "columnas": columnas, "filas": filas}
        )
    return tablas_dispositivo


def _leer_procesos(libro: Any, config: dict[str, Any]) -> dict[str, Any]:
    """La vista de procesos: cuatro subdominios."""
    procesos: dict[str, Any] = {}
    for clave, hoja, tabla in tablas.SUBDOMINIOS_PROCESOS:
        columnas = tablas.columnas_de_procesos(clave, config)
        filas: list[dict[str, Any]] = []
        for numero, fila in _filas(libro, hoja, tabla):
            filas.append(
                _fila_de_vista(columnas, fila, numero, hoja, tabla)
            )
        procesos[clave] = {"columnas": columnas, "filas": filas}
    return procesos


def _leer_entidades(libro: Any, config: dict[str, Any]) -> dict[str, Any]:
    """La vista de entidades."""
    columnas = tablas.columnas_de_entidades(config)
    filas: list[dict[str, Any]] = []
    for numero, fila in _filas(libro, tablas.HOJA_ENTIDADES, tablas.TABLA_ENTIDADES):
        filas.append(
            _fila_de_vista(columnas, fila, numero, tablas.HOJA_ENTIDADES, tablas.TABLA_ENTIDADES)
        )
    return {"columnas": columnas, "filas": filas}
