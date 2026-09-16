"""areas.alimentacion.data.data_ProcSlotMap ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒ¢Ã¢â€šÂ¬Ã‚Â Data Block de slot maps de procesos.

Fase 3, paso 3.2.9.  Migrado de ``areas/alimentacion/application/proc_slot_map_builder.py``
(que define el dataclass ``DataProcSlotMap`` con 12 campos). El builder
``proc_build_slot_maps`` se fusiono aqui mismo (sept-2026) para que el
area solo tenga la familia ``data_*`` como punto de entrada publico.

Slot maps y metadatos TIA para un proceso.  Es el hermano "procesos"
de ``DataDispSlotMap`` (paso 3.2.8) que cubre los 6 DBs de
dispositivos ED/EA/SA/V/M/M_VF.  Las diferencias:
  - Sin slot 0.  Los arrays de proceso empiezan en 1.
  - Parametrizado por array (no por hw_type).
  - 3 arrays por proceso (PReal, PInt, ALM) en lugar de 1.
  - Cruza con ``BloqueCache`` para verificar que el DB/tabla existen
    en el PLC.  Faltan -> ``missing_blocks`` poblado, NO aborta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from areas.alimentacion.helpers.sd.proc_comment_updater import (
    strip_enclosing_quotes,
)
from core.runtime.app_state import AppState
from core.infrastructure.config.config_manager import ConfigManager
from core.infrastructure.tia.tia_export_paths import EMPTY_TEXT
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataProcSlotMap:
    """Slot maps y metadatos TIA para un proceso.

    Atributos:
      - ``preal`` / ``pint`` / ``alm``: ``{slot: comentario}`` para los
        3 arrays del proceso (1-based).  Vacios si no hay parametros
        o si ``missing_blocks`` esta poblado.
      - ``db_param_name``: nombre canonico del DB de parametros
        (``"DB<num_db>_<codigo>_PARAM"``).
      - ``db_alm_name``: nombre canonico del DB de alarmas
        (``"DB<num_db>_<codigo>_ALM"``).
      - ``table_name``: nombre canonico de la tabla de variables
        (``"<uid>_<codigo>"``).
      - ``param_subpath`` / ``alm_subpath``: subcarpeta TIA de cada DB
        dentro de "Bloques de programa".  Se extrae del
        ``BloquePLC.ruta`` cacheado al escanear TIA.  Si la cache no
        tiene la ruta, queda ``""`` y el worker escribe los archivos
        a la raiz de ``exports/`` (legacy).
      - ``nmax``: ``{kind: desired_int}`` con los valores DESEADOS de
        las PlcUserConstant N_MAX del proceso, donde ``kind in
        {"preal", "pint", "alm"}``.
      - ``nmax_names``: ``{kind: full_name}`` con los nombres
        completos ya computados (``"100_N_MAX_PREAL"``).
      - ``missing_blocks``: lista de mensajes describiendo los bloques
        ausentes en el ``BloqueCache``.  Vacia si todo esta presente.
      - ``warnings``: lista de warnings no fatales.
    """

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = ""
    db_alm_name: str = ""
    table_name: str = ""
    param_subpath: str = ""
    alm_subpath: str = ""
    nmax: dict[str, int] = field(default_factory=dict)
    nmax_names: dict[str, str] = field(default_factory=dict)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE).

        Convierte los ``int`` slots a ``str`` (JSON-friendly).
        """
        return {
            "preal": {str(k): v for k, v in self.preal.items()},
            "pint": {str(k): v for k, v in self.pint.items()},
            "alm": {str(k): v for k, v in self.alm.items()},
            "db_param_name": self.db_param_name,
            "db_alm_name": self.db_alm_name,
            "table_name": self.table_name,
            "param_subpath": self.param_subpath,
            "alm_subpath": self.alm_subpath,
            "nmax": dict(self.nmax),
            "nmax_names": dict(self.nmax_names),
            "missing_blocks": list(self.missing_blocks),
            "warnings": list(self.warnings),
        }


# ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ Helpers internos ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬


def _resolve_num_db(
    parametros: list,  # Iterable[DataParamRealPLC | DataParamIntPLC | DataAlarmaPLC]
    codigo: str,
    proc_field: str,
    proc_value: str,
    proc_uid: int,
    warnings: list[str],
    kind_label: str,
) -> int:
    """Resuelve el ``num_db`` a usar para nombrar el DB de un proceso.

    Politica:
      - Toma la primera fila que cumple el filtro (codigo ==
        proc.codigo o proceso == proc.nombre segun ``kind_label``).
      - Si la lista esta vacia, **fallback documentado**:
        ``num_db = proc.uid`` con warning. Esto preserva la
        convencion legacy donde el DB PARAM se nombraba con
        ``3000 + uid`` cuando no habia filas explicitas en el Excel.
    """
    if proc_field == "codigo":
        filtered = [p for p in parametros if getattr(p, "codigo", "") == codigo]
    else:
        filtered = [
            p for p in parametros if getattr(p, "proceso", "") == proc_value
        ]
    if filtered:
        return int(getattr(filtered[0], "num_db", 0) or 0)
    msg = (
        f"Proceso uid={proc_uid} ({kind_label}): no hay filas en el Excel; "
        f"se usa num_db={proc_uid} como fallback (convencion legacy)."
    )
    warnings.append(msg)
    _logger.warning(msg)
    return proc_uid


