"""Catalogo de presentacion de los 4 dominios de software.

Fuente de verdad de que columnas muestra "Definicion programacion"
para ``procesos``, ``parametros_int``, ``parametros_real`` y
``alarmas``. Los nombres de campo vienen de las dataclasses DTO
en ``data_procesos.py``/``data_parametros_int.py``/
``data_parametros_real.py``/``data_alarmas.py``; este modulo
decide el ORDEN visible y las etiquetas humanas, no la shape
del dato.

Se expone al frontend via ``GET /api/v1/catalog``.

Restricciones arquitectonicas:
  - Prohibido importar ``siemens_tia_scripting``.
  - Prohibido el uso de ``Any`` en los atributos declarados.
  - Prohibido depender de openpyxl u otras librerias de
    infraestructura.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from areas.alimentacion.data.data_alarmas import DataAlarmaPLC
from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.data.data_parametros_real import DataParamRealPLC
from areas.alimentacion.data.data_procesos import DataProcesoPLC


@dataclass(frozen=False)
class DataProcCatalog:
    """Snapshot del catalogo de software para la SPA."""

    model_columns: dict[str, list[str]] = field(default_factory=dict)
    col_labels: dict[str, str] = field(default_factory=dict)
    mono_cols: list[str] = field(default_factory=list)
    display_order: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE)."""
        return {
            "model_columns": {
                dom: list(cols) for dom, cols in self.model_columns.items()
            },
            "col_labels": dict(self.col_labels),
            "mono_cols": list(self.mono_cols),
            "display_order": {
                dom: list(cols) for dom, cols in self.display_order.items()
            },
        }


# Mapping dominio -> clase Python. Es la unica fuente de verdad
# para ``get_columns_for`` y ``get_model_columns_map``.
_DOMAIN_TO_CLASS: dict[str, type] = {
    "procesos":        DataProcesoPLC,
    "parametros_int":  DataParamIntPLC,
    "parametros_real": DataParamRealPLC,
    "alarmas":         DataAlarmaPLC,
}


# Etiquetas humanas (idioma actual: espanol). Se aplican a los
# 4 dominios; las claves no presentes caen al fallback ``col_name``
# en la SPA.
COLUMN_LABELS: dict[str, str] = {
    "uid":            "UID",
    "numero":         "No",
    "nombre":         "Nombre",
    "codigo":         "Codigo",
    "preal":          "PReal",
    "index_preal":    "Idx.PReal",
    "pint":           "PInt",
    "index_pint":     "Idx.PInt",
    "alarmas":        "Alarmas",
    "alm_hmi":        "Alarmas HMI",
    "proceso":        "Proceso",
    "num_db":         "Num.DB",
    "producto":       "Producto",
    "tipo":           "Tipo",
    "descripcion":    "Descripcion",
    "comentario_db":  "ComentarioDB",
    "visibilidad":    "Visibilidad",
    "num_lista":      "Num.Lista",
    "txt_lista":      "Txt.Lista",
    "plc_name":       "PLC",
}


# Columnas en monospace (identificadores / codigos).
MONO_COLUMNS: frozenset[str] = frozenset({
    "uid",
    "numero",
    "codigo",
})


# Orden visible por dominio. Contrato: una columna aparece en
# la SPA si y solo si esta en la lista de su dominio. Cambiar
# el orden = reordenar la lista; ocultar = quitarla de la lista.
# ``model_columns`` sigue siendo "el universo total de campos
# del DTO" para casos donde la SPA quiera mostrarlos todos.
DISPLAY_ORDER: dict[str, list[str]] = {
    "procesos": [
        "uid",
        "codigo",
        "nombre",
        "preal",
        "pint",
        "alarmas",
        "alm_hmi",
    ],
    "parametros_int": [
        "uid",
        "numero",
        "codigo",
        "num_db",
        "num_lista",
        "txt_lista",
        "descripcion",
    ],
    "parametros_real": [
        "uid",
        "numero",
        "codigo",
        "num_db",
        "num_lista",
        "txt_lista",
        "descripcion",
    ],
    "alarmas": [
        "uid",
        "numero",
        "proceso",
        "num_db",
        "descripcion",
        "comentario_db",
    ],
}


