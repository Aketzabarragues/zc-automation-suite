"""Parser Excel específico del subdominio alimentación.

Lee el libro Excel del departamento de alimentación y mapea cada hoja
reconocida (``DispED``, ``DispEA``, ``DispSA``, ``DispV``, ``DispM``,
``DispM_VF``) a una lista de dataclasses inmutables del dominio. Las
hojas desconocidas se ignoran silenciosamente (forward-compatible con
futuras ampliaciones del dominio).

Compone sobre el ``ExcelParser`` genérico (en lugar de heredar) para
evitar un conflicto de varianza de tipos: el padre devuelve
``dict[str, list[dict]]`` (forma cruda) y este parser expone
``dict[str, list[Dispositivo]]`` (forma tipada). La conversión
se realiza en este módulo.

Adicionalmente expone ``extraer_dimensiones()`` que parsea named
ranges ``num_disp_*`` del libro y devuelve una instancia fuertemente
tipada de ``DimensionesDispositivos``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Única dependencia externa: ``openpyxl``.
"""
from __future__ import annotations

import dataclasses
import typing
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from core.alimentacion.models.dispositivos import (
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
)
from infrastructure.parsers.excel_parser import ExcelParser


# Mapeo nombre_hoja -> clase del modelo. Cualquier hoja que NO esté
# aquí se ignora (forward-compatible con futuras ampliaciones).
_SHEET_TYPE_MAP: dict[str, type] = {
    "DispED": DispED,
    "DispEA": DispEA,
    "DispSA": DispSA,
    "DispV": DispV,
    "DispM": DispM,
    "DispM_VF": DispM_VF,
}


# ── Helpers de casteo seguro (defensivos contra NaN / None / tipos mixtos)


def _safe_str(value: Any) -> str:
    """Convierte ``value`` a ``str`` quitando NaN/None/vacíos."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("nan", "none", ""):
        return ""
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    """Convierte ``value`` a ``int`` con fallback defensivo."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convierte ``value`` a ``float`` con fallback defensivo."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Convierte ``value`` a ``bool`` (True solo para literales True)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in ("true", "1", "yes", "si")


class AlimentacionExcelParser:
    """Parser Excel del subdominio alimentación.

    Compone sobre ``ExcelParser`` (no hereda) y expone:

      - ``extraer_dtos(excel_path)``: ``dict[str, list[Dispositivo]]``
      - ``extraer_dimensiones(excel_path)``: ``DimensionesDispositivos``

    Solo procesa hojas declaradas en ``_SHEET_TYPE_MAP``. Las filas
    sin ``plc_tag`` válido se descartan silenciosamente (criterio
    de unicidad del PlcTag en TIA Portal).
    """

    def __init__(self) -> None:
        # Composición: usamos el parser genérico como motor de lectura.
        self._generic_parser = ExcelParser()
        # Copia defensiva para evitar mutaciones accidentales del mapa.
        self._type_map: dict[str, type] = dict(_SHEET_TYPE_MAP)

    # ── DTOs por hoja ──────────────────────────────────────────────────
    def extraer_dtos(
        self, excel_path: str | Path
    ) -> dict[str, list[Dispositivo]]:
        """Lee cada hoja del Excel y devuelve listas tipadas por modelo.

        Returns:
            ``dict[str, list[Dispositivo]]``. Las claves son los
            nombres de hoja reconocidos; los valores son listas de
            dataclasses inmutables (``DispED``, ``DispM``, etc.).

        Raises:
            FileNotFoundError: Si el archivo no existe.
        """
        # 1) Lectura cruda (delegada al parser genérico).
        raw: dict[str, list[dict[str, Any]]] = self._generic_parser.extraer_dtos(
            excel_path
        )
        # 2) Conversión tipada (este módulo).
        return self._convert_to_models(raw)

    # ── Dimensiones (named ranges num_disp_*) ─────────────────────────
    def extraer_dimensiones(
        self, excel_path: str | Path
    ) -> DimensionesDispositivos:
        """Lee named ranges ``num_disp_*`` y devuelve una instancia tipada.

        Returns:
            ``DimensionesDispositivos`` con los 6 contadores. Si un
            campo no existe en el Excel, queda en ``0``.
        """
        path = Path(excel_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo Excel: '{path}'"
            )

        workbook = load_workbook(
            filename=str(path), read_only=True, data_only=True
        )
        try:
            return self._extract_dimensiones(workbook)
        finally:
            workbook.close()

    @staticmethod
    def _extract_dimensiones(workbook: Any) -> DimensionesDispositivos:
        """Lee ``wb.defined_names`` y popula ``DimensionesDispositivos``."""
        defined_names = getattr(workbook, "defined_names", None)
        if defined_names is None:
            return DimensionesDispositivos()

        items: Any = (
            defined_names.items()
            if hasattr(defined_names, "items")
            else []
        )
        result: dict[str, int] = {}
        for name, definition in items:
            if not isinstance(name, str):
                continue
            # ``num_disp_ed`` → atributo ``num_disp_ed`` de DimensionesDispositivos.
            attr = _map_named_range_to_attr(name)
            if attr is None:
                continue
            value = _safe_int(_resolve_named_range_value(definition, workbook))
            result[attr] = value

        return DimensionesDispositivos(**result) if result else DimensionesDispositivos()

    # ── Conversión a modelos (privado) ──────────────────────────────────
    def _convert_to_models(
        self,
        raw: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[Dispositivo]]:
        """Mapea el dict crudo a objetos del dominio por hoja."""
        result: dict[str, list[Dispositivo]] = {}
        for sheet_name, rows in raw.items():
            model_cls = self._type_map.get(sheet_name)
            if model_cls is None:
                # Hoja desconocida: se ignora silenciosamente.
                continue
            devices: list[Dispositivo] = []
            for row in rows:
                device = self._build_device(row, model_cls)
                if device is not None:
                    devices.append(device)
            if devices:
                result[sheet_name] = devices
        return result

    @staticmethod
    def _build_device(
        row: dict[str, Any], model_cls: type
    ) -> Dispositivo | None:
        """Instancia un ``model_cls`` a partir de una fila cruda.

        Returns:
            Instancia del modelo, o ``None`` si la fila carece de
            ``plc_tag`` (campo obligatorio; clave única del PlcTag).
        """
        kwargs = _coerce_row_to_model_kwargs(row, model_cls)
        if not kwargs.get("plc_tag"):
            return None
        return model_cls(**kwargs)  # type: ignore[call-arg]


