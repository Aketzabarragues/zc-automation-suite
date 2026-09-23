"""FB de area: preview de comentarios de un proceso vs PLC (diff read-only).

State machine declarativa sobre la tabla ``STAGES``. Cada step ejecuta
una operacion contra el ``ProcPreviewContext`` compartido entre los 6
ticks. Helpers puros (``_empty_nmax_block``, ``_extract_codigo``,
``_compose_arrays_internal``, ``_compute_summary_internal``) viven en
``areas/alimentacion/helpers/proc/proc_generar_preview.py``.

Hereda directo de ``FunctionBase``.

Runtime params via ``start(**kwargs)``:
  - ``proc_uid`` (int): uid del proceso a previsualizar. Obligatorio.
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      "proc_uid":           int,
      "proc_codigo":        str,
      "precondiciones_ok":  bool,
      "missing_blocks":     list[str],
      "db_param_name":      str,
      "db_alm_name":        str,
      "table_name":         str,
      "arrays":             dict,
      "summary":            dict,
      "nmax":               dict,
      "warnings":           list[str],
    }
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionProcDBGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (comentarios + N_MAX) de un proceso."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Exporta 2 DBs (.s7dcl + .s7res) + parsea N_MAX de 1 tabla.
    # TIA V21 puede tardar 1-3 min en PLCs grandes. 180s cubre holgadamente.
    STEP_TIMEOUT_S: float = 180.0

    # Tabla declarativa de stages. Cada tupla: (idx, "nombre_step",
    # "atributo_metodo_en_el_FB"). El ``run_step`` dispatcha contra
    # esta tabla en vez de un ``match``/``case`` inline, para que el
    # flujo sea legible arriba de la clase y los tests puedan
    # mockear ``fb._stage_N_<nombre>`` directamente.
    #
    # Convencion:
    #   - ``idx`` correlativo, 1-based.
    #   - ``nombre_step`` debe coincidir con ``self.steps[idx]["nombre"]``
    #     (registrado en __init__). Si cambias uno, cambia el otro.
    #   - ``atributo_metodo`` es un metodo del FB (no externo): un cambio
    #     de signatura requiere actualizar este registro.
    STAGES: list[tuple[int, str, str]] = [
        (1, "Validar estado de TIA",          "_stage_1_check_state"),
        (2, "Validar bloques",                "_stage_2_check_blocks"),
        (3, "Construir mapa de slots",        "_stage_3_build_slot_maps"),
        (4, "Calcular diferencias de N_MAX",  "_stage_4_compute_nmax"),
        (5, "Exportar y calcular diferencias", "_stage_5_export_and_diff"),
        (6, "Componer respuesta",             "_stage_6_build_response"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_db_generar_preview",
        titulo: str = "Generar preview de comentarios del proceso",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_state: AppState | None = None,
        bloques_cache: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Validar estado de TIA"},
                {"nombre": "Validar bloques"},
                {"nombre": "Construir mapa de slots"},
                {"nombre": "Calcular diferencias de N_MAX"},
                {"nombre": "Exportar y calcular diferencias"},
                {"nombre": "Componer respuesta"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = (
            build_cache if build_cache is not None
            else Path(os.getcwd()) / ".build_cache"
        )
        # Deps especificas.
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ``bloques_cache`` viene del gateway (``_bloques_cache`` del
        # TIAProcessGateway, poblado por ``scan_plc_blocks``). El router
        # lo inyecta explicitamente porque el FB no tiene acceso directo
        # al gateway.
        self._bloques_cache = bloques_cache
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._proc_uid: int = 0
        # ProcPreviewContext compartido entre los 6 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + proc_uid + crear ctx.

        ``bloques_cache`` puede inyectarse por constructor (test) o
        leerse del singleton ``TIADataBloqueCache._caches`` (dict de
        clase, acceso sync) si el FB se registro en el engine sin esa
        dep (caso comun en prod).
        """
        if self._config is None:
            raise RuntimeError(
                "FunctionProcDBGenerarPreview requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionProcDBGenerarPreview requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionProcDBGenerarPreview.start(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcDBGenerarPreview.start(proc_uid=int) es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._proc_uid = proc_uid

        # Si bloques_cache no se inyecta por constructor, leemos del
        # singleton sync (acceso directo al dict de clase). Esto permite
        # que el FB funcione tanto en tests (inyeccion directa) como
        # en prod (singleton). El FB se re-arranca por cada operacion,
        # asi que un snapshot al start es suficiente.
        if self._bloques_cache is None:
            from core.infrastructure.tia.tia_cache import TIADataBloqueCache
            self._bloques_cache = TIADataBloqueCache._caches.get(
                self._plc_name
            )

        # Crear el ProcPreviewContext que las 6 funciones iran mutando.
        # self._ctx esta declarado en __init__ como None; aqui lo
        # inicializamos con las deps inyectadas + plc_name + proc_uid.
        self._ctx = ProcPreviewContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
            bloques_cache=self._bloques_cache,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando preview del proceso "
            f"{self._proc_uid} en {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``proc_generar_preview``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``ProcPreviewContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        if self._ctx is None:
            raise RuntimeError(
                "ProcPreviewContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name/proc_uid valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los stages se declaran arriba de la clase. Asi el
        # flujo del FB es visible de un vistazo (modo SFC) y los tests
        # pueden mockear ``fb._stage_N_<nombre>`` directamente sin
        # parchear el ``match`` interno.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 3/6").
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                result = handler()
                if hasattr(result, "__await__"):
                    await result
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionProcDBGenerarPreview"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        if self._ctx is None:
            # Error temprano: deps no inyectadas o params ausentes.
            self.result = {
                "precondiciones_ok": False,
                "missing_blocks": [
                    "ProcPreviewContext no inicializado. "
                    "Verifica plc_name y proc_uid."
                ],
                "arrays": {},
                "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                            "eliminados": 0, "sin_cambios": 0},
                "warnings": [],
            }
            return

        self.result = self._ctx.result

        # Log de cierre, igual que hacia el use case legacy.
        s = self._ctx.result.get("summary", {})
        nmax_summary = self._ctx.result.get("nmax", {}).get("summary", {})
        logger.debug(
            f"[{self.nombre}] preview calculado para proceso "
            f"{self._ctx.proc_uid} en {self._ctx.plc_name}: "
            f"{s.get('agregados', 0)} agregar, "
            f"{s.get('renombrados', 0)} renombrar, "
            f"{s.get('eliminados', 0)} eliminar, "
            f"{nmax_summary.get('actualizar', 0)} N_MAX actualizar"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 6 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    def _stage_1_check_state(self) -> None:
        """Valida que ``AppState.excel_cache`` esta cargado.

        Si no lo esta, marca ``self._ctx.excel_loaded = False``. El FB
        inspecciona este flag para devolver el shape de error
        correspondiente (``precondiciones_ok=False``,
        ``missing_blocks=[...]``) en ``_stage_6_done``.
        """
        if self._ctx.app_state is None or self._ctx.app_state.excel_cache is None:
            self._ctx.excel_loaded = False
            return
        self._ctx.excel_loaded = True

    def _stage_2_check_blocks(self) -> None:
        """Valida que el cache de bloques del PLC esta disponible.

        Distinguimos 2 casos de "sin cache":
          1. ``bloques_cache is None`` -> el PLC nunca ha sido escaneado.
          2. ``bloques_cache`` existe pero esta vacio -> estado valido
             pero improbable; el FB lo marca como ``missing_blocks``
             via el slot_map resultante.

        Aqui solo marcamos el flag ``bloques_loaded``; la logica de
        "missing blocks concretos" vive en ``_stage_3_build_slot_maps``.
        """
        self._ctx.bloques_loaded = self._ctx.bloques_cache is not None

    def _stage_3_build_slot_maps(self) -> None:
        """Cruza Excel + ``DataBloqueCache`` via ``proc_build_slot_maps``.

        Si la operacion lanza ``RuntimeError`` (p. ej. uid no existe en
        el Excel, o PLC sin bloques), captura la excepcion y la deja en
        ``self._ctx.slot_map_error`` para que ``_stage_6_done`` la
        muestre al operario. NO abortamos: el helper siempre deja el
        ``ctx`` en estado consistente (slot_map o error, nunca ambos).
        """
        if not self._ctx.excel_loaded or not self._ctx.bloques_loaded:
            # Si ya fallaron checks previos, skip.
            return
        from areas.alimentacion.data.data_ProcSlotMap import proc_build_slot_maps
        try:
            self._ctx.slot_map = proc_build_slot_maps(
                self._ctx.app_state, self._ctx.config_manager, self._ctx.proc_uid, self._ctx.bloques_cache
            )
            self._ctx.slot_map_error = None
        except RuntimeError as exc:
            self._ctx.slot_map = None
            self._ctx.slot_map_error = str(exc)

    async def _stage_4_compute_nmax(self) -> None:
        """Lee los N_MAX del proceso (cards SOLO VISUALES para la SPA).

        Convencion del operario: las PlcUserConstant N_MAX de
        un proceso viven en la **tabla del proceso** (``<uid>_<codigo>``,
        p. ej. ``100_CPR``), en la carpeta TIA ``003_Procesos/``. NO en
        la tabla ``000_Config_Dispositivos``.

        Compara el desired (de ``DataProcSlotMap.nmax``, ``len()`` de las
        listas filtradas del Excel) contra el current (exportando la
        tabla del proceso con ``tia_client.export_plc_tags_xml`` y
        parseando con ``PlcUserConstantParser.parse_user_constants``).

        Mismo shape que el ``nmax_block`` de Dispositivos:
        ``{"current", "desired", "todos", "summary"}``.

        Si el config no aporta ``procesos.n_max_suffixes`` o no hay
        slot_map (fase previa fallo), devuelve un bloque vacio. Si el
        export falla, emite un warning y devuelve ``current={}`` sin
        abortar el preview.
        """
        if self._ctx.slot_map is None or self._ctx.slot_map_error is not None:
            self._ctx.nmax_block = _empty_nmax_block()
            return

        nmax_names = self._ctx.slot_map.nmax_names
        nmax_desired = self._ctx.slot_map.nmax
        if not nmax_names or not nmax_desired:
            self._ctx.nmax_block = _empty_nmax_block()
            return

        from areas.alimentacion.helpers.build_cache import build_cache
        from core.helpers.simatic_ml import PlcUserConstantParser
        from core.infrastructure.tia.tia_export_paths import XmlTarget

        target_dir = build_cache(root=self._ctx.build_cache_root).procesos.preview_variables
        table_name = self._ctx.slot_map.table_name
        plc_name = self._ctx.bloques_cache.plc_name if self._ctx.bloques_cache else ""

        current: dict[str, int] = {}
        try:
            await dispatch_async(
                self._ctx.tia_client,
                "export_plc_tags_xml",
                {
                    "plc_name": plc_name,
                    "target_dir": str(target_dir),
                    "table_names": [table_name],
                },
                timeout_s=120.0,
            )
            try:
                xml_path = XmlTarget(target_dir, table_name).path
                current = PlcUserConstantParser.parse_user_constants(xml_path)
            except FileNotFoundError:
                logger.warning(
                    f"[N_MAX procesos] XML esperado no encontrado en "
                    f"{target_dir} para tabla {table_name}."
                )
        except Exception as exc:
            logger.warning(
                f"[N_MAX procesos] export/parse fallo: {exc}. "
                f"Devolviendo current={{}} para no romper la SPA."
            )
            current = {}

        todos: list[dict[str, Any]] = []
        for kind, name in nmax_names.items():
            cur_val = current.get(name)
            des_val = nmax_desired.get(kind, 0)
            if cur_val is not None and int(cur_val) == int(des_val):
                status = "sin_cambios"
            else:
                status = "actualizar"
            todos.append({
                "kind": kind,
                "name": name,
                "actual": cur_val,
                "nuevo": des_val,
                "status": status,
            })

        self._ctx.nmax_block = {
            "current": {nmax_names[k]: v for k, v in current.items()
                        if k in nmax_names},
            "desired": {nmax_names[k]: nmax_desired[k] for k in nmax_names
                        if k in nmax_desired},
            "todos": todos,
            "summary": {
                "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
                "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
                "total": len(todos),
            },
        }

    async def _stage_5_export_and_diff(self) -> None:
        """Exporta los 2 DBs del proceso y lee los ``es-ES`` actuales.

        Stages internos:
          1. Exporta ``DB_PARAM`` y ``DB_ALM`` a
             ``<build_cache>/alimentacion/proc_db/preview/bloques/``.
          2. Crea un ``ProcCommentUpdater`` por DB (sin slot_map, solo
             para usar ``read_current_comments``) y consulta el
             ``es-ES`` actual de cada slot.
          3. Mutua ``self._ctx.preal_current``, ``self._ctx.pint_current`` y
             ``self._ctx.alm_current``.

        Si el export falla (TIA no responde, permisos, etc.), NO
        abortamos: devolvemos ``current=None`` para todos los arrays y
        emitimos un warning via ``self._ctx.export_error``. El operario ve que
        algo fallo pero el preview sigue siendo util (al menos sabe que
        slots quiere actualizar).
        """
        if self._ctx.slot_map is None or self._ctx.slot_map_error is not None:
            return

        from areas.alimentacion.helpers.build_cache import build_cache
        from core.helpers.simatic_sd import (
            find_array_slots,
            read_current_comments,
        )
        from core.infrastructure.tia.tia_export_paths import SdPair

        work_dir = build_cache(root=self._ctx.build_cache_root).procesos.preview_bloques
        plc_name = (
            self._ctx.bloques_cache.plc_name
            if self._ctx.bloques_cache is not None
            else ""
        )
        if not plc_name:
            self._ctx.export_error = "DataBloqueCache sin plc_name; no se puede exportar."
            logger.warning(self._ctx.export_error)
            return

        # Separamos export/read de PARAM y de ALM para distinguir:
        #   - ambos OK: parse normal
        #   - uno falla: warning + seguimos con el otro (modo degradado)
        #   - ambos fallan: self._ctx.export_error poblado (modo error)
        param_error: str | None = None
        alm_error: str | None = None
        dcl_param_text = ""
        res_param_text = ""
        dcl_alm_text = ""
        res_alm_text = ""

        # 1a. Export + read DB_PARAM.
        try:
            await dispatch_async(
                self._ctx.tia_client,
                "export_block",
                {
                    "plc_name": plc_name,
                    "block_name": self._ctx.slot_map.db_param_name,
                    "target_dir": str(work_dir),
                },
                timeout_s=120.0,
            )
            dcl_param_path = SdPair(work_dir, self._ctx.slot_map.db_param_name).dcl
            res_param_path = SdPair(work_dir, self._ctx.slot_map.db_param_name).res
            dcl_param_text = dcl_param_path.read_text(encoding="utf-8-sig") \
                if dcl_param_path.exists() else ""
            res_param_text = res_param_path.read_text(encoding="utf-8-sig") \
                if res_param_path.exists() else ""
            if not dcl_param_text or not res_param_text:
                param_error = f"export OK pero archivos vacios para {self._ctx.slot_map.db_param_name}"
        except Exception as exc:
            param_error = f"export/parse {self._ctx.slot_map.db_param_name}: {exc}"

        # 1b. Export + read DB_ALM.
        try:
            await dispatch_async(
                self._ctx.tia_client,
                "export_block",
                {
                    "plc_name": plc_name,
                    "block_name": self._ctx.slot_map.db_alm_name,
                    "target_dir": str(work_dir),
                },
                timeout_s=120.0,
            )
            dcl_alm_path = SdPair(work_dir, self._ctx.slot_map.db_alm_name).dcl
            res_alm_path = SdPair(work_dir, self._ctx.slot_map.db_alm_name).res
            dcl_alm_text = dcl_alm_path.read_text(encoding="utf-8-sig") \
                if dcl_alm_path.exists() else ""
            res_alm_text = res_alm_path.read_text(encoding="utf-8-sig") \
                if res_alm_path.exists() else ""
            if not dcl_alm_text or not res_alm_text:
                alm_error = f"export OK pero archivos vacios para {self._ctx.slot_map.db_alm_name}"
        except Exception as exc:
            alm_error = f"export/parse {self._ctx.slot_map.db_alm_name}: {exc}"

        # 2. Decidir que reportar segun cuantos DBs fallaron.
        if param_error and alm_error:
            # Ambos fallaron: error. El operario debe investigar.
            logger.error(
                f"_stage_5_export_and_diff: ambos DBs fallaron. "
                f"PARAM={param_error!r}; ALM={alm_error!r}"
            )
            self._ctx.preal_current = None
            self._ctx.pint_current = None
            self._ctx.alm_current = None
            self._ctx.export_error = f"PARAM: {param_error}; ALM: {alm_error}"
            return

        if param_error:
            logger.warning(
                f"_stage_5_export_and_diff: solo DB_PARAM fallo "
                f"({param_error}). Sigo con ALM."
            )
            self._ctx.preal_current = None
            self._ctx.pint_current = None
            # ALM: parsear abajo.
        if alm_error:
            logger.warning(
                f"_stage_5_export_and_diff: solo DB_ALM fallo "
                f"({alm_error}). Sigo con PARAM."
            )
            self._ctx.alm_current = None
            # PARAM: parsear abajo.

        # 3. Parsear comentarios de los DBs que NO fallaron.
        if not param_error:
            # Slots a leer: los del Excel + los que tienen asignacion
            # en el ``.s7dcl`` (slots de TIA no en el Excel -> "eliminar"
            # en el preview). Si el ``.s7dcl`` no existe, ``find_array_slots``
            # devuelve set() y solo se leen los del Excel (modo degradado).
            preal_slots = (
                set(self._ctx.slot_map.preal.keys())
                | find_array_slots(dcl_param_text, "PReal", "UDT")
            )
            pint_slots = (
                set(self._ctx.slot_map.pint.keys())
                | find_array_slots(dcl_param_text, "PInt", "UDT")
            )
            self._ctx.preal_current = read_current_comments(
                res_param_text, "PReal", sorted(preal_slots),
                dcl_param_text, "UDT",
            )
            self._ctx.pint_current = read_current_comments(
                res_param_text, "PInt", sorted(pint_slots),
                dcl_param_text, "UDT",
            )
        if not alm_error:
            alm_slots = (
                set(self._ctx.slot_map.alm.keys())
                | find_array_slots(dcl_alm_text, "ALM", "Simple")
            )
            self._ctx.alm_current = read_current_comments(
                res_alm_text, "ALM", sorted(alm_slots),
                dcl_alm_text, "Simple",
            )

        self._ctx.export_error = None

    def _stage_6_build_response(self) -> None:
        """Compone el ``self._ctx.result`` con el shape legacy de la SPA.

        Inspecciona los flags del ctx (excel_loaded, bloques_loaded,
        slot_map_error, slot_map.missing_blocks) para decidir el shape:

          - Sin Excel -> respuesta vacia + missing_blocks con hint.
          - Sin bloques -> respuesta vacia + missing_blocks con hint.
          - slot_map error -> respuesta vacia + missing_blocks con error.
          - Missing blocks en PLC -> respuesta vacia + missing_blocks
            concretos del slot_map.
          - Happy path -> arrays completos + nmax + warnings.
          - Export fallido (current=None) -> happy path con warnings
            adicionales (el operario ve que algo fallo pero el preview
            sigue siendo util).

        Esta funcion es la UNICA del FB que escribe ``self._ctx.result``.
        El ``on_finish`` lo vuelca a ``self.result``.
        """
        empty_summary = {
            "total": 0, "agregados": 0, "renombrados": 0,
            "eliminados": 0, "sin_cambios": 0,
        }

        if not self._ctx.excel_loaded:
            self._ctx.result = {
                "proc_uid": self._ctx.proc_uid,
                "precondiciones_ok": False,
                "missing_blocks": [
                    "AppState no tiene Excel cargado. Cargue el Excel con "
                    "POST /api/v1/excel/upload."
                ],
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": [],
            }
            return

        if not self._ctx.bloques_loaded:
            self._ctx.result = {
                "proc_uid": self._ctx.proc_uid,
                "precondiciones_ok": False,
                "missing_blocks": [
                    "Cache de bloques del PLC no disponible. "
                    "Selecciona el PLC en el sidebar y espera al "
                    "escaneo de bloques (1-3 min en PLCs grandes)."
                ],
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": [],
            }
            return

        if self._ctx.slot_map is None or self._ctx.slot_map_error is not None:
            self._ctx.result = {
                "proc_uid": self._ctx.proc_uid,
                "precondiciones_ok": False,
                "missing_blocks": [
                    self._ctx.slot_map_error or "Error construyendo slot maps"
                ],
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": [],
            }
            return

        if self._ctx.slot_map.missing_blocks:
            self._ctx.result = {
                "proc_uid": self._ctx.proc_uid,
                "proc_codigo": _extract_codigo(self._ctx.slot_map.db_param_name),
                "precondiciones_ok": False,
                "missing_blocks": self._ctx.slot_map.missing_blocks,
                "db_param_name": self._ctx.slot_map.db_param_name,
                "db_alm_name": self._ctx.slot_map.db_alm_name,
                "table_name": self._ctx.slot_map.table_name,
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": self._ctx.slot_map.warnings,
            }
            return

        # Happy path: compose arrays + summary, merge warnings.
        arrays = _compose_arrays_internal(
            self._ctx.slot_map, self._ctx.preal_current, self._ctx.pint_current, self._ctx.alm_current
        )
        summary = _compute_summary_internal(arrays)
        warnings = list(self._ctx.slot_map.warnings)
        if self._ctx.export_error:
            warnings.append(f"Export fallo: {self._ctx.export_error}. current=None.")

        self._ctx.result = {
            "proc_uid": self._ctx.proc_uid,
            "proc_codigo": _extract_codigo(self._ctx.slot_map.db_param_name),
            "precondiciones_ok": True,
            "missing_blocks": [],
            "db_param_name": self._ctx.slot_map.db_param_name,
            "db_alm_name": self._ctx.slot_map.db_alm_name,
            "table_name": self._ctx.slot_map.table_name,
            "arrays": arrays,
            "summary": summary,
            "nmax": self._ctx.nmax_block,
            "warnings": warnings,
        }



@dataclass
class ProcPreviewContext:
    """Estado compartido entre las funciones de ``proc_generate_preview``.

    Cada funcion toma un ``ProcPreviewContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionProcDBGenerarPreview`` instancia uno y lo reusa entre sus 6
    ticks para que los resultados intermedios esten disponibles para
    las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    proc_uid: int
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path
    bloques_cache: Any  # DataBloqueCache o None

    # ── Resultado de proc_check_state ──
    excel_loaded: bool = True

    # ── Resultado de proc_check_blocks ──
    bloques_loaded: bool = True

    # ── Resultado de proc_build_slot_maps ──
    slot_map: Any = None  # DataProcSlotMap o None
    slot_map_error: str | None = None

    # ── Resultado de proc_compute_nmax ──
    nmax_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultado de proc_export_and_diff ──
    preal_current: "dict[int, str | None] | None" = None
    pint_current: "dict[int, str | None] | None" = None
    alm_current: "dict[int, str | None] | None" = None
    export_error: str | None = None

    # ── Resultado de proc_compose_response (shape legacy final) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Internals puras (no mutan ctx; reciben los datos como args)
# ===========================================================================

def _empty_nmax_block() -> dict[str, Any]:
    """Shape de nmax_block cuando no hay config o falla el slot_map."""
    return {
        "current": {},
        "desired": {},
        "todos": [],
        "summary": {
            "actualizar": 0, "sin_cambios": 0, "total": 0,
        },
    }


def _extract_codigo(db_param_name: str) -> str:
    """Extrae el ``codigo`` del nombre de DB (``DB53100_CPR_PARAM``
    -> ``"CPR"``). Devuelve ``""`` si el formato no encaja."""
    parts = db_param_name.split("_")
    if len(parts) >= 2:
        return parts[1]
    return ""


def _compose_arrays_internal(
    slot_map: Any,
    preal_current: "dict[int, str | None] | None",
    pint_current: "dict[int, str | None] | None",
    alm_current: "dict[int, str | None] | None",
) -> dict[str, Any]:
    """Compone el dict ``arrays`` con los 3 arrays del proceso.

    Para cada slot, generamos una entrada ``{current, desired,
    action}`` con ``action in {"sin_cambios", "renombrar",
    "agregar", "eliminar"}``.

    Slots del Excel (``slot_map_dict``):
      - Si se pasan los mapas ``*_current``: ``current`` es el
        ``es-ES`` real de TIA y ``action``:
          - ``"agregar"`` si el slot no existe en TIA (``current
            is None``) -> el apply lo creara.
          - ``"renombrar"`` si ``current != desired``.
          - ``"sin_cambios"`` si ``current == desired``.
      - Si los mapas son ``None`` (export degradado): ``action``
        se infiere del desired (``"."`` -> "agregar", otro ->
        "renombrar").

    Slots de TIA NO en el Excel (``current_dict - slot_map_dict``):
      - Caso "eliminar". El slot existe en TIA con un comentario
        historico pero el operario no lo tiene en su Excel
        (p. ej. compactado de 60 slots donde el Excel solo trae
        los 20 que el operario quiere gestionar). El apply
        resetea el comentario a ``"."`` (convencion TIA "sin
        comentario"). Si el current es ``""`` (ya vacio),
        ``action = "sin_cambios"``.
    """
    arrays: dict[str, Any] = {}
    satellites_by_array = slot_map.satellites_by_array
    for arr_name, slot_map_dict, db_name, current_dict in (
        ("PReal", slot_map.preal, slot_map.db_param_name, preal_current),
        ("PInt", slot_map.pint, slot_map.db_param_name, pint_current),
        ("ALM", slot_map.alm, slot_map.db_alm_name, alm_current),
    ):
        satellites = satellites_by_array.get(arr_name.lower(), ())
        slot_map_serialized: dict[str, Any] = {}
        # Slots del Excel: comparar desired vs current.
        for slot, desired in slot_map_dict.items():
            if current_dict is not None:
                current = current_dict.get(slot)
                if current is None:
                    action = "agregar"
                elif current == desired:
                    action = "sin_cambios"
                else:
                    action = "renombrar"
            else:
                current = None
                action = "agregar" if desired == "." else "renombrar"
            slot_map_serialized[str(slot)] = {
                "current": current,
                "desired": desired,
                "action": action,
            }
        # Slots de TIA NO en el Excel: "eliminar".
        if current_dict is not None:
            excel_slots = set(slot_map_dict.keys())
            tia_slots = set(current_dict.keys())
            to_remove = sorted(tia_slots - excel_slots)
            for slot in to_remove:
                current = current_dict[slot]
                if current is None or current == "":
                    # Slot vacio en TIA, no hay nada que borrar.
                    action = "sin_cambios"
                else:
                    action = "eliminar"
                slot_map_serialized[str(slot)] = {
                    "current": current,
                    "desired": None,
                    "action": action,
                }
        arrays[arr_name] = {
            "db_name": db_name,
            "array_name": arr_name,
            "satellite_arrays": satellites,
            "current_count": len(current_dict) if current_dict is not None else 0,
            "desired_count": len(slot_map_dict),
            "slot_map": slot_map_serialized,
        }
    return arrays


def _compute_summary_internal(arrays: dict[str, Any]) -> dict[str, int]:
    """Suma el total de slots y cuenta por tipo de accion.

    Shape del dict (alineado con ``sync_dispositivos_instances``):
    ``agregados``, ``renombrados``, ``eliminados``, ``sin_cambios``,
    ``total``.
    """
    total = 0
    agregados = 0
    renombrados = 0
    eliminados = 0
    sin_cambios = 0
    for arr in arrays.values():
        for entry in arr.get("slot_map", {}).values():
            total += 1
            action = entry.get("action")
            if action == "agregar":
                agregados += 1
            elif action == "renombrar":
                renombrados += 1
            elif action == "eliminar":
                eliminados += 1
            elif action == "sin_cambios":
                sin_cambios += 1
    return {
        "total": total,
        "agregados": agregados,
        "renombrados": renombrados,
        "eliminados": eliminados,
        "sin_cambios": sin_cambios,
    }


__all__ = ["FunctionProcDBGenerarPreview", "ProcPreviewContext"]


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "check_state":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.excel_loaded else 'Excel no cargado'}"
        )
    if step_nombre == "check_blocks":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.bloques_loaded else 'Sin cache de bloques'}"
        )
    if step_nombre == "build_slot_maps":
        if ctx.slot_map is None:
            return (
                f"{step_nombre}: "
                f"error: {ctx.slot_map_error or 'sin slot_map'}"
            )
        return (
            f"{step_nombre}: PReal={len(ctx.slot_map.preal)} "
            f"PInt={len(ctx.slot_map.pint)} ALM={len(ctx.slot_map.alm)}"
        )
    if step_nombre == "compute_nmax":
        nmax_summary = ctx.nmax_block.get("summary", {})
        return (
            f"{step_nombre}: {nmax_summary.get('actualizar', 0)} N_MAX "
            f"actualizar, {nmax_summary.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "export_and_diff":
        if ctx.export_error:
            return f"{step_nombre}: error: {ctx.export_error}"
        s = ctx.result.get("summary", {})
        return (
            f"{step_nombre}: {s.get('total', 0)} slots: "
            f"{s.get('renombrados', 0)} renombrar, "
            f"{s.get('agregados', 0)} agregar, "
            f"{s.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "done":
        return f"{step_nombre}: preview compuesto"
    return f"{step_nombre}: OK"
