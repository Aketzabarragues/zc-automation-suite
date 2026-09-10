"""areas.alimentacion.data.data_ProcSlotMap — Data Block de slot maps de procesos.

Fase 3, paso 3.2.9.  Migrado de ``areas/alimentacion/application/proc_slot_map_builder.py``
(que define el dataclass ``ProcSlotMap`` con 12 campos).

Slot maps y metadatos TIA para un proceso.  Es el hermano "procesos"
de ``DataDispSlotMap`` (paso 3.2.8) que cubre los 6 DBs de
dispositivos ED/EA/SA/V/M/M_VF.  Las diferencias:
  - Sin slot 0.  Los arrays de proceso empiezan en 1.
  - Parametrizado por array (no por hw_type).
  - 3 arrays por proceso (PReal, PInt, ALM) en lugar de 1.
  - Cruza con ``BloqueCache`` para verificar que el DB/tabla existen
    en el PLC.  Faltan -> ``missing_blocks`` poblado, NO aborta.

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.3: borrar
``areas/alimentacion/infrastructure/`` / ``application/``).
"""
from __future__ import annotations

from dataclasses import dataclass, field


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


__all__ = ["DataProcSlotMap"]
