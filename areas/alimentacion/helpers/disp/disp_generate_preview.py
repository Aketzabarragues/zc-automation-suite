"""Funciones puras de diff entre desired (Excel) y base (TIA)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.helpers.simatic_ml import PlcUserConstantModifier, PlcUserConstantParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol (no ata al area; cualquier objeto con estos atributos sirve)
# ---------------------------------------------------------------------------


class DispositivoLike(Protocol):
    """Contrato minimo de un dispositivo del Excel."""

    numero: int
    plc_tag: str


# ---------------------------------------------------------------------------
# Dataclass de salida: DiffTable (devices)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffTable:
    """Resultado del diff entre desired (Excel) y base (TIA) para 1 tabla.

    Atributos:
        table_name: nombre de la tabla TIA (``"2000_Disp_ED"``).
        base: ``{uid_str: plc_tag}`` del TIA.
        desired: ``{uid_str: plc_tag}`` del Excel.
        added: uids en desired pero no en base.
        removed: uids en base pero no en desired.
        renamed: ``{uid: (plc_tag_TIA, plc_tag_Excel)}``.
        missing_xml: True si el XML de TIA no existia.
    """

    table_name: str
    base: dict[str, str]
    desired: dict[str, str]
    added: list[str]
    removed: list[str]
    renamed: dict[str, tuple[str, str]]
    missing_xml: bool = False

    @property
    def is_empty(self) -> bool:
        """True si no hay ningun cambio."""
        return not (self.added or self.removed or self.renamed)

    @property
    def n_total_changes(self) -> int:
        """Total de entradas a aplicar en TIA (added + renamed)."""
        return len(self.added) + len(self.renamed)


# ---------------------------------------------------------------------------
# Dataclass de salida: NmaxDiff (N_MAX, valores numericos)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmaxDiff:
    """Resultado del diff de N_MAX entre desired (Excel) y base (TIA).

    Atributos:
        table_name: nombre de la tabla (``"000_Config_Dispositivos"``).
        current: valores del TIA (``{}`` si XML falta).
        desired: valores del Excel (nombres canonicos ``N_MAX_DISP_*``).
        todos: lista de ``{name, actual, nuevo, status}`` por N_MAX.
        summary: ``{actualizar, sin_cambios, total}``.
        missing_xml: True si el XML no existia.
    """

    table_name: str
    current: dict[str, int]
    desired: dict[str, int]
    todos: list[dict[str, Any]]
    summary: dict[str, int]
    missing_xml: bool = False


# ---------------------------------------------------------------------------
# Helpers privados (lectura XML)
# ---------------------------------------------------------------------------


def _read_devices_from_xml(xml_path: Path) -> dict[str, str]:
    """Lee un XML FLAT de ``PlcTagTable`` y devuelve ``{uid_str: plc_tag}``."""
    if not xml_path.is_file():
        return {}
    try:
        modifier = PlcUserConstantModifier(xml_path)
    except Exception as exc:
        logger.warning(
            f"[diff] No se pudo cargar XML de disp '{xml_path.name}': {exc}"
        )
        return {}
    return dict(modifier.read_user_constants_with_uids())


def _read_nmax_from_xml(xml_path: Path) -> tuple[dict[str, int], str | None]:
    """Lee un XML FLAT con N_MAX y devuelve ``(values_dict, error_message)``."""
    if not xml_path.is_file():
        return {}, f"XML de N_MAX no encontrado en TIA export: {xml_path}"
    try:
        values = PlcUserConstantParser.parse_user_constants(xml_path)
        return dict(values), None
    except Exception as exc:
        logger.error(f"[N_MAX] Parse FAIL {xml_path}: {exc}")
        return {}, f"parse fail: {exc}"


# ---------------------------------------------------------------------------
# API publica: compute_diff_table (devices)
# ---------------------------------------------------------------------------


def compute_diff_table(
    table_name: str,
    desired_devices: list[DispositivoLike],
    xml_path: Path,
) -> DiffTable:
    """Calcula el diff entre desired_devices (Excel) y xml_path (TIA).

    Args:
        table_name: nombre de la tabla TIA (solo logs/debug).
        desired_devices: lista de ``DispositivoLike``.
        xml_path: ruta al ``.xml`` FLAT exportado de TIA.

    Returns:
        ``DiffTable`` con los 4 vectores del diff + ``base``.
    """
    desired: dict[str, str] = {}
    for device in desired_devices:
        numero = int(getattr(device, "numero", 0) or 0)
        plc_tag = str(getattr(device, "plc_tag", "") or "")
        if numero > 0 and plc_tag:
            desired[str(numero)] = plc_tag

    base = _read_devices_from_xml(xml_path)
    missing_xml = not xml_path.is_file()

    base_uids = set(base.keys())
    desired_uids = set(desired.keys())

    added = sorted(desired_uids - base_uids)
    removed = sorted(base_uids - desired_uids)
    renamed: dict[str, tuple[str, str]] = {
        uid: (base[uid], desired[uid])
        for uid in (base_uids & desired_uids)
        if base[uid] != desired[uid]
    }

    return DiffTable(
        table_name=table_name,
        base=base,
        desired=desired,
        added=added,
        removed=removed,
        renamed=renamed,
        missing_xml=missing_xml,
    )


# ---------------------------------------------------------------------------
# API publica: compute_nmax_diff (N_MAX)
# ---------------------------------------------------------------------------


def compute_nmax_diff(
    table_name: str,
    desired_nmax: dict[str, int],
    xml_path: Path,
) -> NmaxDiff:
    """Calcula el diff de N_MAX entre desired_nmax (Excel) y xml_path (TIA).

    Args:
        table_name: nombre de la tabla N_MAX.
        desired_nmax: ``{nombre_nmax: valor_deseado}`` del Excel (nombres
            canonicos ``N_MAX_DISP_*``).
        xml_path: ruta al XML FLAT de TIA con las N_MAX.

    Returns:
        ``NmaxDiff`` con ``current``/``desired``/``todos``/``summary``.
    """
    current, error_message = _read_nmax_from_xml(xml_path)
    missing_xml = error_message is not None

    if missing_xml:
        return NmaxDiff(
            table_name=table_name,
            current={},
            desired=dict(desired_nmax),
            todos=[],
            summary={
                "actualizar": 0,
                "sin_cambios": len(desired_nmax),
                "total": len(desired_nmax),
            },
            missing_xml=True,
        )

    todos: list[dict[str, Any]] = []
    for name in desired_nmax.keys():
        cur_val = current.get(name)
        des_val = int(desired_nmax[name])
        if cur_val is not None and int(cur_val) == des_val:
            status = "sin_cambios"
        else:
            status = "actualizar"
        todos.append({
            "name": name,
            "actual": cur_val,
            "nuevo": des_val,
            "status": status,
        })

    return NmaxDiff(
        table_name=table_name,
        current=current,
        desired=dict(desired_nmax),
        todos=todos,
        summary={
            "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
            "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
            "total": len(todos),
        },
        missing_xml=False,
    )


__all__ = [
    "DispositivoLike",
    "DiffTable",
    "NmaxDiff",
    "compute_diff_table",
    "compute_nmax_diff",
]
