"""Defaults defensivos del ``ConfigManager`` aportados por el área Alimentación.

Antes de PR 1, ``ConfigManager`` exponía constantes de módulo con los
valores por defecto del departamento de alimentación:

  - ``_DEFAULT_DEPARTMENT = "alimentacion"``
  - ``_DEFAULT_NMAX_CATALOG`` con los 6 N_MAX legacy.
  - ``_DEFAULT_GLOBAL_CONFIG_TABLE_NAME = "000_Config_Dispositivos"``
  - ``_DEFAULT_TIA_FOLDER_PROCESO = "003_Procesos"``
  - ``_DEFAULT_TIA_FOLDER_DISPOSITIVOS = "2000_Dispositivos"``
  - ``_DEFAULT_TIA_FOLDER_NMAX = "000_Sistema"``

PR 1 los eliminó del core (genérico). Este módulo los recupera como
**defaults defensivos** que el área aporta vía
``AreaSpec.contributes_config_defaults``: solo se aplican al bloque
``departments["alimentacion"]`` cuando el JSON no los trae, para
mantener back-compat con instalaciones que aún no migraron a la
estructura multi-área explícita.

Política:
  - **Filtro por ``dept_id``**: la función ``install`` se invoca para
    CADA departamento del JSON. Solo modifica el dict del área de
    alimentación (``dept_id == "alimentacion"``); ignora el resto.
  - **No-op si el JSON ya trae la clave**: la presencia de la clave
    en el JSON significa que el operario (o la migración) la ha
    configurado explícitamente y los defaults no deben pisarla.
"""
from __future__ import annotations

import logging
from typing import Any


_logger: logging.Logger = logging.getLogger(
    f"{__name__}.AlimentacionConfigDefaults"
)


# Identificador del área. Usado como filtro de ``dept_id``.
_DEPT_ID: str = "alimentacion"


# ── Catálogo N_MAX legacy (6 entradas canónicas del área) ────────────
# Se usan solo si ``n_max_catalog`` no está presente en el bloque del
# departamento. Mantener sincronizado con la tabla PLC de
# ``2000_Disp_*`` y con la convención ``N_MAX_DISP_<HW>``.
_DEFAULT_NMAX_CATALOG: list[dict[str, str]] = [
    {"name": "N_MAX_DISP_ED",   "excel_named_range": "Num_Disp_ED",   "hw_type": "ed"},
    {"name": "N_MAX_DISP_EA",   "excel_named_range": "Num_Disp_EA",   "hw_type": "ea"},
    {"name": "N_MAX_DISP_SA",   "excel_named_range": "Num_Disp_SA",   "hw_type": "sa"},
    {"name": "N_MAX_DISP_V",    "excel_named_range": "Num_Disp_V",    "hw_type": "v"},
    {"name": "N_MAX_DISP_M",    "excel_named_range": "Num_Disp_M",    "hw_type": "m"},
    {"name": "N_MAX_DISP_M_VF", "excel_named_range": "Num_Disp_M_VF", "hw_type": "m_vf"},
]


# ── Defaults de carpetas TIA y tabla global ───────────────────────────
_DEFAULT_GLOBAL_CONFIG_TABLE_NAME: str = "000_Config_Dispositivos"
_DEFAULT_TIA_FOLDER_PROCESO: str = "003_Procesos"
_DEFAULT_TIA_FOLDER_DISPOSITIVOS: str = "2000_Dispositivos"
_DEFAULT_TIA_FOLDER_NMAX: str = "000_Sistema"


def install(dept_cfg: dict[str, Any], dept_id: str) -> None:
    """Rellena claves ausentes en el bloque del departamento de alimentación.

    Args:
        dept_cfg: Sub-bloque del departamento bajo ``config.json["departments"]``
                  (se muta in-place).
        dept_id: Identificador del departamento (``"alimentacion"``, etc.).
                 Si no es ``"alimentacion"``, esta función es no-op:
                 los defaults NO se aplican a otros departamentos.

    Notas:
        - Si la clave ya está en ``dept_cfg``, NO se sobrescribe.
        - Tras mutar ``dept_cfg``, el ``ConfigManager`` re-indexa sus
          caches (``_nmax_by_name`` / ``_nmax_by_hw``) por si hemos
          añadido entradas a ``n_max_catalog``.
    """
    if dept_id != _DEPT_ID:
        # Defensa: aunque ``ConfigManager.apply_defaults`` ya pasa
        # ``self._department``, esta función la hace explícita y a
        # prueba de errores del composition root.
        return

    # ── Catálogo N_MAX ──────────────────────────────────────────────
    if "n_max_catalog" not in dept_cfg or not isinstance(
        dept_cfg.get("n_max_catalog"), list
    ):
        _logger.info(
            "Alimentación: 'n_max_catalog' ausente; se aplican los "
            "6 N_MAX legacy como defaults defensivos."
        )
        dept_cfg["n_max_catalog"] = list(_DEFAULT_NMAX_CATALOG)

    # ── Tabla global N_MAX ──────────────────────────────────────────
    if not dept_cfg.get("global_config_table_name"):
        dept_cfg["global_config_table_name"] = _DEFAULT_GLOBAL_CONFIG_TABLE_NAME

    # ── Carpetas TIA ────────────────────────────────────────────────
    tia_folders = dept_cfg.get("tia_folders")
    if not isinstance(tia_folders, dict):
        tia_folders = {}
        dept_cfg["tia_folders"] = tia_folders
    if not tia_folders.get("proceso"):
        tia_folders["proceso"] = _DEFAULT_TIA_FOLDER_PROCESO
    if not tia_folders.get("dispositivos"):
        tia_folders["dispositivos"] = _DEFAULT_TIA_FOLDER_DISPOSITIVOS
    if not tia_folders.get("nmax"):
        tia_folders["nmax"] = _DEFAULT_TIA_FOLDER_NMAX


__all__ = ["install"]
