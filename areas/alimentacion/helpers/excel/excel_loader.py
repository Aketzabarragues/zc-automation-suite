"""Cargador sincrono del Excel corporativo del area de alimentacion.

``ExcelLoader`` abre el workbook UNA sola vez, ejecuta los 19
parsers que lo componen (12 dispositivos + 4 software + 1 N_MAX
+ 1 lista de PLCs + 1 entidades) y construye una ``DataExcelCache``
inmutable con los 3 lookups precomputados por ``codigo``.

Es **sincrono**: corre en un hilo dedicado, no en un event loop. Su
unico caller es ``helpers/excel/excel_upload.py::parse_excel_to_cache``,
a su vez invocado por el FB ``subir_excel``
(``functions/function_excel_cargar.py``) desde el hilo ``plc-ob1``
del OB1.

Pipeline (orden de ejecucion sobre el mismo ``wb``):
    1. 12 parsers de dispositivos (``DispED``/``DispEA``/``DispSA``/
       ``DispSD``/``DispV``/``DispM``/``DispM_VF``/``DispM_SINA``/
       ``DispTQ``/``DispTQ_AE``/``DispTOT``/``DispPID``) — extraen las
       ``ListObject`` de las hojas ``DISP_<HW>``.
    2. 4 parsers de software (``Procesos``/``PReal``/``PInt``/
       ``Alarmas``) — extraen las ``ListObject`` de las hojas
       ``CONFIG``/``P_REAL``/``P_INT``/``ALARMAS``.
    3. 1 parser de N_MAX (``DimensionesParser``) — extrae los
       defined names ``N_MAX_*``/``Num_Disp_*``.
    4. 1 parser de la lista canonica de PLCs (``PLCListParser``) —
       lee la ``Tabla_PLC`` de la hoja ``CONFIG``.
    5. 1 parser de entidades (``EntidadesParser``) —
       extrae la ``Tabla_Entidades`` de la hoja ``ENTIDADES``.
       Multi-PLC (cada ``Entidad`` lleva su ``plc_name``); el
       filtrado por PLC vive en el ``excel_active`` derivado, no aqui.

Tras el parseo, construye los lookups ``*_by_codigo`` filtrando
filas sin ``codigo`` para evitar colisiones con la clave vacia.

Restriccion arquitectonica: este modulo NO importa
``siemens_tia_scripting``. Solo ``openpyxl`` + ``logging`` + DTOs
del subdominio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

# Asegura que ``Logger.web()`` / ``Logger.ok()`` existen aunque el
# modulo se importe fuera del arranque (tests, scripts). Es
# idempotente: si ya estan registrados, no hace nada.
from core.infrastructure.log.log_web_bridge import install_web_level
install_web_level()

from core.data.data_excel_cache import DataExcelCache
from areas.alimentacion.helpers.excel.excel_parser_proc_alarmas import AlarmasParser
from areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones import (
    DimensionesParser,
)
from areas.alimentacion.helpers.excel.excel_parser_disp_ed import DispEDParser
from areas.alimentacion.helpers.excel.excel_parser_disp_ea import DispEAParser
from areas.alimentacion.helpers.excel.excel_parser_disp_m import DispMParser
from areas.alimentacion.helpers.excel.excel_parser_disp_m_sina import DispMSINAParser
from areas.alimentacion.helpers.excel.excel_parser_disp_m_vf import DispM_VFParser
from areas.alimentacion.helpers.excel.excel_parser_disp_pid import DispPIDParser
from areas.alimentacion.helpers.excel.excel_parser_disp_sa import DispSAParser
from areas.alimentacion.helpers.excel.excel_parser_disp_sd import DispSDParser
from areas.alimentacion.helpers.excel.excel_parser_disp_tot import DispTOTParser
from areas.alimentacion.helpers.excel.excel_parser_disp_tq import DispTQParser
from areas.alimentacion.helpers.excel.excel_parser_disp_tq_ae import (
    DispTQ_AEParser,
)
from areas.alimentacion.helpers.excel.excel_parser_disp_v import DispVParser
from areas.alimentacion.helpers.excel.excel_parser_entidades import EntidadesParser
from areas.alimentacion.helpers.excel.excel_parser_plc import PLCListParser
from areas.alimentacion.helpers.excel.excel_parser_proc_pint import PIntParser
from areas.alimentacion.helpers.excel.excel_parser_proc_preal import PRealParser
from areas.alimentacion.helpers.excel.excel_parser_proc_procesos import ProcesosParser
from core.infrastructure.config.config_manager import ConfigManager


_logger = logging.getLogger(__name__)


class ExcelLoader:
    """Carga el Excel corporativo UNA vez y devuelve un ``DataExcelCache``.

    Atributos:
        _config_manager: ``ConfigManager`` opcional inyectado. Si se
            pasa, los 12 parsers de dispositivos lo usan para
            resolver su ``SHEET``/``TABLE`` data-driven.
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager
        # Los 12 parsers de dispositivos (reciben config_manager).
        self._disp_ed = DispEDParser(config_manager=config_manager)
        self._disp_ea = DispEAParser(config_manager=config_manager)
        self._disp_sa = DispSAParser(config_manager=config_manager)
        self._disp_sd = DispSDParser(config_manager=config_manager)
        self._disp_v = DispVParser(config_manager=config_manager)
        self._disp_m = DispMParser(config_manager=config_manager)
        self._disp_m_vf = DispM_VFParser(config_manager=config_manager)
        self._disp_m_sina = DispMSINAParser(config_manager=config_manager)
        self._disp_tq = DispTQParser(config_manager=config_manager)
        self._disp_tq_ae = DispTQ_AEParser(config_manager=config_manager)
        self._disp_tot = DispTOTParser(config_manager=config_manager)
        self._disp_pid = DispPIDParser(config_manager=config_manager)
        # Los 4 parsers de software (no necesitan config_manager:
        # sus hojas/tablas son fijas y no se sobreescriben).
        self._procesos = ProcesosParser()
        self._preal = PRealParser()
        self._pint = PIntParser()
        self._alarmas = AlarmasParser()
        # El parser de N_MAX (puede usar el config_manager).
        self._dimensiones = DimensionesParser(config_manager=config_manager)
        # El parser de la lista canonica de PLCs.
        self._plcs = PLCListParser()

    def load(self, excel_path: str | Path) -> DataExcelCache:
        """Carga el workbook UNA vez, ejecuta los 19 parsers, construye el cache.

        Args:
            excel_path: ruta al ``.xlsx`` a parsear (absoluta o
                relativa; el cache guarda la version ``absolute()``).

        Returns:
            ``DataExcelCache`` inmutable con los 8 dominios del Excel
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

        # Resolución Windows-safe: ``st_mtime_ns`` está disponible en
        # Python 3.7+ y en openpyxl / Windows con precisión de
        # nanosegundos.
        mtime_ns = path.stat().st_mtime_ns
        wb = load_workbook(
            filename=str(path), read_only=False, data_only=True,
        )
        try:
            # -- 6 dispositivos --
            disp_ed = self._disp_ed.extraer(wb)
            disp_ea = self._disp_ea.extraer(wb)
            disp_sa = self._disp_sa.extraer(wb)
            disp_sd = self._disp_sd.extraer(wb)
            disp_v = self._disp_v.extraer(wb)
            disp_m = self._disp_m.extraer(wb)
            disp_m_vf = self._disp_m_vf.extraer(wb)
            disp_m_sina = self._disp_m_sina.extraer(wb)
            disp_tq = self._disp_tq.extraer(wb)
            disp_tq_ae = self._disp_tq_ae.extraer(wb)
            disp_tot = self._disp_tot.extraer(wb)
            disp_pid = self._disp_pid.extraer(wb)
            # -- 4 software --
            procesos = self._procesos.extraer(wb)
            preal = self._preal.extraer(wb)
            pint = self._pint.extraer(wb)
            alarmas = self._alarmas.extraer(wb)
            # -- 1 N_MAX --
            n_max = self._dimensiones.extraer(wb)
            # 1 lista canonica de PLCs.
            plcs = tuple(self._plcs.extraer(wb))
            # 1 entidades (Tabla_Entidades en hoja ENTIDADES).
            # Instantiation inline porque EntidadesParser captura el
            # workbook en __init__ (a diferencia de los disp parsers,
            # que reciben wb por ``extraer(wb)``). Multi-PLC.
            entidades = tuple(EntidadesParser(wb).parse())
        finally:
            wb.close()

        # -- Lookups precomputados por \codigo\ --
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

        # Los 9 tipos concretos (``DispED``/``DispEA``/...) satisfacen
        # estructuralmente el ``Protocol Dispositivo``. Las listas se
        # convierten a tuplas para preservar ``frozen=True`` en el
        # ``DataExcelCache``.
        dispositivos_dict: dict[str, tuple[Dispositivo, ...]] = {
            "ed":     tuple(disp_ed),
            "ea":     tuple(disp_ea),
            "sa":     tuple(disp_sa),
            "sd":     tuple(disp_sd),
            "v":      tuple(disp_v),
            "m":      tuple(disp_m),
            "m_vf":   tuple(disp_m_vf),
            "m_sina": tuple(disp_m_sina),
            "tq":     tuple(disp_tq),
            "tq_ae":  tuple(disp_tq_ae),
            "tot":    tuple(disp_tot),
            "pid":    tuple(disp_pid),
        }

        total_disp = sum(len(t) for t in dispositivos_dict.values())
        total_sw = len(procesos) + len(preal) + len(pint) + len(alarmas)
        _logger.debug(
            f"Excel parseado: {total_disp} disp + {total_sw} software "
            f"+ N_MAX en '{path.name}'"
        )

        return DataExcelCache(
            excel_path=str(path.absolute()),
            excel_mtime_ns=mtime_ns,
            parsed_at=datetime.now(timezone.utc),
            dispositivos=dispositivos_dict,
            n_max=n_max,
            plcs=plcs,
            procesos=tuple(procesos),
            parametros_real=tuple(preal),
            parametros_int=tuple(pint),
            alarmas=tuple(alarmas),
            entidades=entidades,
            procesos_by_codigo=procesos_by_codigo,
            parametros_real_by_codigo=preal_by_codigo,
            parametros_int_by_codigo=pint_by_codigo,
            software_parsers_implemented=True,
        )


__all__ = ["ExcelLoader"]