# ── Helpers de mapeo (privados al módulo) ──────────────────────────────


_DIMENSION_ATTRS: set[str] = {
    "num_disp_ed",
    "num_disp_ea",
    "num_disp_sa",
    "num_disp_v",
    "num_disp_m",
    "num_disp_m_vf",
}


def _map_named_range_to_attr(name: str) -> str | None:
    """Convierte ``num_disp_ed`` → ``num_disp_ed`` (passthrough validado).

    Devuelve ``None`` si el nombre no es un atributo de
    ``DimensionesDispositivos``.
    """
    if name in _DIMENSION_ATTRS:
        return name
    return None


def _resolve_named_range_value(definition: Any, workbook: Any) -> Any:
    """Lee el valor de un ``DefinedName`` resolviendo su hoja y celda."""
    # openpyxl 3.1+: ``attr_text``. Versiones anteriores: ``value``.
    attr_text: Any = getattr(definition, "attr_text", None)
    if not attr_text:
        attr_text = getattr(definition, "value", None)
    if not isinstance(attr_text, str) or "!" not in attr_text:
        return None

    sheet_part, cell_part = attr_text.split("!", 1)
    sheet_name = sheet_part.strip().strip("'").strip('"')
    cell_ref = cell_part.replace("$", "").strip()
    try:
        sheet = workbook[sheet_name]
    except (KeyError, TypeError):
        return None
    try:
        cell = sheet[cell_ref]
    except (KeyError, AttributeError, TypeError):
        return None
    return getattr(cell, "value", None)


def _coerce_row_to_model_kwargs(
    row: dict[str, Any], model_cls: type
) -> dict[str, Any]:
    """Mapea una fila del Excel a kwargs del dataclass, con casteo seguro.

    Usa ``typing.get_type_hints`` para resolver anotaciones forward-ref
    (``from __future__ import annotations``). Solo castea columnas cuyo
    nombre coincide con un campo declarado del dataclass; el resto se
    ignora.
    """
    hints: dict[str, Any] = typing.get_type_hints(model_cls)
    fields = {f.name for f in dataclasses.fields(model_cls)}
    kwargs: dict[str, Any] = {}
    for col_name, value in row.items():
        if col_name not in fields:
            continue
        field_type = hints.get(col_name, str)
        kwargs[col_name] = _coerce_value(value, field_type)
    return kwargs


def _coerce_value(value: Any, field_type: Any) -> Any:
    """Castea ``value`` al tipo declarado del campo."""
    if field_type is str:
        return _safe_str(value)
    if field_type is int:
        return _safe_int(value)
    if field_type is float:
        return _safe_float(value)
    if field_type is bool:
        return _safe_bool(value)
    # Tipo no soportado: devolver tal cual (forward-compatible).
    return value


__all__ = ["AlimentacionExcelParser"]