def get_columns_for(domain: str) -> list[str]:
    """Devuelve los campos declarados en la dataclass del dominio.

    Universo total (puede incluir campos no listados en
    ``DISPLAY_ORDER``). La SPA normalmente usara ``DISPLAY_ORDER``
    directamente para decidir que renderizar.
    """
    cls = _DOMAIN_TO_CLASS.get(domain)
    if cls is None:
        return []
    return [f.name for f in dataclasses.fields(cls)]


def get_model_columns_map() -> dict[str, list[str]]:
    """``{domain: [field_name, ...]}`` para los 4 dominios."""
    return {dom: get_columns_for(dom) for dom in _DOMAIN_TO_CLASS}


def build_proc_catalog() -> dict:
    """Empaqueta el payload del catalog de software.

    Shape (estable; la SPA hace fallback por clave ausente si el
    backend no la expone todavia):

        {
          "model_columns": {domain: [field_name, ...], ...},
          "col_labels":    {col_name: "Label humano", ...},
          "mono_cols":     ["uid", "numero", ...],
          "display_order": {domain: [col_name_in_order, ...], ...},
        }
    """
    return {
        "model_columns": get_model_columns_map(),
        "col_labels":    dict(COLUMN_LABELS),
        "mono_cols":     sorted(MONO_COLUMNS),
        "display_order": {
            dom: list(cols) for dom, cols in DISPLAY_ORDER.items()
        },
    }


def build_software_catalog(config_manager=None) -> dict:
    """Wrapper con prefijo ``proc_`` para fusionar con el catalog de disp.

    El endpoint ``GET /api/v1/catalog`` hace flat merge de las areas,
    por lo que las claves del catalog de disp y del de software no
    pueden colisionar. Se prefijan con ``proc_``.

    Si se pasa ``config_manager``, aplica el override de
    ``display_order`` desde el ``config.json`` (ver
    ``ConfigManager.get_proc_display_order_override``). Un override
    por dominio reemplaza su entrada en ``DISPLAY_ORDER`` (visibilidad
    explicita: el operario pone la lista completa que quiere ver).
    """
    raw = build_proc_catalog()
    display_order = raw["display_order"]
    if config_manager is not None:
        override = _get_override(config_manager)
        if override:
            display_order = {**display_order, **override}
    return {
        "proc_model_columns": raw["model_columns"],
        "proc_col_labels":    raw["col_labels"],
        "proc_mono_cols":     raw["mono_cols"],
        "proc_display_order": display_order,
    }


def _get_override(config_manager) -> dict[str, list[str]]:
    """Lee y valida el override de ``display_order`` del config_manager.

    Devuelve ``{domain: [col, ...]}`` solo con entradas validas. Las
    claves desconocidas (dominios que no existen o columnas que no
    son campos del DTO) se descartan con warning.
    """
    raw = config_manager.get_proc_display_order_override()
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for domain, cols in raw.items():
        if domain not in _DOMAIN_TO_CLASS:
            import logging
            logging.getLogger(__name__).warning(
                "proc_display_order override: dominio '%s' desconocido; "
                "se ignora. Dominios validos: %s",
                domain, sorted(_DOMAIN_TO_CLASS),
            )
            continue
        if not isinstance(cols, list):
            continue
        dto_fields = {f.name for f in dataclasses.fields(_DOMAIN_TO_CLASS[domain])}
        cols_validos = [c for c in cols if isinstance(c, str) and c in dto_fields]
        descartados = [c for c in cols if c not in dto_fields]
        if descartados:
            import logging
            logging.getLogger(__name__).warning(
                "proc_display_order override: dominio '%s' ignora columnas "
                "desconocidas %s (campos validos: %s)",
                domain, descartados, sorted(dto_fields),
            )
        if cols_validos:
            out[domain] = cols_validos
    return out


__all__ = [
    "DataProcCatalog",
    "build_proc_catalog",
    "build_software_catalog",
    "get_columns_for",
    "get_model_columns_map",
    "COLUMN_LABELS",
    "MONO_COLUMNS",
    "DISPLAY_ORDER",
]