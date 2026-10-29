"""FB de area: sincroniza comentarios de un proceso contra TIA Portal.

State machine sobre el helper ``proc_sincronizar``
(areas/alimentacion/helpers/proc/proc_sincronizar.py). El helper
expone funciones independientes que reciben un ``ProcSyncContext``
y mutan sus campos. Aqui en el FB vive la state machine: el orden
de las llamadas, el mapping step -> funcion del helper, y la
instanciacion del ctx.

Hereda directo de ``FunctionBase``.

Runtime params via ``start(**kwargs)``:
  - ``proc_uid`` (int): uid del proceso. Obligatorio.
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape esperada por la SPA::

    {
      "proc_uid":             int,
      "plc_name":             str,
      "success":              True,
      "applied":              True,
      "operations_executed":  int,
      "details":              list[dict],
      "warnings":             list[str],
      "post_sync_preview":    dict | None,
    }

Steps (9, Tx A N_MAX + compile + Tx B + post-preview):
  - check_state_commit       -> valida excel_cache cargado
  - check_blocks_commit      -> valida bloques_cache cargado
  - build_slot_maps_commit   -> recalcula slot maps desde AppCache
  - sync_nmax                -> Tx A online (incluso si nmax_ops=[])
  - wait_consolidation       -> sleep 2s para que TIA consolide
  - compile_proc_blocks      -> compila PARAM + ALM tras el resize
  - open_transaction         -> Tx B: commits + import
  - post_preview             -> regenera preview para 'todo en sync'
  - done                     -> vuelca ctx.result a self.result
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import validate_execute_batch_result
from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.helpers.tia.with_plc import with_plc
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.app_cache import AppCache, get_app_cache
from areas.alimentacion._area_id import AREA_ID
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT

# Asegura que ``Logger.web/ok`` existen (idempotente).
install_web_level()

logger = logging.getLogger(__name__)


# Sleep para que TIA consolide internamente entre Tx A y Tx B.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


class FunctionProcDBSincronizar(FunctionBase):
    """FB que aplica comentarios del proceso contra TIA en una sola TX."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 1 transaccion TIA con 2 sub-comandos
    # (``update_proc_comments_db_param`` + ``update_proc_comments_db_alm``).
    # TIA V21 puede tardar 1-3 min en PLCs grandes.
    STEP_TIMEOUT_S: float = 300.0

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
        (1, "Validar estado de TIA",       "_stage_1_check_state_commit"),
        (2, "Validar bloques",             "_stage_2_check_blocks_commit"),
        (3, "Construir mapa de slots",     "_stage_3_build_slot_maps_commit"),
        (4, "Aplicar N_MAX",               "_stage_4_sync_nmax"),
        (5, "Esperar consolidación TIA",   "_stage_5_wait_consolidation"),
        (6, "Compilar bloques",            "_stage_6_compile_proc_blocks"),
        (7, "Abrir transacción TIA",       "_stage_7_open_transaction"),
        (8, "Generar preview post-sincronización", "_stage_8_post_preview"),
        (9, "Componer respuesta",          "_stage_9_build_response"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_db_sincronizar",
        titulo: str = "Sincronizar comentarios del proceso contra PLC",
        steps: list[dict[str, Any]] | None = None,
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
            steps=steps if steps is not None else [
                {"nombre": "Validar estado de TIA"},
                {"nombre": "Validar bloques"},
                {"nombre": "Construir mapa de slots"},
                {"nombre": "Aplicar N_MAX"},
                {"nombre": "Esperar consolidación TIA"},
                {"nombre": "Compilar bloques"},
                {"nombre": "Abrir transacción TIA"},
                {"nombre": "Generar preview post-sincronización"},
                {"nombre": "Componer respuesta"},
            ],
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
        # ``bloques_cache`` se inyecta por constructor (test) o se lee
        # del ``AppCache`` en ``on_start``.
        self._bloques_cache = bloques_cache
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._proc_uid: int = 0
        # ProcSyncContext compartido entre los 5 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

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
                "FunctionProcSincronizar requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionProcSincronizar requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionProcSincronizar.execute(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcSincronizar.start(proc_uid=int) es obligatorio"
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

        # Crear el ProcSyncContext que las 4 funciones iran mutando.
        # ``ProcSyncContext`` esta definido en este mismo modulo (al
        # final del archivo).
        self._ctx = ProcSyncContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_cache=self._app_cache,
            build_cache_root=self._build_cache_root,
            bloques_cache=self._bloques_cache,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando sync del proceso "
            f"{self._proc_uid} en {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``proc_sincronizar``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``ProcSyncContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        if self._ctx is None:
            raise RuntimeError(
                "ProcSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name/proc_uid valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los 9 stages se declaran arriba de la clase. Asi el
        # flujo del FB es visible de un vistazo (modo SFC) y los tests
        # pueden mockear ``fb._stage_N_<nombre>`` directamente sin
        # parchear el ``match`` interno.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 3/9").
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                handler()
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionProcDBSincronizar"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA.

        Ademas publica el resultado en el AppCache (slots
        ``last_proc_commit_summary`` + ``preview_proc``): el router solo
        encola el trabajo en el OB1, asi que la publicacion tiene que
        ocurrir aqui, cuando el FB ha terminado.
        """
        if self._ctx is None:
            # Error temprano: deps no inyectadas o params ausentes.
            self.result = {
                "success": False,
                "applied": False,
                "operations_executed": 0,
                "details": [],
                "warnings": [
                    "ProcSyncContext no inicializado. "
                    "Verifica plc_name y proc_uid."
                ],
            }
            return

        self.result = self._ctx.result

        # Log de cierre con el mismo formato que el resto de FBs.
        ops_executed = self.result.get("operations_executed", 0)
        logger.debug(
            f"[{self.nombre}] sync completo para proceso "
            f"{self._ctx.proc_uid} en {self._ctx.plc_name}: "
            f"{ops_executed} ops aplicadas"
        )

        self._publish_result_to_cache()
        logger.ok(
            f"Sincronizacion de proceso '{self._ctx.proc_uid}' en "
            f"'{self._ctx.plc_name}': {ops_executed} ops aplicadas"
        )

    def _publish_result_to_cache(self) -> None:
        """Publica el resumen del commit y el preview post-sync en el AppCache.

        El AppCache es el canal por el que la SPA se entera del commit:
        lee estos slots y los recibe por SSE (``cache_changed``). El
        router solo encola el trabajo, asi que la publicacion tiene que
        ocurrir aqui, cuando el FB ha terminado.
        """
        from core.runtime.app_cache import get_app_cache
        from core.runtime.area_preview_cache import (
            area_set_preview_proc,
            area_set_proc_commit_summary,
        )

        app_cache = get_app_cache()
        area_set_proc_commit_summary(app_cache, "alimentacion", self.result)
        post_sync_preview = (
            self.result.get("post_sync_preview")
            if isinstance(self.result, dict) else None
        )
        if post_sync_preview is not None:
            area_set_preview_proc(app_cache, "alimentacion", post_sync_preview)

    # ==================================================================
    # Stages del FB (ZONA 4: 9 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    def _stage_1_check_state_commit(self) -> None:
        """Stage 1: valida que el cache del Excel esta cargado.

        Multi-PLC: chequea el cache activo del area (filtrado por PLC).
        """
        from core.runtime.excel_cache import excel_get_active
        cache = (
            excel_get_active(self._ctx.app_cache, "alimentacion")
            if self._ctx.app_cache is not None else None
        )
        self._ctx.excel_loaded = cache is not None
        if not self._ctx.excel_loaded:
            raise RuntimeError(
                "app_cache.excel_active_by_area['alimentacion'] esta vacio. "
                "Cargue el Excel con POST /api/v1/excel/upload."
            )

    def _stage_2_check_blocks_commit(self) -> None:
        """Stage 2: valida que el cache de bloques del PLC esta disponible."""
        self._ctx.bloques_loaded = self._ctx.bloques_cache is not None
        if not self._ctx.bloques_loaded:
            raise RuntimeError(
                "Cache de bloques del PLC no disponible. "
                "Selecciona el PLC en el sidebar y espera al "
                "escaneo de bloques (1-3 min en PLCs grandes)."
            )

    def _stage_3_build_slot_maps_commit(self) -> None:
        """Stage 3: recalcula slot maps + calcula N_MAX ops.

        Contrato de abort sobre ``slot_map``:
          - ``table_present=False``: abort ("Tabla de variables del
            proceso no existe en el PLC").
          - Tabla presente + ambos DBs en ``db_missing``: abort
            ("no hay nada que aplicar").

        Si solo 1 DB esta en ``db_missing``, emite warning al operario
        y sigue: Tx B omitira el DB ausente en la fase 2.

        Tras la validacion, calcula ``ctx.nmax_ops`` (necesario para
        stage 4) y loguea el conteo.
        """
        from areas.alimentacion.data.data_proc_slot_map import (
            format_missing_db_message,
            proc_build_slot_maps,
        )
        self._ctx.slot_map = proc_build_slot_maps(
            self._ctx.app_cache, self._ctx.config_manager,
            self._ctx.proc_uid, self._ctx.bloques_cache,
        )
        if self._ctx.slot_map is None:
            raise RuntimeError(
                "proc_build_slot_maps_commit no inicializo "
                "ctx.slot_map. El helper fallo silenciosamente."
            )

        sm = self._ctx.slot_map

        if not sm.table_present:
            raise RuntimeError(
                f"Tabla de variables del proceso {self._ctx.proc_uid} "
                f"no existe en el PLC. Crea la tabla '{sm.table_name}' "
                f"en TIA Portal antes de sincronizar."
            )

        if (
            sm.db_param_name in sm.db_missing
            and sm.db_alm_name in sm.db_missing
        ):
            raise RuntimeError(
                f"Faltan DB_PARAM ({sm.db_param_name}) y DB_ALM "
                f"({sm.db_alm_name}) del proceso {self._ctx.proc_uid}; "
                f"no hay nada que aplicar."
            )

        for missing_db in sm.db_missing:
            msg = format_missing_db_message(sm, missing_db)
            sm.warnings.append(msg)
            logger.warning(f"[{self.nombre}] {msg}")

        # Calcular nmax_ops ANTES del step sync_nmax. El helper
        # necesita slot_map (resuelto arriba) y dimensiones (en
        # app_cache). Separamos el calculo del dispatch para poder
        # loguear el resultado del diff y abortar si falla el parser,
        # sin abrir Tx A.
        self._proc_compute_nmax_ops_inline()
        logger.debug(
            f"[{self.nombre}] N_MAX diff: "
            f"{len(self._ctx.nmax_ops)} ops a aplicar"
        )

    def _proc_compute_nmax_ops_inline(self) -> None:
        """Calculo de nmax_ops (helper local del stage 3).

        Llama al module-level ``_compute_nmax_ops_for_proc_apply`` con
        ``self._ctx.tags_base`` (preview variables) y el ``slot_map``
        construido en stage 3. Se separa del stage 3 para mantener
        el método del FB delgado y poder loguear el resultado del diff
        antes de abrir Tx A.
        """
        from areas.alimentacion.helpers.layout.build_cache import build_cache

        if self._ctx.tags_base is None:
            proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
            self._ctx.tags_base = proc_ctx.preview_variables

        self._ctx.nmax_ops = _compute_nmax_ops_for_proc_apply(
            self._ctx.tags_base, self._ctx.proc_uid, self._ctx.slot_map,
        )

    def _stage_4_sync_nmax(self) -> None:
        """Stage 4: dispatch ``execute_transactional_batch`` con N_MAX ops.

        Siempre se ejecuta, aunque ``ctx.nmax_ops=[]`` (requisito del
        operario: el flujo debe correr completo aunque los N_MAX ya
        estuvieran aplicados). Si la lista esta vacia, el batch aborta
        con ``ValueError``; lo capturamos y emitimos un resultado OK
        con 0 ops ejecutadas para que la state machine continue.
        """
        operations: list[dict[str, Any]] = []
        for nmax_op in self._ctx.nmax_ops:
            operations.append({
                "command": "update_user_constant_value",
                "args": {
                    "plc_name": self._ctx.plc_name,
                    "table_name": nmax_op["table_name"],
                    "constant_name": nmax_op["constant_name"],
                    "new_value": nmax_op["new_value"],
                },
            })

        if not operations:
            # Sin ops: nada que aplicar, logueamos y seguimos.
            logger.info(
                f"[proc_db_sync {self._ctx.plc_name} u{self._ctx.proc_uid}] "
                f"sin N_MAX ops; batch omitido"
            )
            self._ctx.nmax_result = {
                "success": True,
                "operations_executed": 0,
                "details": [],
            }
            return

        logger.info(
            f"[proc_db_sync {self._ctx.plc_name} u{self._ctx.proc_uid}] "
            f"Tx A (online): {len(operations)} N_MAX via batch"
        )
        nmax_result = self._ctx.tia_client.submit_and_wait(
            "execute_transactional_batch",
            {
                "undo_text": (
                    f"Actualizando N_MAX proceso {self._ctx.proc_uid} "
                    f"({self._ctx.plc_name})..."
                ),
                "operations": operations,
            },
            timeout=60.0,
        )
        if not nmax_result.get("ok"):
            raise RuntimeError(
                f"execute_transactional_batch fallo: "
                f"{nmax_result.get('error') or '<sin error>'}"
            )
        self._ctx.nmax_result = nmax_result.get("result") or {}

    def _stage_5_wait_consolidation(self) -> None:
        """Stage 5: sleep 2s para que TIA consolide tras Tx A."""
        time.sleep(TIA_CONSOLIDATION_SLEEP_S)

    def _stage_6_compile_proc_blocks(self) -> None:
        """Stage 6: compila los DBs PARAM + ALM del proceso actual.

        Patron paralelo a ``disp_Sincronizar.compilar_bloques``:
        dispatch ``compile_blocks`` con los 2 DBs. Si TIA reporta
        errores parciales, marca ``compile_ok=False`` y guarda el
        mensaje en ``compile_error`` (el FB lo evalua en su post-step).
        """
        block_names = self._proc_discover_compile_dbs_inline()
        if not block_names:
            self._ctx.compile_ok = False
            self._ctx.compile_error = (
                "proc_discover_compile_dbs retorno []: self._ctx.slot_map "
                "no inicializado. Fallo previo en build_slot_maps_commit."
            )
            return

        try:
            compile_result = self._ctx.tia_client.submit_and_wait(
                "compile_blocks",
                {
                    "plc_name": self._ctx.plc_name,
                    "block_names": block_names,
                },
                timeout=120.0,
            )
        except Exception as e:
            self._ctx.compile_ok = False
            self._ctx.compile_error = f"compile_blocks excepcion: {e!r}"
            return

        if not compile_result.get("ok"):
            self._ctx.compile_ok = False
            self._ctx.compile_error = (
                compile_result.get("error") or "compile_blocks fallo"
            )
            return

        self._ctx.compile_result = compile_result.get("result") or {}
        compiled = (self._ctx.compile_result or {}).get("compiled", [])
        errors = (self._ctx.compile_result or {}).get("errors", [])
        any_had_errors = any(c.get("had_errors") for c in compiled)
        if any_had_errors or errors:
            self._ctx.compile_ok = False
            n_had = sum(1 for c in compiled if c.get("had_errors"))
            n_err = len(errors)
            n_not_found = len(
                (self._ctx.compile_result or {}).get("not_found", [])
            )
            self._ctx.compile_error = (
                f"TIA reporta errores de compilacion post-N_MAX: "
                f"{n_had} bloque(s) con errores, "
                f"{n_err} excepcion(es), "
                f"{n_not_found} no encontrado(s). "
                f"Revisa el proyecto en TIA Portal: los DBs pueden "
                f"haber quedado con tamano inconsistente tras el resize."
            )
            logger.warning(
                f"[{self._ctx.plc_name}] Compilacion parcial proc "
                f"tras N_MAX: {compile_result}"
            )

    def _proc_discover_compile_dbs_inline(self) -> list[str]:
        """Lista de DBs a compilar (helper de ``_stage_6``).

        Excluye los DBs en ``slot_map.db_missing`` porque
        ``compile_blocks`` aborta si recibe un bloque inexistente.
        Retorna ``[]`` si ``ctx.slot_map`` no esta inicializado.
        """
        if self._ctx.slot_map is None:
            return []
        sm = self._ctx.slot_map
        result: list[str] = []
        if sm.db_param_name not in sm.db_missing:
            result.append(sm.db_param_name)
        if sm.db_alm_name not in sm.db_missing:
            result.append(sm.db_alm_name)
        return result

    def _stage_7_open_transaction(self) -> None:
        """Stage 7: Tx B (comentarios) - orquesta 5 fases + commit final.

        Fases (delegadas en helpers module-level ``_proc_tx_b_*``):
          1. limpiar workdir.
          2. re-export PARAM + ALM.
          3. leer comentarios actuales (modo degradado si falla).
          4. cruzar Excel + "eliminar" (".").
          5. componer las ops del lote.

        Tras las 5 fases, hace commits inline sobre los archivos
        exportados y un ``import_block`` al PLC.
        """
        codigo = (
            self._ctx.slot_map.db_param_name.split("_")[1]
            if "_" in self._ctx.slot_map.db_param_name
            else self._ctx.proc_uid
        )
        undo_text = (
            f"Sincronizando comentarios proceso {self._ctx.proc_uid} ({self._ctx.plc_name})..."
        )

        # Phase 1
        _proc_tx_b_limpiar(self._ctx)

        # Phase 2 + 3: re-export + read current. Modo degradado:
        # si el re-export o la lectura falla, seguimos con
        # current_* vacios (el apply solo aplicara los slots del Excel,
        # sin detectar "eliminar"). El operario lo vera como
        # "renombrar / agregar", no "eliminar".
        try:
            _proc_tx_b_detectar_eliminar_export(self._ctx)
            current_preal, current_pint, current_alm = (
                _proc_tx_b_detectar_eliminar_read(self._ctx)
            )
        except Exception as exc:
            logger.warning(
                f"_stage_7_open_transaction: re-lectura de TIA para "
                f"detectar 'eliminar' fallo: {exc!r}. El apply solo "
                f"aplicara los slots del Excel (modo degradado)."
            )
            current_preal, current_pint, current_alm = {}, {}, {}

        _proc_tx_b_calcular_apply_maps(
            self._ctx, current_preal, current_pint, current_alm
        )

        # 6 commits sobre el DB PARAM (PReal + 3 satellites + PInt +
        # 2 satellites) y 1 sobre el DB ALM. Cada commit opera sobre
        # el archivo exportado.
        details: list[dict[str, Any]] = []
        operations_executed = 0
        param_modified = False
        alm_modified = False

        if self._ctx.exports_param_dir is not None:
            preal_apply_int = {
                int(k): v for k, v in self._ctx.apply_preal_map.items()
            }
            pint_apply_int = {
                int(k): v for k, v in self._ctx.apply_pint_map.items()
            }
            param_arrays = [
                ("PReal",                   "UDT"),
                ("PReal_Vis",               "Simple"),
                ("Aux.PReal_ValorAnterior", "Simple"),
                ("PInt",                    "UDT"),
                ("PInt_Vis",                "Simple"),
                ("Aux.PInt_ValorAnterior",  "Simple"),
            ]
            from core.helpers.simatic_sd import commit_array_comments
            from core.infrastructure.tia.tia_export_paths import SdPair
            for array_name, array_type in param_arrays:
                slot_map = (
                    preal_apply_int
                    if array_name.startswith(("PReal", "Aux.PReal"))
                    else pint_apply_int
                )
                if not slot_map:
                    continue
                result = commit_array_comments(
                    SdPair(
                        Path(self._ctx.exports_param_dir),
                        self._ctx.slot_map.db_param_name,
                    ).dcl,
                    SdPair(
                        Path(self._ctx.exports_param_dir),
                        self._ctx.slot_map.db_param_name,
                    ).res,
                    array_name=array_name,
                    slot_map=slot_map,
                    array_type=array_type,
                    write_to_original=True,
                )
                details.append({
                    "array": array_name,
                    "injected": dict(result.injected),
                    "updated": dict(result.updated),
                    "removed": list(result.removed),
                })
                operations_executed += 1
                if (
                    len(result.injected)
                    + len(result.updated)
                    + len(result.removed)
                ) > 0:
                    param_modified = True

        if self._ctx.exports_alm_dir is not None:
            alm_apply_int = {
                int(k): v for k, v in self._ctx.apply_alm_map.items()
            }
            if alm_apply_int:
                from core.helpers.simatic_sd import commit_array_comments
                from core.infrastructure.tia.tia_export_paths import SdPair
                result = commit_array_comments(
                    SdPair(
                        Path(self._ctx.exports_alm_dir),
                        self._ctx.slot_map.db_alm_name,
                    ).dcl,
                    SdPair(
                        Path(self._ctx.exports_alm_dir),
                        self._ctx.slot_map.db_alm_name,
                    ).res,
                    array_name="ALM",
                    slot_map=alm_apply_int,
                    array_type="Simple",
                    write_to_original=True,
                )
                details.append({
                    "array": "ALM",
                    "injected": dict(result.injected),
                    "updated": dict(result.updated),
                    "removed": list(result.removed),
                })
                operations_executed += 1
                if (
                    len(result.injected)
                    + len(result.updated)
                    + len(result.removed)
                ) > 0:
                    alm_modified = True

        plc_name = (
            self._ctx.bloques_cache.plc_name
            if self._ctx.bloques_cache is not None
            else ""
        )
        import shutil as _shutil
        from areas.alimentacion.helpers.layout.build_cache import build_cache

        if (param_modified or alm_modified) and plc_name:
            proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
            modified_root = proc_ctx.sync_bloques_modified

            if param_modified and self._ctx.exports_param_dir is not None:
                modified_param_dir = (
                    str(Path(modified_root) / self._ctx.slot_map.param_subpath)
                    if self._ctx.slot_map.param_subpath
                    else str(modified_root)
                )
                if Path(self._ctx.exports_param_dir).exists():
                    Path(modified_param_dir).mkdir(parents=True, exist_ok=True)
                    _shutil.copytree(
                        self._ctx.exports_param_dir, modified_param_dir,
                        dirs_exist_ok=True,
                    )

            if alm_modified and self._ctx.exports_alm_dir is not None:
                modified_alm_dir = (
                    str(Path(modified_root) / self._ctx.slot_map.alm_subpath)
                    if self._ctx.slot_map.alm_subpath
                    else str(modified_root)
                )
                if Path(self._ctx.exports_alm_dir).exists():
                    Path(modified_alm_dir).mkdir(parents=True, exist_ok=True)
                    _shutil.copytree(
                        self._ctx.exports_alm_dir, modified_alm_dir,
                        dirs_exist_ok=True,
                    )

            # Un solo import_block bajo execute_transactional_batch para
            # atomicidad semantica: si TIA falla durante el scaneo
            # recursivo de sync_bloques_modified, rollback total.
            self._ctx.tia_client.submit_and_wait(
                "execute_transactional_batch",
                {
                    "undo_text": (
                        f"Sincronizando proceso {self._ctx.proc_uid} ({self._ctx.plc_name})..."
                    ),
                    "operations": [
                        {
                            "command": "import_block",
                            "args": {
                                "plc_name": plc_name,
                                "import_dir": str(modified_root),
                                "target_folder": "",
                            },
                        },
                    ],
                },
                timeout=600.0,
            )

        self._ctx.tx_result = {
            "operations_executed": operations_executed,
            "details": details,
        }

    def _stage_8_post_preview(self) -> None:
        """Stage 8: regenera el preview tras el commit.

        Replica el flujo del preview (``generar_prevision``) inline,
        sin state machine externa, usando las funciones puras del
        helper ``helpers/proc/proc_generar_preview.py``. Mismo patron
        que ``_stage_11_disp_post_preview`` de ``function_disp_sincronizar``.

        Pasos:
          1. Limpia ``preview/`` + re-exporta DB_PARAM + DB_ALM + tabla N_MAX.
          2. ``compute_proc_slot_diff`` (helper) -> preal/pint/alm current.
          3. ``compute_nmax_diff_for_proc`` (helper) -> N_MAX current.
          4. ``compose_arrays`` + ``compute_summary`` (helper) -> shape.
          5. Compone ``post_sync_preview`` con shape legacy esperada
             por la SPA.

        Si TIA aun consolida Tx B y algun export/parse falla,
        captura la excepcion y deja ``ctx.post_sync_preview=None``
        (warning en log). El operario puede lanzar preview manual.
        """
        from pathlib import Path

        from areas.alimentacion.helpers.layout.build_cache import build_cache
        from areas.alimentacion.helpers.proc.proc_db_generar_preview import (
            compose_arrays,
            compute_nmax_diff_for_proc,
            compute_proc_slot_diff,
            compute_summary,
        )
        from core.infrastructure.tia.tia_export_paths import SdPair, XmlTarget

        try:
            slot_map = self._ctx.slot_map
            if slot_map is None:
                raise RuntimeError("slot_map no disponible (sync no llego al stage 3)")

            plc_name = self._ctx.plc_name
            proc_uid = self._ctx.proc_uid

            # 1/5. Limpia preview/ + exporta 2 DBs + tabla N_MAX.
            proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
            proc_ctx.clean_preview()
            preview_bloques = proc_ctx.preview_bloques
            preview_variables = proc_ctx.preview_variables

            batch_result = self._ctx.tia_client.submit_and_wait(
                "execute_batch",
                {
                    "operations": [
                        {
                            "command": "export_blocks",
                            "args": {
                                "plc_name": plc_name,
                                "target_dir": str(preview_bloques),
                                "block_names": [
                                    slot_map.db_param_name,
                                    slot_map.db_alm_name,
                                ],
                            },
                        },
                        {
                            "command": "export_tables",
                            "args": {
                                "plc_name": plc_name,
                                "target_dir": str(preview_variables),
                                "table_names": [slot_map.table_name],
                            },
                        },
                    ],
                },
                timeout=120.0,
            )
            validate_execute_batch_result(
                batch_result["result"],
                undo_text=f"Generando prevision de proceso {proc_uid} ({plc_name})...",
                plc_name=plc_name,
                log=logger,
            )

            dcl_param_path = SdPair(preview_bloques, slot_map.db_param_name).dcl
            res_param_path = SdPair(preview_bloques, slot_map.db_param_name).res
            dcl_alm_path = SdPair(preview_bloques, slot_map.db_alm_name).dcl
            res_alm_path = SdPair(preview_bloques, slot_map.db_alm_name).res
            dcl_param_text = (
                dcl_param_path.read_text(encoding="utf-8-sig")
                if dcl_param_path.exists() else ""
            )
            res_param_text = (
                res_param_path.read_text(encoding="utf-8-sig")
                if res_param_path.exists() else ""
            )
            dcl_alm_text = (
                dcl_alm_path.read_text(encoding="utf-8-sig")
                if dcl_alm_path.exists() else ""
            )
            res_alm_text = (
                res_alm_path.read_text(encoding="utf-8-sig")
                if res_alm_path.exists() else ""
            )

            # 2/5. Diff de slots (helper puro).
            preal_current, pint_current, alm_current = compute_proc_slot_diff(
                slot_map=slot_map,
                dcl_param_text=dcl_param_text,
                res_param_text=res_param_text,
                dcl_alm_text=dcl_alm_text,
                res_alm_text=res_alm_text,
            )

            # 3/5. Diff de N_MAX (helper puro).
            xml_path = XmlTarget(preview_variables, slot_map.table_name).path
            nmax_diff = compute_nmax_diff_for_proc(
                table_name=slot_map.table_name,
                nmax_names=slot_map.nmax_names,
                nmax_desired=slot_map.nmax,
                xml_path=xml_path,
            )

            # 4/5. Compose arrays + summary (helper puro).
            arrays = compose_arrays(slot_map, preal_current, pint_current, alm_current)
            summary = compute_summary(arrays)
            warnings: list[str] = list(slot_map.warnings)
            if preal_current is None or pint_current is None:
                warnings.append("Export DB_PARAM o lectura fallo: PReal/PInt current=None.")
            if alm_current is None:
                warnings.append("Export DB_ALM o lectura fallo: ALM current=None.")

            # 5/5. Compone post_sync_preview (shape legacy).
            from areas.alimentacion.helpers.proc.proc_db_generar_preview import (
                extract_codigo,
            )
            self._ctx.post_sync_preview = {
                "proc_uid": proc_uid,
                "proc_codigo": extract_codigo(slot_map.db_param_name),
                "precondiciones_ok": True,
                "missing_blocks": [],
                "db_param_name": slot_map.db_param_name,
                "db_alm_name": slot_map.db_alm_name,
                "table_name": slot_map.table_name,
                "arrays": arrays,
                "summary": summary,
                "nmax": {
                    "current": nmax_diff.current,
                    "desired": nmax_diff.desired,
                    "todos": nmax_diff.todos,
                    "summary": nmax_diff.summary,
                    "nmax_error": (
                        f"XML de N_MAX no encontrado en {xml_path}"
                        if nmax_diff.missing_xml else None
                    ),
                },
                "warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[{self._ctx.plc_name}/proceso {self._ctx.proc_uid}] "
                f"Post-sync preview fallo (commit ya aplicado): "
                f"{exc!r}. El operario puede lanzar preview manual "
                f"desde la SPA."
            )
            self._ctx.post_sync_preview = None

    def _stage_9_build_response(self) -> None:
        """Stage 9: compone ``ctx.result`` con la shape legacy de la SPA.

        Inspecciona ``ctx.tx_result`` para extraer el resumen del lote
        (``operations_executed``, ``details``) y los warnings del
        slot_map.
        """
        tx = self._ctx.tx_result or {}
        ops_executed = tx.get("operations_executed", 0)
        warnings = self._ctx.slot_map.warnings if self._ctx.slot_map else []
        self._ctx.result = {
            "proc_uid": self._ctx.proc_uid,
            "plc_name": self._ctx.plc_name,
            "success": True,
            "applied": True,
            "operations_executed": ops_executed,
            "details": tx.get("details", []),
            "warnings": warnings,
            # Se rellena con el dict legacy del preview (o None si fallo)
            # al final del step ``post_preview``. El FB lo vuelca a
            # ``self.result`` para que la SPA vea "todo en sync" sin
            # pedir un preview manual extra (mismo patron que Dispositivos).
            "post_sync_preview": self._ctx.post_sync_preview,
        }


# ============================================================================
# Helper local del FB: calculo de ops N_MAX del proceso.
#
# Patron paralelo a ``_compute_nmax_ops_for_apply`` en
# ``function_disp_sincronizar.py``: misma firma, misma abstraccion.
# Vive en este archivo (no en ``helpers/proc/``) porque la logica es
# especifica del FB proc_db: la tabla de variables del proceso por
# convencion del operario; el dispatch de disp usa la
# tabla global de dispositivos.
# ============================================================================


def _compute_nmax_ops_for_proc_apply(
    tags_base: Path,
    proc_uid: int,
    slot_map: Any,
) -> list[dict[str, Any]]:
    """Calcula ops de N_MAX contra la tabla de variables del proceso.

    Args:
        tags_base: Carpeta donde TIA (vía preview) exportó la tabla de
            variables del proceso (``build_cache.procesos.preview_variables``).
        proc_uid: UID del proceso (para mensajes accionables).
        slot_map: ``DataProcSlotMap`` con ``table_name``, ``nmax`` y
            ``nmax_names``.

    Returns:
        Lista de ``[{"table_name", "constant_name", "new_value"}]``
        lista para ``execute_transactional_batch`` con
        ``update_user_constant_value``. Vacía si todos los N_MAX ya
        coinciden con el estado exportado.

    Raises:
        RuntimeError: Si ``slot_map`` es None / ``table_name`` vacío,
            si no hay ``nmax_names`` en config, o si la tabla no está
            exportada en ``tags_base`` (preview no se ejecutó).
    """
    from core.helpers.simatic_ml import PlcUserConstantParser
    from core.infrastructure.tia.tia_export_paths import XmlTarget

    if slot_map is None:
        raise RuntimeError(
            "_compute_nmax_ops_for_proc_apply: slot_map es None. "
            "El step 'Construir mapa de slots' no se ejecutó (o falló)."
        )
    table_name = getattr(slot_map, "table_name", "") or ""
    if not table_name:
        raise RuntimeError(
            f"_compute_nmax_ops_for_proc_apply: slot_map.table_name "
            f"vacío. ¿proc_uid={proc_uid} existe en el AppCache?"
        )
    nmax_names: dict[str, str] = (
        getattr(slot_map, "nmax_names", {}) or {}
    )
    if not nmax_names:
        raise RuntimeError(
            f"_compute_nmax_ops_for_proc_apply: config_manager no "
            f"aporta procesos.n_max_suffixes para proc_uid={proc_uid}. "
            f"Revisa config/defaults.py."
        )

    try:
        xml_path = XmlTarget(tags_base, table_name).path
    except FileNotFoundError:
        raise RuntimeError(
            f"Tabla de variables del proceso {proc_uid} no exportada: "
            f"{tags_base}/{table_name}.xml (ni directo ni con rglob). "
            f"Ejecuta POST /api/v1/procesos/sync/preview antes del "
            f"commit, o revisa que el PLC tenga la tabla {table_name}."
        )

    try:
        current: dict[str, int] = PlcUserConstantParser.parse_user_constants(
            xml_path
        )
    except Exception as e:
        raise RuntimeError(
            f"_compute_nmax_ops_for_proc_apply: parseo de {xml_path} "
            f"falló: {e!r}. ¿XML corrupto o sin permisos de lectura?"
        ) from e

    nmax_desired: dict[str, int] = (
        getattr(slot_map, "nmax", {}) or {}
    )
    ops: list[dict[str, Any]] = []
    for kind, desired_val in nmax_desired.items():
        full_name = nmax_names.get(kind)
        if not full_name:
            logger.warning(
                f"[proc][N_MAX] kind={kind!r} sin nmax_name declarado. "
                f"Se ignora."
            )
            continue
        cur_val = current.get(full_name)
        desired_int = int(desired_val)
        if cur_val is not None and int(cur_val) == desired_int:
            continue
        ops.append({
            "table_name": table_name,
            "constant_name": full_name,
            "new_value": desired_int,
        })
    return ops


# ============================================================================
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora los 9 stages viven como metodos del FB (mutando ``self._ctx``). Solo
# permanecen aqui el ``ProcSyncContext`` (dataclass entre stages) y las
# helpers puras (``_proc_tx_b_limpiar``, ``_proc_tx_b_detectar_eliminar_export``,
# ``_proc_tx_b_detectar_eliminar_read``, ``_proc_tx_b_calcular_apply_maps``,
# ``_proc_tx_b_construir_ops``, ``_step_summary``).
# ============================================================================

@dataclass
class ProcSyncContext:
    """Estado compartido entre las funciones de ``proc_sincronizar``.

    Cada funcion toma un ``ProcSyncContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionProcSincronizar`` instancia uno y lo reusa entre sus 5
    ticks para que los resultados intermedios esten disponibles para
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

    # ── Resultado de proc_check_state_commit ──
    excel_loaded: bool = True

    # ── Resultado de proc_check_blocks_commit ──
    bloques_loaded: bool = True

    # ── Resultado de proc_build_slot_maps_commit ──
    slot_map: Any = None  # DataProcSlotMap o None

    # ── Resultado de proc_sync_nmax (Tx A: N_MAX online) ──
    tags_base: Path | None = None
    nmax_ops: list[dict[str, Any]] = field(default_factory=list)
    nmax_result: "dict[str, Any] | None" = None

    # ── Resultado de proc_compile_blocks (post-Tx A) ──
    compile_result: "dict[str, Any] | None" = None
    compile_ok: bool = True
    compile_error: str | None = None

    tx_result: "dict[str, Any] | None" = None

    work_dir: Path | None = None
    exports_subdir: Path | None = None
    exports_param_dir: str | None = None
    exports_alm_dir: str | None = None
    apply_preal_map: dict[str, str] = field(default_factory=dict)
    apply_pint_map: dict[str, str] = field(default_factory=dict)
    apply_alm_map: dict[str, str] = field(default_factory=dict)
    tx_b_ops: list[dict[str, Any]] = field(default_factory=list)

    # ── Resultado de proc_post_preview (preview post-sync) ──
    # Misma shape que devuelve ``proc_generar_preview`` (legacy SPA):
    # sirve para que el sync view muestre "todo en sync" sin pedir
    # un preview manual extra. None si el helper fallo (commit ya
    # aplicado; el operario puede lanzar preview manual aparte).
    post_sync_preview: dict[str, Any] | None = None

    result: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ProcSyncContext",
    "TIA_CONSOLIDATION_SLEEP_S",
]


# ===========================================================================
# Helpers privadas de ``_stage_7_open_transaction`` (4 fases de Tx B).
# Cada una opera sobre el ``ProcSyncContext`` pasado por argumento.
# Viven aqui (no en la clase) porque son codigo filesystem puro +
# dispatchs al worker; no necesitan ``self``.
# ===========================================================================


def _proc_tx_b_limpiar(ctx: ProcSyncContext) -> None:
    """Fase limpia el workdir antes del batch.

    Borra ``exports/`` y ``modified/`` para evitar archivos stale de
    runs anteriores (stale = "Import failed because object with name
    X already exists").
    """
    from areas.alimentacion.helpers.layout.build_cache import build_cache

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    proc_ctx.clean_sincronizar()
    ctx.work_dir = proc_ctx.sync_bloques_modified
    ctx.exports_subdir = proc_ctx.sync_bloques_export


def _proc_tx_b_detectar_eliminar_export(ctx: ProcSyncContext) -> None:
    """Fase re-exporta los DBs presentes a ``exports/<subpath>/``.

    Construye la lista de ops filtrando por ``slot_map.db_missing`` y
    las despacha en un solo ``execute_batch``. Tras el dispatch, valida
    ``details`` per-op: si una op falla con "no encontrado", omite ese
    DB (``exports_*_dir=None`` + warning). Si falla por otra causa
    raise (mantiene la semantica del sync ante errores no esperados).
    """
    from areas.alimentacion.helpers.layout.build_cache import build_cache
    from areas.alimentacion.data.data_proc_slot_map import (
        format_missing_db_message,
    )

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    plc_name = (
        ctx.bloques_cache.plc_name
        if ctx.bloques_cache is not None
        else ""
    )

    param_subpath = ctx.slot_map.param_subpath or ""
    alm_subpath = ctx.slot_map.alm_subpath or ""

    exports_param_dir = (
        str(proc_ctx.sync_bloques_export / param_subpath)
        if param_subpath else str(proc_ctx.sync_bloques_export)
    )
    exports_alm_dir = (
        str(proc_ctx.sync_bloques_export / alm_subpath)
        if alm_subpath else str(proc_ctx.sync_bloques_export)
    )

    operations: list[dict] = []
    op_block_names: list[str] = []
    if ctx.slot_map.db_param_name not in ctx.slot_map.db_missing:
        operations.append({
            "command": "export_blocks",
            "args": {
                "plc_name": plc_name,
                "target_dir": exports_param_dir,
                "block_names": [ctx.slot_map.db_param_name],
            },
        })
        op_block_names.append(ctx.slot_map.db_param_name)
    else:
        exports_param_dir = None
    if ctx.slot_map.db_alm_name not in ctx.slot_map.db_missing:
        operations.append({
            "command": "export_blocks",
            "args": {
                "plc_name": plc_name,
                "target_dir": exports_alm_dir,
                "block_names": [ctx.slot_map.db_alm_name],
            },
        })
        op_block_names.append(ctx.slot_map.db_alm_name)
    else:
        exports_alm_dir = None

    if not operations:
        raise RuntimeError(
            "_proc_tx_b_detectar_eliminar_export: sin ops a despachar "
            "(ambos DBs faltan). stage 3 debio abortar antes."
        )

    batch_result = ctx.tia_client.submit_and_wait(
        "execute_batch",
        {"operations": operations},
        timeout=120.0,
    )
    result = batch_result.get("result") or {}
    details = result.get("details") or []

    for idx, d in enumerate(details):
        if d.get("ok"):
            continue
        error_str = str(d.get("error", "")).lower()
        block_name = (
            op_block_names[idx] if idx < len(op_block_names) else ""
        )
        if "no encontrado" in error_str or "not found" in error_str:
            msg = format_missing_db_message(ctx.slot_map, block_name)
            if block_name == ctx.slot_map.db_param_name:
                exports_param_dir = None
            elif block_name == ctx.slot_map.db_alm_name:
                exports_alm_dir = None
            ctx.slot_map.warnings.append(msg)
            logger.warning(f"[{ctx.plc_name}] {msg}")
        else:
            raise RuntimeError(
                f"execute_batch fallo en op {idx+1}: "
                f"{d.get('error')}"
            )

    ctx.exports_param_dir = exports_param_dir
    ctx.exports_alm_dir = exports_alm_dir


def _proc_tx_b_detectar_eliminar_read(
    ctx: ProcSyncContext,
) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
    """Fase lee los comentarios ``es-ES`` actuales de cada array.

    Usa los archivos exportados en fase 2. Si el parseo falla
    (YAML invalido, .s7dcl ausente), devuelve ``({}, {}, {})`` y el
    apply seguira solo con los slots del Excel (modo degradado).
    """
    from core.helpers.simatic_sd import (
        find_array_slots,
        read_current_comments,
    )
    from core.infrastructure.tia.tia_export_paths import SdPair

    try:
        dcl_param = SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).dcl
        res_param = SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).res
        dcl_alm = SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).dcl
        res_alm = SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).res

        dcl_param_text = dcl_param.read_text(encoding="utf-8-sig") \
            if dcl_param.exists() else ""
        res_param_text = res_param.read_text(encoding="utf-8-sig") \
            if res_param.exists() else ""
        dcl_alm_text = dcl_alm.read_text(encoding="utf-8-sig") \
            if dcl_alm.exists() else ""
        res_alm_text = res_alm.read_text(encoding="utf-8-sig") \
            if res_alm.exists() else ""

        preal_slots = sorted(
            set(ctx.slot_map.preal.keys())
            | find_array_slots(dcl_param_text, "PReal", "UDT")
        )
        pint_slots = sorted(
            set(ctx.slot_map.pint.keys())
            | find_array_slots(dcl_param_text, "PInt", "UDT")
        )
        alm_slots = sorted(
            set(ctx.slot_map.alm.keys())
            | find_array_slots(dcl_alm_text, "ALM", "Simple")
        )
        current_preal = read_current_comments(
            res_param_text, "PReal", preal_slots, dcl_param_text, "UDT",
        )
        current_pint = read_current_comments(
            res_param_text, "PInt", pint_slots, dcl_param_text, "UDT",
        )
        current_alm = read_current_comments(
            res_alm_text, "ALM", alm_slots, dcl_alm_text, "Simple",
        )
    except Exception as exc:
        logger.warning(
            f"_proc_tx_b_detectar_eliminar_read: parseo de 'es-ES' "
            f"fallo ({exc!r}). apply solo aplicara slots del Excel "
            f"(modo degradado)."
        )
        return {}, {}, {}

    return current_preal, current_pint, current_alm