def _build_slot_map(
    parametros: list, proc_field: str, proc_value: str, warnings: list[str]
) -> dict[int, str]:
    """Construye ``{i+1: comentario_db}`` 1-based.

    Politica de comentarios vacios: si ``comentario_db`` es "" o
    ``None``, se mapea a ``"."`` (convencion TIA "sin comentario")
    con warning al logger.
    """
    if proc_field == "codigo":
        filtered = [p for p in parametros if getattr(p, "codigo", "") == proc_value]
    else:
        filtered = [
            p for p in parametros if getattr(p, "proceso", "") == proc_value
        ]
    slot_map: dict[int, str] = {}
    for i, p in enumerate(filtered):
        comentario = str(getattr(p, "comentario_db", "") or "")
        comentario = strip_enclosing_quotes(comentario)
        if not comentario.strip():
            _logger.warning(
                f"Parametro sin comentario_db (Excel vacio); "
                f"se mapea a '.' (indice {i + 1})."
            )
            comentario = EMPTY_TEXT
        slot_map[i + 1] = comentario
    return slot_map


# ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ API publica ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚¢Ãƒ¢Ã¢â€šÂ¬Ã‚ÂÃƒ¢Ã¢â‚¬Å¡Ã‚Â¬


def proc_build_slot_maps(
    app_state: AppState,
    config_manager: ConfigManager,
    proc_uid: int,
    bloques_cache: DataBloqueCache,
) -> DataProcSlotMap:
    """Cruza Excel + DataBloqueCache + config para producir los slot maps.

    Raises:
        RuntimeError: si ``app_state.excel_cache`` es ``None`` o si
                      ``proc_uid`` no esta en ``excel_cache.procesos``.
                      Mensaje accionable: "Cargue primero el Excel
                      con POST /api/v1/excel/upload" o
                      "El proceso {uid} no esta en el Excel cargado".

    Politica de precondiciones:
      - Si falta alguno de los 3 bloques (DB_PARAM, DB_ALM, tabla)
        en el ``DataBloqueCache``, la funcion añade el nombre a
        ``missing_blocks`` y retorna con los 3 dicts vacios
        (NO lanza). La SPA pinta el aviso y bloquea la vista de diff.
    """
    excel_cache = app_state.excel_cache
    if excel_cache is None:
        raise RuntimeError(
            "excel_cache esta vacio. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )

    proc = None
    for p in excel_cache.procesos:
        if int(p.uid) == int(proc_uid):
            proc = p
            break
    if proc is None:
        raise RuntimeError(
            f"El proceso con uid={proc_uid} no esta en el Excel cargado. "
            "Recargue el Excel o seleccione otro proceso."
        )

    warnings: list[str] = []

    # Nombres canonicos TIA.
    num_db_param = _resolve_num_db(
        list(excel_cache.parametros_real),
        codigo=proc.codigo,
        proc_field="codigo",
        proc_value=proc.codigo,
        proc_uid=proc_uid,
        warnings=warnings,
        kind_label="PReal/PInt",
    )
    db_param_name = f"DB{num_db_param}_{proc.codigo}_PARAM"

    num_db_alm = _resolve_num_db(
        list(excel_cache.alarmas),
        codigo=proc.codigo,
        proc_field="proceso",
        proc_value=proc.nombre,
        proc_uid=proc_uid,
        warnings=warnings,
        kind_label="ALM",
    )
    db_alm_name = f"DB{num_db_alm}_{proc.codigo}_ALM"

    table_name = f"{proc_uid}_{proc.codigo}"

    missing_blocks: list[str] = []
    if DataBloquePLC.normalize_name(db_param_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de parametros: {db_param_name}")
    if DataBloquePLC.normalize_name(db_alm_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de alarmas: {db_alm_name}")
    if DataBloquePLC.normalize_name(table_name) not in bloques_cache.tag_tables:
        missing_blocks.append(f"Tabla de variables: {table_name}")

    def _extract_subpath(key: str) -> str:
        val = bloques_cache.blocks.get(key, "")
        if isinstance(val, str):
            return val
        return getattr(val, "ruta", "")

    param_key = DataBloquePLC.normalize_name(db_param_name)
    param_subpath = _extract_subpath(param_key)
    alm_key = DataBloquePLC.normalize_name(db_alm_name)
    alm_subpath = _extract_subpath(alm_key)

    if missing_blocks:
        return DataProcSlotMap(
            preal={}, pint={}, alm={},
            db_param_name=db_param_name,
            db_alm_name=db_alm_name,
            table_name=table_name,
            param_subpath=param_subpath,
            alm_subpath=alm_subpath,
            missing_blocks=missing_blocks,
            warnings=warnings,
        )

    preal = _build_slot_map(
        list(excel_cache.parametros_real),
        proc_field="codigo",
        proc_value=proc.codigo,
        warnings=warnings,
    )
    pint = _build_slot_map(
        list(excel_cache.parametros_int),
        proc_field="codigo",
        proc_value=proc.codigo,
        warnings=warnings,
    )
    alm = _build_slot_map(
        list(excel_cache.alarmas),
        proc_field="proceso",
        proc_value=proc.nombre,
        warnings=warnings,
    )

    suffixes = config_manager.get_proc_nmax_suffixes()
    nmax_desired: dict[str, int] = {}
    nmax_names: dict[str, str] = {}
    if suffixes:
        nmax_desired["preal"] = len(preal)
        nmax_desired["pint"] = len(pint)
        nmax_desired["alm"] = len(alm)
        for kind, suffix in suffixes.items():
            nmax_names[kind] = f"{proc_uid}_N_MAX_{suffix}"

    return DataProcSlotMap(
        preal=preal,
        pint=pint,
        alm=alm,
        db_param_name=db_param_name,
        db_alm_name=db_alm_name,
        table_name=table_name,
        param_subpath=param_subpath,
        alm_subpath=alm_subpath,
        nmax=nmax_desired,
        nmax_names=nmax_names,
        missing_blocks=missing_blocks,
        warnings=warnings,
    )


__all__ = ["DataProcSlotMap", "proc_build_slot_maps"]
