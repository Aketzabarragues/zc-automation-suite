"""Cargador síncrono del Excel corporativo del subdominio alimentación.

``ExcelLoader`` abre el workbook UNA sola vez, ejecuta los 11
parsers que lo componen (6 dispositivos + 4 software + 1 N_MAX) y
construye una ``ExcelCache`` inmutable con los 3 lookups
precomputados por ``codigo``.

Es **síncrono** (no async) porque la apertura del workbook con
openpyxl es CPU/IO-bound y bloquearía el event loop de asyncio.
Los callers (router FastAPI, MCP tool) lo invocan con
``asyncio.to_thread(loader.load, path)`` para no bloquear el event
loop.

Pipeline (orden de ejecución sobre el mismo ``wb``):
    1. 6 mini parsers de dispositivos (``DispED``/``EA``/``SA``/``V``
       /``M``/``M_VF``) — extaen las ``ListObject`` de las hojas
       ``DISP_<HW>``.
    2. 4 parsers de software (``Procesos``/``PReal``/``PInt``/
       ``Alarmas``) — extraen las ``ListObject`` de las hojas
       ``CONFIGURACION``/``P_REAL``/``P_INT``/``ALARMAS``.
    3. 1 parser de N_MAX (``DimensionesParser``) — extrae los
       defined names ``N_MAX_*``/``Num_Disp_*``.

Tras el parseo, construye los lookups ``*_by_codigo`` filtrando
filas sin ``codigo`` para evitar colisiones con la clave vacía.

Restricción arquitectónica: este módulo NO importa
``siemens_tia_scripting``. Solo ``openpyxl`` + ``logging`` + DTOs
del subdominio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from areas.alimentacion.domain.models.excel_cache import (
    Dispositivo,
    ExcelCache,
)
from areas.alimentacion.infrastructure.parsers.alarmas import AlarmasParser
from areas.alimentacion.infrastructure.parsers.dimensiones import (
    DimensionesParser,
)
from areas.alimentacion.infrastructure.parsers.disp_ed import DispEDParser
from areas.alimentacion.infrastructure.parsers.disp_ea import DispEAParser
from areas.alimentacion.infrastructure.parsers.disp_m import DispMParser
from areas.alimentacion.infrastructure.parsers.disp_m_vf import DispM_VFParser
from areas.alimentacion.infrastructure.parsers.disp_sa import DispSAParser
from areas.alimentacion.infrastructure.parsers.disp_v import DispVParser
from areas.alimentacion.infrastructure.parsers.pint import PIntParser
from areas.alimentacion.infrastructure.parsers.preal import PRealParser
from areas.alimentacion.infrastructure.parsers.procesos import ProcesosParser
from core.infrastructure.config_manager import ConfigManager


_logger = logging.getLogger(__name__)


class ExcelLoader:
    """Carga el Excel corporativo UNA vez y devuelve un ``ExcelCache``.

    Atributos:
        _config_manager: ``ConfigManager`` opcional inyectado. Si se
            pasa, los 6 mini parsers de dispositivos lo usan para
            resolver su ``SHEET``/``TABLE`` data-driven.
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager
        # Los 6 parsers de dispositivos (reciben config_manager).
        self._disp_ed = DispEDParser(config_manager=config_manager)
        self._disp_ea = DispEAParser(config_manager=config_manager)
        self._disp_sa = DispSAParser(config_manager=config_manager)
        self._disp_v = DispVParser(config_manager=config_manager)
        self._disp_m = DispMParser(config_manager=config_manager)
        self._disp_m_vf = DispM_VFParser(config_manager=config_manager)
        # Los 4 parsers de software (no necesitan config_manager:
        # sus hojas/tablas son fijas y no se sobreescriben).
        self._procesos = ProcesosParser()
        self._preal = PRealParser()
        self._pint = PIntParser()
        self._alarmas = AlarmasParser()
        # El parser de N_MAX (puede usar el config_manager).
        self._dimensiones = DimensionesParser(config_manager=config_manager)

    def load(self, excel_path: str | Path) -> ExcelCache:
        """Carga el workbook UNA vez, ejecuta los 11 parsers, construye el cache.

        Args:
            excel_path: ruta al ``.xlsx`` a parsear (absoluta o
                relativa; el cache guarda la versión ``absolute()``).

        Returns:
            ``ExcelCache`` inmutable con los 10 dominios del Excel
            y los 3 lookups precomputados por ``codigo``.

        Raises:
            FileNotFoundError: si el archivo no existe.

        Note:
            Si un parser lanza, el workbook se cierra en el
            ``finally`` (no se filtra el handle). El error se
            propaga al caller tras el cleanup.
        """
        path = Path(excel_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"No se encontró el Excel: '{path}'"
            )

        # Resolución Windows-safe (R3 del plan): ``st_mtime_ns``
        # está disponible en Python 3.7+ y en openpyxl / Windows
        # con precisión de nanosegundos.
        mtime_ns = path.stat().st_mtime_ns
        wb = load_workbook(
            filename=str(path), read_only=False, data_only=True,
        )
        try:
            # ── 6 dispositivos ───────────────────────────────────────
            disp_ed = self._disp_ed.extraer(wb)
            disp_ea = self._disp_ea.extraer(wb)
            disp_sa = self._disp_sa.extraer(wb)
            disp_v = self._disp_v.extraer(wb)
            disp_m = self._disp_m.extraer(wb)
            disp_m_vf = self._disp_m_vf.extraer(wb)
            # ── 4 software ───────────────────────────────────────────
            procesos = self._procesos.extraer(wb)
            preal = self._preal.extraer(wb)
            pint = self._pint.extraer(wb)
            alarmas = self._alarmas.extraer(wb)
            # ── 1 N_MAX ──────────────────────────────────────────────
            n_max = self._dimensiones.extraer(wb)
        finally:
            wb.close()

        # ── Lookups precomputados por ``codigo`` ─────────────────────
        # Filtramos ``codigo`` vacío para no contaminar el dict con
        # un valor clave="" que pise accidentalmente otras entradas
        # válidas.
        procesos_by_codigo = {
            p.codigo: p for p in procesos if p.codigo
        }
        preal_by_codigo = {
            p.codigo: p for p in preal if p.codigo
        }
        pint_by_codigo = {
            p.codigo: p for p in pint if p.codigo
        }

        # Los 6 tipos concretos (``DispED``/``DispEA``/...) satisfacen
        # estructuralmente el ``Protocol Dispositivo``. Las listas se
        # convierten a tuplas para preservar ``frozen=True`` en el
        # ``ExcelCache``.
        dispositivos_dict: dict[str, tuple[Dispositivo, ...]] = {
            "ed":    tuple(disp_ed),
            "ea":    tuple(disp_ea),
            "sa":    tuple(disp_sa),
            "v":     tuple(disp_v),
            "m":     tuple(disp_m),
            "m_vf":  tuple(disp_m_vf),
        }

        return ExcelCache(
            excel_path=str(path.absolute()),
            excel_mtime_ns=mtime_ns,
            parsed_at=datetime.now(timezone.utc),
            dispositivos=dispositivos_dict,
            n_max=n_max,
            procesos=tuple(procesos),
            parametros_real=tuple(preal),
            parametros_int=tuple(pint),
            alarmas=tuple(alarmas),
            procesos_by_codigo=procesos_by_codigo,
            parametros_real_by_codigo=preal_by_codigo,
            parametros_int_by_codigo=pint_by_codigo,
            software_parsers_implemented=True,
        )


__all__ = ["ExcelLoader"]
