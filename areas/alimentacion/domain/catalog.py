"""Catálogo de presentación para alimentar la SPA.

Este módulo es la **fuente de verdad** de:
  - las columnas que muestra cada tipo de dispositivo en
    "Definición programación" (``MODEL_COLUMNS``),
  - las etiquetas humanas de cada columna (``COLUMN_LABELS``),
  - qué columnas se renderizan en monospace (``MONO_COLUMNS``),
  - y los helpers que mapean ``canonical`` (DispED, DispEA, ...)
    a su clase Python para introspección con ``dataclasses.fields``.

Todo lo que antes vivía hardcoded en los JS de
``DefinicionProgramacion.js`` y ``Dispositivos.js`` ahora vive
aquí y se expone al frontend a través del endpoint
``GET /api/v1/catalog``.

Restricciones arquitectónicas:
  - Prohibido importar ``siemens_tia_scripting``.
  - Prohibido el uso de ``Any`` en los atributos declarados.
  - Prohibido depender de openpyxl u otras librerías de
    infraestructura.
  - Prohibido ``dataclasses.fields`` directos en JS — siempre
    pasan por este helper.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from areas.alimentacion.domain.models.dispositivos import (
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
)
from core.infrastructure.config_manager import ConfigManager


# ── Mapping canónica → clase Python ────────────────────────────────────
# Tabla canónica ``canonical → Disp*``. Es la única fuente de verdad
# para el endpoint ``/api/v1/catalog`` y para ``get_columns_for``.
# Añadir un nuevo tipo (p.ej. ``DispSD``) requiere:
#   1. Crear la dataclass en ``models/dispositivos.py``.
#   2. Añadir la entry aquí.
#   3. Configurar la entry en el ``config.json`` (``Dispositivos``
#      y opcionalmente ``excel_target``).
_CANONICAL_TO_CLASS: dict[str, type[Dispositivo]] = {
    "DispED":   DispED,
    "DispEA":   DispEA,
    "DispSA":   DispSA,
    "DispV":    DispV,
    "DispM":    DispM,
    "DispM_VF": DispM_VF,
}


# ── Etiquetas de columna (idioma actual: español) ────────────────────
# Plano: ``col_name → "Label humano"``. Se aplica a todas las
# pestañas; las claves de los dataclasses que NO estén aquí
# caen al fallback ``col_name`` en la SPA.
COLUMN_LABELS: dict[str, str] = {
    "uid":             "UID",
    "numero":          "Número",
    "plc_tag":         "PLC Tag",
    "plc_comentario":  "Comentario PLC",
    "descripcion":     "Descripción",
    "tag":             "TAG",
    "fat":             "FAT",
    "e_byte":          "E.Byte",
    "e_bit":           "E.Bit",
    "s_byte":          "S.Byte",
    "s_bit":           "S.Bit",
    "rr_byte":         "RR.Byte",
    "rr_bit":          "RR.Bit",
    "rt_byte":         "RT.Byte",
    "rt_bit":          "RT.Bit",
    "rm_byte":         "RM.Byte",
    "rm_bit":          "RM.Bit",
    "sa_byte":         "SA.Byte",
    "unidades":        "Unidades",
    "rii":             "RII",
    "rsi":             "RSI",
    "gr_alarma":       "Gr.Alarma",
    "cuadro":          "Cuadro",
    "observaciones":   "Observaciones",
    "plc_tipo":        "PLC.Tipo",
    "plc_index":       "PLC.Index",
    "hmi_index":       "Hmi.Index",
    "hmi_texto":       "Hmi.Texto",
    "comentario_db":   "ComentarioDB",
}


# ── Columnas en monospace (identificadores / códigos) ───────────────
# Set de nombres de campo que se renderizan con ``font-mono`` en
# la SPA (identificadores únicos, sin espacios, que conviene
# alinear visualmente).
MONO_COLUMNS: frozenset[str] = frozenset({
    "uid",
    "plc_tag",
    "plc_comentario",
})


# ── API pública ──────────────────────────────────────────────────────


def get_disp_class(canonical: str) -> type[Dispositivo] | None:
    """Devuelve la clase Python asociada a ``canonical`` o ``None``."""
    return _CANONICAL_TO_CLASS.get(canonical)


def get_columns_for(canonical: str) -> list[str]:
    """Devuelve la lista de nombres de campo visibles del dataclass.

    Si ``canonical`` no está registrado, retorna ``[]`` (la SPA
    mostrará un mensaje "no hay columnas" en esa pestaña).

    Filtra deliberadamente los campos ``cfg_*`` (strings SCL de
    configuración de la línea ``cfg_* := ...;``) porque la UI
    legacy nunca los mostraba en el Inspector: son
    configuración de PLC, no datos del dispositivo. Si en el
    futuro la SPA los quiere exponer, se hace añadiendo un
    endpoint nuevo (no se relaja este filtro).

    Es la **fuente única** de las columnas de la tabla
    "Definición programación": cualquier campo nuevo ``no cfg``
    que se añada a la dataclass aparece automáticamente en la SPA.
    """
    cls = get_disp_class(canonical)
    if cls is None:
        return []
    return [
        f.name for f in dataclasses.fields(cls)
        if not (f.name.startswith("cfg_"))
    ]


def get_model_columns_map() -> dict[str, list[str]]:
    """Devuelve ``{canonical: [field_name, ...]}`` para TODOS los tipos
    que tengan dataclass registrada.

    Es la versión "bulk" de ``get_columns_for``; el endpoint
    ``/api/v1/catalog`` la usa para emitir el shape completo
    en una sola respuesta.
    """
    return {canon: get_columns_for(canon) for canon in _CANONICAL_TO_CLASS}


# ── Vistas para el endpoint /api/v1/catalog ──────────────────────────


def build_device_tabs(cm: ConfigManager) -> list[dict[str, str]]:
    """Devuelve ``[{hw_type, canonical, label}]`` para el frontend.

    Orden: el de declaración en ``Dispositivos`` del config
    (preserva el orden histórico: ``ed/ea/sa/v/m/m_vf``).
    """
    out: list[dict[str, str]] = []
    for hw in cm.list_hw_types_active():
        target = cm.get_excel_target_for(hw)
        if target is None:
            continue
        canonica = target.get("canonical", "")
        if not canonica:
            continue
        # ``label`` por convención: ``"HW — Descripción"``. Como
        # no tenemos un "description" en el config aún, derivamos
        # el label del ``hw_type`` con la primera letra en
        # mayúscula. Si en el futuro se añade un ``label`` al
        # ``excel_target`` del config, se respeta.
        override_label = target.get("label")
        if isinstance(override_label, str) and override_label.strip():
            label = override_label.strip()
        else:
            label = _default_label_for_hw(hw)
        out.append(
            {"hw_type": hw, "canonical": canonica, "label": label}
        )
    return out


def build_nmax_view(cm: ConfigManager) -> list[dict[str, str]]:
    """Devuelve ``[{name, label}]`` para el frontend (cards de N_MAX).

    ``label`` se deriva del nombre canónico: ``"N_MAX_DISP_ED"``
    → ``"num_disp_ed"``. Si en el futuro se quiere un label
    humano (``"Entradas Digitales"``), se añade al
    ``n_max_catalog[i].label`` del config.
    """
    out: list[dict[str, str]] = []
    for name in cm.list_nmax_active():
        entry = cm.get_nmax_entry(name) or {}
        # Override opcional.
        override = entry.get("display_label")
        if isinstance(override, str) and override.strip():
            label = override.strip()
        else:
            label = _default_label_for_nmax(name)
        out.append({"name": name, "label": label})
    return out


def build_catalog(cm: ConfigManager) -> dict[str, Any]:
    """Empaqueta el payload completo del endpoint ``/api/v1/catalog``.

    Shape (estable; la SPA hace fallback por clave ausente si
    el backend no la expone todavía):

        {
          "device_tabs":     [{hw_type, canonical, label}, ...],
          "nmax":            [{name, label}, ...],
          "model_columns":   {canonical: [field_name, ...], ...},
          "col_labels":      {col_name: "Label humano", ...},
          "mono_cols":       ["uid", "plc_tag", ...]
        }
    """
    return {
        "device_tabs":   build_device_tabs(cm),
        "nmax":          build_nmax_view(cm),
        "model_columns": get_model_columns_map(),
        "col_labels":    dict(COLUMN_LABELS),
        "mono_cols":     sorted(MONO_COLUMNS),
    }


# ── Helpers puros ────────────────────────────────────────────────────


def _default_label_for_hw(hw: str) -> str:
    """``"ed"`` → ``"ED"``; ``"m_vf"`` → ``"MVF"``. Convenção SPA."""
    return hw.replace("_", "").upper()


def _default_label_for_nmax(name: str) -> str:
    """``"N_MAX_DISP_ED"`` → ``"num_disp_ed"``.

    Por qué este label (en vez del nombre canónico): coincide
    con la estética del panel "Definición programación" legacy
    (que mostraba ``num_disp_ed``, ``num_disp_ea``, …). Si en
    el futuro la SPA quiere un label humano, se prefiere
    ``entry.display_label``.
    """
    if name.startswith("N_MAX_DISP_"):
        rest = name[len("N_MAX_DISP_"):]
        return f"num_disp_{rest.lower()}"
    return name


__all__ = [
    "build_catalog",
    "build_device_tabs",
    "build_nmax_view",
    "get_columns_for",
    "get_disp_class",
    "get_model_columns_map",
]
