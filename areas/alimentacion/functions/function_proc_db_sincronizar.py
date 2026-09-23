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
  - build_slot_maps_commit   -> recalcula slot maps desde AppState
  - sync_nmax                -> Tx A online (incluso si nmax_ops=[])
  - wait_consolidation       -> sleep 2s para que TIA consolide
  - compile_proc_blocks      -> compila PARAM + ALM tras el resize
  - open_transaction         -> Tx B: commits + import
  - post_preview             -> regenera preview para 'todo en sync'
  - done                     -> vuelca ctx.result a self.result
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async, validate_execute_batch_result
from core.runtime.app_state import AppState, get_app_state

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
        self._build_cache_root: Path = (
            build_cache if build_cache is not None
            else Path(os.getcwd()) / ".build_cache"
        )
        # Deps especificas.
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ``bloques_cache`` viene del gateway; el router lo inyecta.
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

        ``bloques_cache`` puede inyectarse por constructor (test) o
        leerse del singleton ``TIADataBloqueCache._caches`` (dict de
        clase, acceso sync) si el FB se registro en el engine sin esa
        dep (caso comun en prod).
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
                "FunctionProcSincronizar.start(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcSincronizar.start(proc_uid=int) es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._proc_uid = proc_uid

        # Si bloques_cache no se inyecta por constructor, leemos del
        # singleton sync (acceso directo al dict de clase). Esto permite
        # que el FB funcione tanto en tests (inyeccion directa) como
        # en prod (singleton). El FB se re-arranca por cada operacion,
        # asi que un snapshot al start es suficiente.
        if self._bloques_cache is None:
            from core.infrastructure.tia.tia_cache import (
                TIADataBloqueCache,
            )
            self._bloques_cache = TIADataBloqueCache._caches.get(
                self._plc_name
            )

        # Crear el ProcSyncContext que las 4 funciones iran mutando.
        # ``ProcSyncContext`` esta definido en este mismo modulo (al
        # final del archivo); el import legacy desde
        # ``helpers/proc/proc_sincronizar`` apunta a un modulo que
        # se elimino en F1-F11 al absorber los orquestadores a los FBs.
        self._ctx = ProcSyncContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
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

    async def run_step(self, idx: int, **params: Any) -> str:
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
                result = handler()
                if hasattr(result, "__await__"):
                    await result
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionProcDBSincronizar"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
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

        # Log de cierre, igual que hacia el use case legacy.
        ops_executed = self.result.get("operations_executed", 0)
        logger.debug(
            f"[{self.nombre}] sync completo para proceso "
            f"{self._ctx.proc_uid} en {self._ctx.plc_name}: "
            f"{ops_executed} ops aplicadas"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 9 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    def _stage_1_check_state_commit(self) -> None:
        """Stage 1: valida que ``AppState.excel_cache`` esta cargado."""
        self._ctx.excel_loaded = (
            self._ctx.app_state is not None
            and self._ctx.app_state.excel_cache is not None
        )
        if not self._ctx.excel_loaded:
            raise RuntimeError(
                "AppState.excel_cache esta vacio. "
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

        Si falla (``RuntimeError`` por uid inexistente, PLC sin bloques,
        etc.), se propaga al FB que aborta. Tras construir slot_maps,
        calcula ``ctx.nmax_ops`` (necesario para stage 4) y loguea el
        conteo.
        """
        from areas.alimentacion.data.data_ProcSlotMap import proc_build_slot_maps
        self._ctx.slot_map = proc_build_slot_maps(
            self._ctx.app_state, self._ctx.config_manager,
            self._ctx.proc_uid, self._ctx.bloques_cache,
        )
        if self._ctx.slot_map is None:
            raise RuntimeError(
                "proc_build_slot_maps_commit no inicializo "
                "ctx.slot_map. El helper fallo silenciosamente."
            )
        if self._ctx.slot_map.missing_blocks:
            raise RuntimeError(
                f"Faltan bloques en el PLC: "
                f"{self._ctx.slot_map.missing_blocks}"
            )
        # Calcular nmax_ops ANTES del step sync_nmax. El helper
        # necesita slot_map (resuelto arriba) y dimensiones (en
        # app_state). Separamos el calculo del dispatch para poder
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
        from areas.alimentacion.helpers.build_cache import build_cache

        if self._ctx.tags_base is None:
            proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
            self._ctx.tags_base = proc_ctx.preview_variables

        self._ctx.nmax_ops = _compute_nmax_ops_for_proc_apply(
            self._ctx.tags_base, self._ctx.proc_uid, self._ctx.slot_map,
        )

    async def _stage_4_sync_nmax(self) -> None:
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
        nmax_result = await dispatch_async(
            self._ctx.tia_client,
            "execute_transactional_batch",
            {
                "undo_text": (
                    f"Sync N_MAX proceso {self._ctx.proc_uid} "
                    f"({self._ctx.plc_name})"
                ),
                "operations": operations,
            },
        )
        if not nmax_result.get("ok"):
            raise RuntimeError(
                f"execute_transactional_batch fallo: "
                f"{nmax_result.get('error') or '<sin error>'}"
            )
        self._ctx.nmax_result = nmax_result.get("result") or {}

    async def _stage_5_wait_consolidation(self) -> None:
        """Stage 5: sleep 2s para que TIA consolide tras Tx A."""
        await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)

    async def _stage_6_compile_proc_blocks(self) -> None:
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
            compile_result = await dispatch_async(
                self._ctx.tia_client,
                "compile_blocks",
                {
                    "plc_name": self._ctx.plc_name,
                    "block_names": block_names,
                },
                timeout_s=120.0,
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

        Para proc son los 2 DBs del proceso actual (param + alm).
        Si ``ctx.slot_map`` no esta inicializado, retorna ``[]``.
        El stage 6 se ejecuta DESPUES de ``_stage_3`` asi que
        normalmente siempre hay slot_map.
        """
        if self._ctx.slot_map is None:
            return []
        return [
            self._ctx.slot_map.db_param_name,
            self._ctx.slot_map.db_alm_name,
        ]

    async def _stage_7_open_transaction(self) -> None:
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
            f"Sync comentarios proceso {codigo} ({self._ctx.plc_name})"
        )

        # Phase 1
        _proc_tx_b_limpiar(self._ctx)

        # Phase 2 + 3: re-export + read current. Modo degradado:
        # si el re-export o la lectura falla, seguimos con
        # current_* vacios (el apply solo aplicara los slots del Excel,
        # sin detectar "eliminar"). El operario lo vera como
        # "renombrar / agregar", no "eliminar".
        try:
            await _proc_tx_b_detectar_eliminar_export(self._ctx)
            current_preal, current_pint, current_alm = (
                await _proc_tx_b_detectar_eliminar_read(self._ctx)
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
        from areas.alimentacion.helpers.build_cache import build_cache

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
            await dispatch_async(
                self._ctx.tia_client,
                "execute_transactional_batch",
                {
                    "undo_text": (
                        f"Sync proc_db {self._ctx.proc_uid} (Tx B)"
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
                timeout_s=600.0,
            )

        self._ctx.tx_result = {
            "operations_executed": operations_executed,
            "details": details,
        }

    async def _stage_8_post_preview(self) -> None:
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

        from areas.alimentacion.helpers.build_cache import build_cache
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

            batch_result = await dispatch_async(
                self._ctx.tia_client,
                "execute_batch",
                {
                    "operations": [
                        {
                            "command": "export_block",
                            "args": {
                                "plc_name": plc_name,
                                "block_name": slot_map.db_param_name,
                                "target_dir": str(preview_bloques),
                            },
                        },
                        {
                            "command": "export_block",
                            "args": {
                                "plc_name": plc_name,
                                "block_name": slot_map.db_alm_name,
                                "target_dir": str(preview_bloques),
                            },
                        },
                        {
                            "command": "export_plc_tags_xml",
                            "args": {
                                "plc_name": plc_name,
                                "target_dir": str(preview_variables),
                                "table_names": [slot_map.table_name],
                            },
                        },
                    ],
                },
                timeout_s=120.0,
            )
            validate_execute_batch_result(
                batch_result["result"],
                undo_text="Preview post-sync proceso",
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
# convencion del operario (sept-2026); el dispatch de disp usa la
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
            f"vacío. ¿proc_uid={proc_uid} existe en AppState?"
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
# Codigo absorbido de helpers/proc/proc_sincronizar.py (commit 22, sept-2026).
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
    app_state: Any
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



# Wrappers legacy. Conservados para compat con callers / tests que
# importaban estos nombres. Usar las 4 fases publicas de Tx B.


async def _compute_apply_maps(
    ctx: ProcSyncContext,
) -> "tuple[dict[str, str], dict[str, str], dict[str, str]]":
    """DEPRECATED. Usar ``proc_tx_b_*`` directamente."""
    if not hasattr(ctx, "exports_param_dir"):
        await proc_tx_b_detectar_eliminar_export(ctx)
    current_preal, current_pint, current_alm = (
        await proc_tx_b_detectar_eliminar_read(ctx)
    )
    return proc_tx_b_calcular_apply_maps(
        ctx, current_preal, current_pint, current_alm
    )


async def _re_export_current(  # noqa: D401 - legacy shim
    ctx: ProcSyncContext,
) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
    """DEPRECATED. Usar ``proc_tx_b_detectar_eliminar_export/read``."""
    await proc_tx_b_detectar_eliminar_export(ctx)
    return await proc_tx_b_detectar_eliminar_read(ctx)


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
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    proc_ctx.clean_sincronizar()
    ctx.work_dir = proc_ctx.sync_bloques_modified
    ctx.exports_subdir = proc_ctx.sync_bloques_export


async def _proc_tx_b_detectar_eliminar_export(ctx: ProcSyncContext) -> None:
    """Fase re-exporta los 2 DBs a ``exports/<subpath>/``.

    Si falla, el FB aborta (no tiene sentido continuar sin estado
    actual fiable).
    """
    from areas.alimentacion.helpers.build_cache import build_cache

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

    batch_result = await dispatch_async(
        ctx.tia_client,
        "execute_batch",
        {
            "operations": [
                {
                    "command": "export_block",
                    "args": {
                        "plc_name": plc_name,
                        "block_name": ctx.slot_map.db_param_name,
                        "target_dir": exports_param_dir,
                    },
                },
                {
                    "command": "export_block",
                    "args": {
                        "plc_name": plc_name,
                        "block_name": ctx.slot_map.db_alm_name,
                        "target_dir": exports_alm_dir,
                    },
                },
            ],
        },
        timeout_s=120.0,
    )
    validate_execute_batch_result(
        batch_result["result"],
        undo_text="Export Tx B (param + alm)",
        plc_name=plc_name,
        log=logger,
    )
    ctx.exports_param_dir = exports_param_dir
    ctx.exports_alm_dir = exports_alm_dir


async def _proc_tx_b_detectar_eliminar_read(
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
        return (
            f"{step_nombre}: PReal={len(ctx.slot_map.preal)} "
            f"PInt={len(ctx.slot_map.pint)} ALM={len(ctx.slot_map.alm)}"
            f" N_MAX_ops={len(ctx.nmax_ops)}"
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