def _proc_tx_b_calcular_apply_maps(
    ctx: ProcSyncContext,
    current_preal: dict[int, str | None],
    current_pint: dict[int, str | None],
    current_alm: dict[int, str | None],
) -> "tuple[dict[str, str], dict[str, str], dict[str, str]]":
    """Fase mezcla Excel + "eliminar" (``"."``).

    "Eliminar" = slot presente en TIA pero NO en el Excel. Su
    comentario se resetea a ``"."``. Asi el operario ve
    renombrar / agregar / eliminar en la preview.
    """
    def _merge(
        slot_map: dict[int, str],
        current: dict[int, str | None],
    ) -> dict[str, str]:
        to_delete = {
            str(slot): "."
            for slot in sorted(set(current.keys()) - set(slot_map.keys()))
            if current.get(slot)
        }
        return {
            **{str(k): v for k, v in slot_map.items()},
            **to_delete,
        }

    preal_apply = _merge(ctx.slot_map.preal, current_preal)
    pint_apply = _merge(ctx.slot_map.pint, current_pint)
    alm_apply = _merge(ctx.slot_map.alm, current_alm)

    ctx.apply_preal_map = preal_apply
    ctx.apply_pint_map = pint_apply
    ctx.apply_alm_map = alm_apply
    return preal_apply, pint_apply, alm_apply



