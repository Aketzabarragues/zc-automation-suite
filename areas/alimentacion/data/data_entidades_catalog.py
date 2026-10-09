"""Catalogo de presentacion del feature ENTIDADES.

Fuente de verdad de que columnas muestra la SPA para el DTO ``Entidad``
(``DB6_ENT.ENT``). Igual patron que ``data_proc_catalog.py`` para
los 4 dominios de software, pero aqui solo hay un dominio
(``entidades``) porque el DTO no se ramifica por tipo.

Se expone al frontend via ``GET /api/v1/catalog`` con prefijo
``ent_*`` (mismo mecanismo que ``proc_*``; ver ``test_catalog.py``).

Restricciones arquitectonicas:
  - Prohibido importar ``siemens_tia_scripting``.
  - Prohibido el uso de ``Any`` en los atributos declarados.
  - Prohibido depender de openpyxl u otras librerias de
    infraestructura.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from areas.alimentacion.data.data_entidades import Entidad


@dataclass(frozen=False)
class DataEntidadesCatalog:
    """Snapshot del catalogo de entidades para la SPA."""

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
            "col_labels":    dict(self.col_labels),
            "mono_cols":     list(self.mono_cols),
            "display_order": {
                dom: list(cols) for dom, cols in self.display_order.items()
            },
        }


# Mapping dominio -> clase Python. Es la unica fuente de verdad
# para ``get_columns_for`` y ``get_model_columns_map``.
_DOMAIN_TO_CLASS: dict[str, type] = {
    "entidades": Entidad,
}


# Etiquetas humanas (idioma actual: espanol). Se aplican al
# unico dominio; las claves no presentes caen al fallback
# ``col_name`` en la SPA.
COLUMN_LABELS: dict[str, str] = {
    "numero":         "Numero",
    "plc_name":       "PLC",
    "plc_tag":        "PLC.Tag",
    "plc_tipo":       "PLC.Tipo",
    "plc_index":      "PLC.Index",
    "plc_comentario": "PLC.Comentario",
    "descripcion":    "Descripcion",
}


# Columnas en monospace (identificadores / codigos).
MONO_COLUMNS: frozenset[str] = frozenset({
    "numero",
    "plc_name",
    "plc_tag",
    "plc_tipo",
    "plc_index",
})


# Orden visible por dominio. Contrato: una columna aparece en
# la SPA si y solo si esta en la lista de su dominio. Cambiar
# el orden = reordenar la lista; ocultar = quitarla de la lista.
DISPLAY_ORDER: dict[str, list[str]] = {
    "entidades": [
        "plc_name",
        "numero",
        "descripcion",
        "plc_tag",
        "plc_tipo",
        "plc_index",
        "plc_comentario",
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
    """``{domain: [field_name, ...]}`` para todos los dominios."""
    return {dom: get_columns_for(dom) for dom in _DOMAIN_TO_CLASS}


def build_entidades_catalog(config_manager=None) -> dict:
    """Empaqueta el payload del catalog de entidades con prefijo ``ent_``.

    El endpoint ``GET /api/v1/catalog`` hace flat merge de las areas,
    por lo que las claves del catalog de disp (sin prefijo), del de
    software (con prefijo ``proc_``) y del de entidades no pueden
    colisionar. Aqui se anteponen ``ent_``.

    Shape (estable; la SPA hace fallback por clave ausente si el
    backend no la expone todavia):

        {
          "ent_model_columns": {domain: [field_name, ...], ...},
          "ent_col_labels":    {col_name: "Label humano", ...},
          "ent_mono_cols":     ["numero", "plc_tag", ...],
          "ent_display_order": {domain: [col_name_in_order, ...], ...},
        }

    Si se aporta, ``config_manager`` aplica los overrides de
    ``display_order`` y ``col_labels`` desde el ``config.json``
    (ver ``ConfigManager.get_entidades_display_order_override`` y
    ``get_entidades_col_labels_override``). Override por dominio
    reemplaza su entrada (visibilidad explicita: el operario pone
    la lista completa que quiere ver).
    """
    display_order: dict[str, list[str]] = {
        dom: list(cols) for dom, cols in DISPLAY_ORDER.items()
    }
    col_labels: dict[str, str] = dict(COLUMN_LABELS)
    if config_manager is not None:
        override_do = _get_display_order_override(config_manager)
        if override_do:
            display_order = {**display_order, **override_do}
        override_cl = _get_col_labels_override(config_manager)
        if override_cl:
            col_labels = {**col_labels, **override_cl}
    return {
        "ent_model_columns": get_model_columns_map(),
        "ent_col_labels":    col_labels,
        "ent_mono_cols":     sorted(MONO_COLUMNS),
        "ent_display_order": display_order,
    }


def _get_display_order_override(config_manager) -> dict[str, list[str]]:
    """Lee y valida el override de ``display_order`` del config_manager.

    Devuelve ``{domain: [col, ...]}`` solo con entradas validas. Las
    claves desconocidas (dominios que no existen o columnas que no
    son campos del DTO) se descartan con warning.
    """
    raw = config_manager.get_entidades_display_order_override()
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for domain, cols in raw.items():
        if domain not in _DOMAIN_TO_CLASS:
            import logging
            logging.getLogger(__name__).warning(
                "entidades_display_order override: dominio '%s' desconocido; "
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
                "entidades_display_order override: dominio '%s' ignora columnas "
                "desconocidas %s (campos validos: %s)",
                domain, descartados, sorted(dto_fields),
            )
        if cols_validos:
            out[domain] = cols_validos
    return out


def _get_col_labels_override(config_manager) -> dict[str, str]:
    """Lee y valida el override de ``col_labels`` del config_manager.

    Devuelve ``{col_name: "Label humano"}`` solo con entradas validas
    (la clave debe ser un campo del DTO y el valor un string no vacio).
    Las claves que empiezan por ``_`` se ignoran silenciosamente:
    convencion para meter docstrings (``_comment``) en el ``config.json``
    sin contaminar el dict de overrides.
    """
    raw = config_manager.get_entidades_col_labels_override()
    if not raw or not isinstance(raw, dict):
        return {}
    all_dto_fields = {
        f.name for cls in _DOMAIN_TO_CLASS.values()
        for f in dataclasses.fields(cls)
    }
    out: dict[str, str] = {}
    for col, label in raw.items():
        if not isinstance(col, str):
            continue
        if col.startswith("_"):
            continue
        if col not in all_dto_fields:
            import logging
            logging.getLogger(__name__).warning(
                "entidades_col_labels override: columna '%s' desconocida; "
                "se ignora. Campos validos: %s",
                col, sorted(all_dto_fields),
            )
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        out[col] = label.strip()
    return out


__all__ = [
    "DataEntidadesCatalog",
    "build_entidades_catalog",
    "get_columns_for",
    "get_model_columns_map",
    "COLUMN_LABELS",
    "MONO_COLUMNS",
    "DISPLAY_ORDER",
]