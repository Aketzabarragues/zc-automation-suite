"""FB de area: preview de comentarios de un proceso vs PLC (diff read-only).

Cada step se declara con ``@step`` encima de su propio codigo y ejecuta
una operacion contra el ``ProcPreviewContext`` compartido entre los 6
steps. El motor (``core/composition/plc_function_base.py``) los recoge
en orden de definicion y hace el dispatch; cada metodo devuelve su
detail. Helpers puros (``_empty_nmax_block``, ``_extract_codigo``,
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
      "db_present":         {"param": bool, "alm": bool},
      "table_present":      bool,
      "arrays":             dict,
      "summary":            dict,
      "nmax":               dict,
      "warnings":           list[str],
    }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase
from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.helpers.tia.with_plc import with_plc
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.app_cache import AppCache, get_app_cache
from areas.alimentacion._area_id import AREA_ID
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT
from areas.alimentacion.helpers.proc.proc_db_generar_preview import (
    compose_arrays,
    compute_nmax_diff_for_proc,
    compute_proc_slot_diff,
    compute_summary,
    empty_nmax_block,
    extract_codigo,
)

# Asegura que ``Logger.web/ok`` existen (idempotente).
install_web_level()

logger = logging.getLogger(__name__)


class FunctionProcDBGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (comentarios + N_MAX) de un proceso."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Exporta 2 DBs (.s7dcl + .s7res) + parsea N_MAX de 1 tabla.
    # TIA V21 puede tardar 1-3 min en PLCs grandes. 180s cubre holgadamente.
    STEP_TIMEOUT_S: float = 180.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_db_generar_preview",
        titulo: str = "Generar preview de comentarios del proceso",
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
        bloques_cache: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ``bloques_cache`` lo produce ``scan_plc_blocks``
        # (``core.infrastructure.tia.tia_cache``), que despacha el
        # comando ``scan_blocks`` al worker OT
        # (``core.infrastructure.tia.tia_loop``). El router lo inyecta
        # explicitamente; si no lo hace, el FB lo lee del ``AppCache``
        # en ``on_start``. El valor inyectado se guarda aparte para
        # poder volver a el en cada run: si el ``AppCache`` no tiene
        # cache para el PLC pedido, el FB debe quedarse sin cache y no
        # reusar el del run anterior (puede ser de otro PLC).
        self._bloques_cache_injected = bloques_cache
        self._bloques_cache = bloques_cache
        # ZONA 3: estado entre steps.
        self._plc_name: str = ""
        self._proc_uid: int = 0
        # ProcPreviewContext compartido entre los 6 steps. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # Reset del estado de Zona 3
    # ==================================================================

    def reset_run_state(self) -> None:
        """Reinicia el estado de Zona 3 antes de cada ``execute()``.

        Sin esto el FB se queda con el cache de bloques del run anterior
        cuando el ``AppCache`` no tiene cache para el PLC pedido:
        diffearia contra bloques de otro PLC.
        """
        self._bloques_cache = self._bloques_cache_injected

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + proc_uid + crear ctx.

        ``bloques_cache`` se inyecta por constructor (test) o se lee
        de ``app_cache.plc_blocks`` via ``plc_blocks_get`` si el FB
        se registro en el engine sin esa dep (caso comun en prod).
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
                "FunctionProcDBGenerarPreview.execute(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcDBGenerarPreview.start(proc_uid=int) es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._proc_uid = proc_uid

        # Validar contra TIA Portal (fail-late).
        validate_plc_in_tia(self._tia_client, self._plc_name)
        # Validar contra el Excel cargado (multi-PLC).
        validate_plc_in_excel(self._app_cache, self._plc_name, AREA_ID)
        # Propagar al AppCache (defensa redundante con el endpoint).
        with_plc(self._app_cache, self._plc_name, AREA_ID)

        # ``bloques_cache`` puede inyectarse por constructor (test) o
        # leerse del AppCache (acceso sync al dict de estado). Se
        # prioriza el AppCache para que un refresh manual del cache
        # (boton ↻ del sidebar) se refleje en el siguiente arranque del
        # FB. La inyeccion por constructor se respeta solo cuando el
        # AppCache esta vacio (tests que mockean el cache sin popular
        # el contenedor global).
        from core.infrastructure.tia.tia_cache import plc_blocks_get
        singleton_cache = plc_blocks_get(self._app_cache, self._plc_name)
        if singleton_cache is not None:
            self._bloques_cache = singleton_cache

        # Crear el ProcPreviewContext que las 6 funciones iran mutando.
        # self._ctx esta declarado en __init__ como None; aqui lo
        # inicializamos con las deps inyectadas + plc_name + proc_uid.
        self._ctx = ProcPreviewContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_cache=self._app_cache,
            build_cache_root=self._build_cache_root,
            bloques_cache=self._bloques_cache,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando preview del proceso "
            f"{self._proc_uid} en {self._plc_name}"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA.

        Ademas publica el resultado en el AppCache (slot
        ``preview_proc``): el router solo encola el trabajo en el OB1,
        asi que la publicacion tiene que ocurrir aqui, cuando el FB ha
        terminado.
        """
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

        # Log de cierre con el mismo formato que el resto de FBs.
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

        self._publish_result_to_cache()
        logger.ok(
            f"Prevision de proceso '{self._ctx.proc_uid}' en "
            f"'{self._ctx.plc_name}': "
            f"{s.get('agregados', 0)} adds, {s.get('renombrados', 0)} renames, "
            f"{s.get('eliminados', 0)} removes, "
            f"{nmax_summary.get('actualizar', 0)} N_MAX"
        )

    def _publish_result_to_cache(self) -> None:
        """Publica el preview de procesos en el AppCache.

        El AppCache es el canal por el que la SPA se entera: lee este
        slot y lo recibe por SSE (``cache_changed``). El router solo
        encola el trabajo, asi que la publicacion tiene que ocurrir
        aqui, cuando el FB ha terminado.
        """
        from core.runtime.app_cache import get_app_cache
        from core.runtime.area_preview_cache import area_set_preview_proc

        app_cache = get_app_cache()
        area_set_preview_proc(app_cache, "alimentacion", self.result)

    # ==================================================================
    # LOS STEPS
    #
    # Cada ``_stage_N_<slug>`` es un step declarado con ``@step``. El
    # motor los recoge en orden de definicion (que es el orden del
    # flujo) y hace el dispatch. El metodo devuelve su detail.
    # ==================================================================

    @step(
        "Validar estado de TIA",
        descripcion="Valida que el Excel del area este cargado",
    )
    def _stage_1_validar_estado_de_tia(self) -> str:
        """Valida que el cache del Excel esta cargado.

        Multi-PLC: chequea el cache activo del area (filtrado por PLC).

        Si no lo esta, marca ``self._ctx.excel_loaded = False``. El FB
        inspecciona este flag para devolver el shape de error
        correspondiente (``precondiciones_ok=False``,
        ``missing_blocks=[...]``) en ``_stage_6_componer_respuesta``.
        """
        from core.runtime.excel_cache import excel_get_active
        cache = (
            excel_get_active(self._ctx.app_cache, "alimentacion")
            if self._ctx.app_cache is not None else None
        )
        if cache is None:
            self._ctx.excel_loaded = False
            return "Validar estado de TIA: Excel no cargado"
        self._ctx.excel_loaded = True
        return "Validar estado de TIA: OK"

    @step(
        "Validar bloques",
        descripcion="Valida que el cache de bloques del PLC este disponible",
    )
    def _stage_2_validar_bloques(self) -> str:
        """Valida que el cache de bloques del PLC esta disponible.

        Distinguimos 2 casos de "sin cache":
          1. ``bloques_cache is None`` -> el PLC nunca ha sido escaneado.
          2. ``bloques_cache`` existe pero esta vacio -> estado valido
             pero improbable; el FB lo marca como ``missing_blocks``
             via el slot_map resultante.

        Aqui solo marcamos el flag ``bloques_loaded``; la logica de
        "missing blocks concretos" vive en ``_stage_3_construir_mapa_de_slots``.
        """
        self._ctx.bloques_loaded = self._ctx.bloques_cache is not None
        if self._ctx.bloques_loaded:
            return "Validar bloques: OK"
        return "Validar bloques: Sin cache de bloques"

    @step(
        "Construir mapa de slots",
        descripcion="Cruza el Excel con los bloques del PLC y arma los mapas de slots",
    )
    def _stage_3_construir_mapa_de_slots(self) -> str:
        """Cruza Excel + ``DataBloqueCache`` via ``proc_build_slot_maps``.

        Si la operacion lanza ``RuntimeError`` (p. ej. uid no existe en
        el Excel, o PLC sin bloques), captura la excepcion y la deja en
        ``self._ctx.slot_map_error`` para que ``_stage_6_componer_respuesta``
        la muestre al operario. NO abortamos: el helper siempre deja el
        ``ctx`` en estado consistente (slot_map o error, nunca ambos).
        """
        def _detail_error() -> str:
            return (
                f"Construir mapa de slots: "
                f"error: {self._ctx.slot_map_error or 'sin slot_map'}"
            )

        if not self._ctx.excel_loaded or not self._ctx.bloques_loaded:
            # Si ya fallaron checks previos, skip.
            return _detail_error()
        from areas.alimentacion.data.data_proc_slot_map import proc_build_slot_maps
        try:
            self._ctx.slot_map = proc_build_slot_maps(
                self._ctx.app_cache, self._ctx.config_manager, self._ctx.proc_uid, self._ctx.bloques_cache
            )
            self._ctx.slot_map_error = None
        except RuntimeError as exc:
            self._ctx.slot_map = None
            self._ctx.slot_map_error = str(exc)

        if self._ctx.slot_map is None:
            return _detail_error()

        # slot_map_size incluye el slot 0 placeholder "NO USAR"
        # (1 + N_MAX reales). N_MAX es el dato del Excel (sin el
        # placeholder). Mostrar ambos evita confusion: el operario
        # espera N_MAX=PReal (el campo del proceso), no el tamano
        # del slot_map.
        sm = self._ctx.slot_map
        nmax = getattr(sm, "nmax", {}) or {}
        return (
            f"Construir mapa de slots: "
            f"slot_map(PReal={len(sm.preal)}, PInt={len(sm.pint)}, "
            f"ALM={len(sm.alm)}) "
            f"N_MAX(PReal={nmax.get('preal', '?')}, "
            f"PInt={nmax.get('pint', '?')}, "
            f"ALM={nmax.get('alm', '?')})"
        )

    @step(
        "Calcular diferencias de N_MAX",
        descripcion="Compara los N_MAX del Excel con los exportados del PLC",
    )
    def _stage_4_calcular_diferencias_de_n_max(self) -> str:
        """Lee los N_MAX del proceso (cards SOLO VISUALES para la SPA).

        Convencion del operario: las PlcUserConstant N_MAX de
        un proceso viven en la **tabla del proceso** (``<uid>_<codigo>``,
        p. ej. ``100_CPR``), en la carpeta TIA ``0_Procesos/``. NO en
        la tabla ``0_Config_Dispositivos``.

        Compara el desired (de ``DataProcSlotMap.nmax``, ``len()`` de las
        listas filtradas del Excel) contra el current (exportando la
        tabla del proceso con ``tia_client.export_tables`` y
        delegando en ``compute_nmax_diff_for_proc``).

        Mismo shape que el ``nmax_block`` de Dispositivos:
        ``{"current", "desired", "todos", "summary", "nmax_error"}``.

        Si el config no aporta ``procesos.n_max_suffixes`` o no hay
        slot_map (fase previa fallo), devuelve un bloque vacio. Si el
        export falla, emite un warning y devuelve ``current={}`` sin
        abortar el preview.
        """
        def _detail() -> str:
            nmax_summary = self._ctx.nmax_block.get("summary", {})
            return (
                f"Calcular diferencias de N_MAX: "
                f"{nmax_summary.get('actualizar', 0)} N_MAX actualizar, "
                f"{nmax_summary.get('sin_cambios', 0)} sin cambios"
            )

        if self._ctx.slot_map is None or self._ctx.slot_map_error is not None:
            self._ctx.nmax_block = empty_nmax_block()
            return _detail()

        nmax_names = self._ctx.slot_map.nmax_names
        nmax_desired = self._ctx.slot_map.nmax
        if not nmax_names or not nmax_desired:
            self._ctx.nmax_block = empty_nmax_block()
            return _detail()

        from areas.alimentacion.helpers.layout.build_cache import build_cache
        from core.infrastructure.tia.tia_export_paths import XmlTarget

        target_dir = build_cache(root=self._ctx.build_cache_root).procesos.preview_variables
        table_name = self._ctx.slot_map.table_name
        plc_name = self._ctx.bloques_cache.plc_name if self._ctx.bloques_cache else ""

        try:
            self._ctx.tia_client.submit_and_wait(
                "export_tables",
                {
                    "plc_name": plc_name,
                    "target_dir": str(target_dir),
                    "table_names": [table_name],
                    # Solo lectura: el preview lee el ``.xml`` de este
                    # workdir para diffearlo y no lo importa nunca en
                    # TIA, asi que el layout plano es el de este caso.
                    # Declararlo explicito evita heredar el default.
                    "keep_folder_structure": False,
                },
                timeout=120.0,
            )
            xml_path = XmlTarget(target_dir, table_name).path
            nmax_diff = compute_nmax_diff_for_proc(
                table_name=table_name,
                nmax_names=nmax_names,
                nmax_desired=nmax_desired,
                xml_path=xml_path,
            )
            self._ctx.nmax_block = {
                "current": nmax_diff.current,
                "desired": nmax_diff.desired,
                "todos": nmax_diff.todos,
                "summary": nmax_diff.summary,
                "nmax_error": (
                    f"XML de N_MAX no encontrado en TIA export: {xml_path}"
                    if nmax_diff.missing_xml else None
                ),
            }
        except FileNotFoundError:
            logger.warning(
                f"[N_MAX procesos] XML esperado no encontrado en "
                f"{target_dir} para tabla {table_name}."
            )
            self._ctx.nmax_block = empty_nmax_block()
        except Exception as exc:
            logger.warning(
                f"[N_MAX procesos] export/parse fallo: {exc}. "
                f"Devolviendo current={{}} para no romper la SPA."
            )
            self._ctx.nmax_block = empty_nmax_block()

        return _detail()

    @step(
        "Exportar y calcular diferencias",
        descripcion="Exporta los DBs del proceso y compara los comentarios actuales",
    )
    def _stage_5_exportar_y_calcular_diferencias(self) -> str:
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
        def _detail() -> str:
            if self._ctx.export_error:
                return (
                    f"Exportar y calcular diferencias: "
                    f"error: {self._ctx.export_error}"
                )
            # Los contadores de slots se componen en el paso 6: aqui
            # todavia no hay ``ctx.result``.
            s = self._ctx.result.get("summary", {})
            return (
                f"Exportar y calcular diferencias: {s.get('total', 0)} slots: "
                f"{s.get('renombrados', 0)} renombrar, "
                f"{s.get('agregados', 0)} agregar, "
                f"{s.get('sin_cambios', 0)} sin cambios"
            )

        if self._ctx.slot_map is None or self._ctx.slot_map_error is not None:
            return _detail()

        from areas.alimentacion.helpers.layout.build_cache import build_cache
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
            return _detail()

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

        # 1. Export + read DB_PARAM y DB_ALM (1 dispatch unificado).
        param_name = self._ctx.slot_map.db_param_name
        alm_name = self._ctx.slot_map.db_alm_name
        try:
            self._ctx.tia_client.submit_and_wait(
                "export_blocks",
                {
                    "plc_name": plc_name,
                    "target_dir": str(work_dir),
                    "block_names": [param_name, alm_name],
                },
                timeout=120.0,
            )
            dcl_param_path = SdPair(work_dir, param_name).dcl
            res_param_path = SdPair(work_dir, param_name).res
            dcl_param_text = dcl_param_path.read_text(encoding="utf-8-sig") \
                if dcl_param_path.exists() else ""
            res_param_text = res_param_path.read_text(encoding="utf-8-sig") \
                if res_param_path.exists() else ""
            if not dcl_param_text or not res_param_text:
                param_error = f"export OK pero archivos vacios para {param_name}"
            dcl_alm_path = SdPair(work_dir, alm_name).dcl
            res_alm_path = SdPair(work_dir, alm_name).res
            dcl_alm_text = dcl_alm_path.read_text(encoding="utf-8-sig") \
                if dcl_alm_path.exists() else ""
            res_alm_text = res_alm_path.read_text(encoding="utf-8-sig") \
                if res_alm_path.exists() else ""
            if not dcl_alm_text or not res_alm_text:
                alm_error = f"export OK pero archivos vacios para {alm_name}"
        except Exception as exc:
            param_error = f"export/parse {param_name}: {exc}"
            alm_error = f"export/parse {alm_name}: {exc}"

        # 2. Decidir que reportar segun cuantos DBs fallaron.
        if param_error and alm_error:
            # Ambos fallaron: error. El operario debe investigar.
            logger.error(
                f"_stage_5_exportar_y_calcular_diferencias: ambos DBs fallaron. "
                f"PARAM={param_error!r}; ALM={alm_error!r}"
            )
            self._ctx.preal_current = None
            self._ctx.pint_current = None
            self._ctx.alm_current = None
            self._ctx.export_error = f"PARAM: {param_error}; ALM: {alm_error}"
            return _detail()

        if param_error:
            logger.warning(
                f"_stage_5_exportar_y_calcular_diferencias: solo DB_PARAM fallo "
                f"({param_error}). Sigo con ALM."
            )
            self._ctx.preal_current = None
            self._ctx.pint_current = None
            # ALM: parsear abajo.
        if alm_error:
            logger.warning(
                f"_stage_5_exportar_y_calcular_diferencias: solo DB_ALM fallo "
                f"({alm_error}). Sigo con PARAM."
            )
            self._ctx.alm_current = None
            # PARAM: parsear abajo.

        # 3. Parsear comentarios de los DBs que NO fallaron, via helper puro.
        preal_current, pint_current, alm_current = compute_proc_slot_diff(
            slot_map=self._ctx.slot_map,
            dcl_param_text=dcl_param_text,
            res_param_text=res_param_text,
            dcl_alm_text=dcl_alm_text,
            res_alm_text=res_alm_text,
        )
        if not param_error:
            self._ctx.preal_current = preal_current
            self._ctx.pint_current = pint_current
        if not alm_error:
            self._ctx.alm_current = alm_current

        self._ctx.export_error = None
        return _detail()

    @step(
        "Componer respuesta",
        descripcion="Compone la respuesta final que consume la SPA",
    )
    def _stage_6_componer_respuesta(self) -> str:
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
                    "AppCache no tiene Excel cargado para el area. Cargue el Excel con "
                    "POST /api/v1/excel/upload."
                ],
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": [],
            }
            return "Componer respuesta: preview compuesto"

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
            return "Componer respuesta: preview compuesto"

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
            return "Componer respuesta: preview compuesto"

        sm = self._ctx.slot_map
        fatal_missing = (
            not sm.table_present
            or (
                sm.db_param_name in sm.db_missing
                and sm.db_alm_name in sm.db_missing
            )
        )
        # Flags estructurados de presencia en el PLC. La SPA los usa
        # para marcar visualmente que un nombre concreto falta, sin
        # tener que parsear ``missing_blocks`` (strings formateados).
        db_present = {
            "param": sm.db_param_name not in sm.db_missing,
            "alm": sm.db_alm_name not in sm.db_missing,
        }
        if fatal_missing:
            self._ctx.result = {
                "proc_uid": self._ctx.proc_uid,
                "proc_codigo": extract_codigo(sm.db_param_name),
                "precondiciones_ok": False,
                "missing_blocks": sm.missing_blocks,
                "db_param_name": sm.db_param_name,
                "db_alm_name": sm.db_alm_name,
                "table_name": sm.table_name,
                "db_present": db_present,
                "table_present": sm.table_present,
                "arrays": {},
                "summary": dict(empty_summary),
                "warnings": sm.warnings,
            }
            return "Componer respuesta: preview compuesto"

        # 1 DB ausente (recuperable) o ambos presentes: compose arrays,
        # summary y warnings. ``sm.db_missing`` se anade a ``warnings``
        # para que la SPA muestre el aviso al operario.
        from areas.alimentacion.data.data_proc_slot_map import (
            format_missing_db_message,
        )
        arrays = compose_arrays(
            sm, self._ctx.preal_current, self._ctx.pint_current, self._ctx.alm_current
        )
        summary = compute_summary(arrays)
        warnings = list(sm.warnings)
        for missing_db in sm.db_missing:
            warnings.append(format_missing_db_message(sm, missing_db))
        if self._ctx.export_error:
            warnings.append(f"Export fallo: {self._ctx.export_error}. current=None.")

        self._ctx.result = {
            "proc_uid": self._ctx.proc_uid,
            "proc_codigo": extract_codigo(self._ctx.slot_map.db_param_name),
            "precondiciones_ok": True,
            "missing_blocks": [],
            "db_param_name": self._ctx.slot_map.db_param_name,
            "db_alm_name": self._ctx.slot_map.db_alm_name,
            "table_name": self._ctx.slot_map.table_name,
            "db_present": db_present,
            "table_present": self._ctx.slot_map.table_present,
            "arrays": arrays,
            "summary": summary,
            "nmax": self._ctx.nmax_block,
            "warnings": warnings,
        }
        return "Componer respuesta: preview compuesto"



@dataclass
class ProcPreviewContext:
    """Estado compartido entre las funciones de ``proc_generate_preview``.

    Cada funcion toma un ``ProcPreviewContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionProcDBGenerarPreview`` instancia uno y lo reusa entre sus 6
    steps para que los resultados intermedios esten disponibles para
    las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    proc_uid: int
    tia_client: Any
    config_manager: Any
    app_cache: AppCache
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


__all__ = ["FunctionProcDBGenerarPreview", "ProcPreviewContext"]