def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "check_state_commit":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.excel_loaded else 'Excel no cargado'}"
        )
    if step_nombre == "check_blocks_commit":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.bloques_loaded else 'Sin cache de bloques'}"
        )
    if step_nombre == "build_slot_maps_commit":
        if ctx.slot_map is None:
            return f"{step_nombre}: slot_map no inicializado"
        # slot_map_size incluye el slot 0 placeholder "NO USAR"
        # (1 + N_MAX reales). N_MAX es el dato del Excel (sin el
        # placeholder). Mostrar ambos evita confusion: el operario
        # espera N_MAX=PReal (el campo del proceso), no el tamano
        # del slot_map.
        sm = ctx.slot_map
        nmax = getattr(sm, "nmax", {}) or {}
        return (
            f"{step_nombre}: "
            f"slot_map(PReal={len(sm.preal)}, PInt={len(sm.pint)}, "
            f"ALM={len(sm.alm)}) "
            f"N_MAX(PReal={nmax.get('preal', '?')}, "
            f"PInt={nmax.get('pint', '?')}, "
            f"ALM={nmax.get('alm', '?')}) "
            f"N_MAX_ops={len(ctx.nmax_ops)}"
        )
    if step_nombre == "sync_nmax":
        ops = len(ctx.nmax_ops or [])
        return f"{step_nombre}: {ops} N_MAX aplicadas (incondicional)"
    if step_nombre == "wait_consolidation":
        return f"{step_nombre}: 2s sleep OK"
    if step_nombre == "compile_proc_blocks":
        if ctx.compile_ok:
            return f"{step_nombre}: OK"
        return f"{step_nombre}: ERROR ({ctx.compile_error})"
    if step_nombre == "open_transaction":
        ops = (ctx.tx_result or {}).get("operations_executed", 0)
        return f"{step_nombre}: {ops} ops aplicadas OK"
    if step_nombre == "post_preview":
        return (
            f"{step_nombre}: "
            f"{'preview regenerado OK' if ctx.post_sync_preview else 'preview fallo (warning en log)'}"
        )
    if step_nombre == "done":
        return f"{step_nombre}: sync compuesto"
    return f"{step_nombre}: OK"


__all__ = ["FunctionProcSincronizar"]
