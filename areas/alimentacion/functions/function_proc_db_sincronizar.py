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

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionProcDBSincronizar(FunctionBase):
    """FB que aplica comentarios del proceso contra TIA en una sola TX."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 1 transaccion TIA con 2 sub-comandos
    # (``update_proc_comments_db_param`` + ``update_proc_comments_db_alm``).
    # TIA V21 puede tardar 1-3 min en PLCs grandes.
    STEP_TIMEOUT_S: float = 300.0

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
                {"nombre": "check_state_commit"},
                {"nombre": "check_blocks_commit"},
                {"nombre": "build_slot_maps_commit"},
                {"nombre": "sync_nmax"},
                {"nombre": "wait_consolidation"},
                {"nombre": "compile_proc_blocks"},
                {"nombre": "open_transaction"},
                {"nombre": "post_preview"},
                {"nombre": "done"},
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
            from core.infrastructure.tia.tia_bloque_cache import (
                TIADataBloqueCache,
            )
            self._bloques_cache = TIADataBloqueCache._caches.get(
                self._plc_name
            )

        # Crear el ProcSyncContext que las 4 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            ProcSyncContext,
        )
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
        match step_nombre:
            case "check_state_commit":
                self.proc_check_state_commit()
                # Pre-flight: abortar con RuntimeError si no hay excel.
                if not self._ctx.excel_loaded:
                    raise RuntimeError(
                        "AppState.excel_cache esta vacio. "
                        "Cargue el Excel con POST /api/v1/excel/upload."
                    )
            case "check_blocks_commit":
                self.proc_check_blocks_commit()
                if not self._ctx.bloques_loaded:
                    raise RuntimeError(
                        "Cache de bloques del PLC no disponible. "
                        "Selecciona el PLC en el sidebar y espera al "
                        "escaneo de bloques (1-3 min en PLCs grandes)."
                    )
            case "build_slot_maps_commit":
                self.proc_build_slot_maps_commit()
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
                # app_state). Separamos el calculo del dispatch para
                # poder loguear el resultado del diff y abortar si
                # falla el parser, sin abrir Tx A.
                self.proc_compute_nmax_ops()
                logger.debug(
                    f"[{self.nombre}] N_MAX diff: "
                    f"{len(self._ctx.nmax_ops)} ops a aplicar"
                )
            case "sync_nmax":
                # INCONDICIONAL (requisito del operario): aunque
                # ``ctx.nmax_ops=[]``, se despacha el handler. Asi el
                # flujo se ejecuta completo aunque ya estuvieran
                # aplicados.
                await self.proc_sync_nmax()
            case "wait_consolidation":
                await self.proc_wait_consolidation()
            case "compile_proc_blocks":
                await self.proc_compile_blocks()
                if not self._ctx.compile_ok:
                    raise RuntimeError(
                        f"compile_proc_blocks reporto error: "
                        f"{self._ctx.compile_error}"
                    )
            case "open_transaction":
                await self.proc_open_transaction()
            case "post_preview":
                # Regenera el preview tras el commit para que la SPA
                # vea "todo en sync" sin pedir un preview manual. Si
                # TIA aun esta consolidando Tx B, el helper captura la
                # excepcion y deja ctx.post_sync_preview=None (warning
                # en log). El operario puede lanzar preview manual.
                await self.proc_post_preview()
            case "done":
                # ``proc_done_summary_commit`` compone ``ctx.result``;
                # el FB lo vuelca a ``self.result`` en ``on_finish``.
                self.proc_done_summary_commit()
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        # Resumen legible del step que acaba de correr.
        return _step_summary(self._ctx, step_nombre)

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



# ============================================================================
# Codigo absorbido de helpers/proc/proc_sincronizar.py (commit 22, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora vive como metodos del FB (mutando ``self._ctx``).
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


def proc_check_state_commit(self) -> None:
    """Comprueba que ``AppState.excel_cache`` esta cargado.

    Si no, marca ``self._ctx.excel_loaded = False`` para que el FB aborte
    con un mensaje accionable antes de tocar el gateway.
    """
    if self._ctx.app_state is None or self._ctx.app_state.excel_cache is None:
        self._ctx.excel_loaded = False
        return
    self._ctx.excel_loaded = True


def proc_check_blocks_commit(self) -> None:
    """Comprueba que el cache de bloques del PLC esta disponible.

    Marca ``self._ctx.bloques_loaded`` para que el FB aborte con un mensaje
    accionable si falta.
    """
    self._ctx.bloques_loaded = self._ctx.bloques_cache is not None


def proc_build_slot_maps_commit(self) -> None:
    """Recalcula slot maps desde ``AppState``.

    Si falla (``RuntimeError`` por uid inexistente, PLC sin bloques,
    etc.), se propaga al FB que decide si abortar.
    """
    from areas.alimentacion.data.data_ProcSlotMap import proc_build_slot_maps
    self._ctx.slot_map = proc_build_slot_maps(
        self._ctx.app_state, self._ctx.config_manager, self._ctx.proc_uid, self._ctx.bloques_cache
    )


async def proc_open_transaction(self) -> None:
    """Orquesta las 5 fases del sync de comentarios y dispara el lote final.

    Fases (cada una es una funcion publica testeable):
      1. proc_tx_b_limpiar: limpia el workdir.
      2. proc_tx_b_detectar_eliminar_export: re-exporta PARAM + ALM.
      3. proc_tx_b_detectar_eliminar_read: lee comentarios actuales.
      4. proc_tx_b_calcular_apply_maps: mezcla Excel + "eliminar" (".").
      5. proc_tx_b_construir_ops: compone las 2 ops del lote.

    Tras las 5 fases, hace 6 commits inline sobre los archivos
    exportados y un ``import_block`` al PLC.
    """
    codigo = (
        self._ctx.slot_map.db_param_name.split("_")[1]
        if "_" in self._ctx.slot_map.db_param_name
        else self._ctx.proc_uid
    )
    undo_text = f"Sync comentarios proceso {codigo} ({self._ctx.plc_name})"

    # Phase 1
    proc_tx_b_limpiar(ctx)

    # Phase 2 + 3: re-export + read current. Modo degradado:
    # si el re-export o la lectura falla, seguimos con
    # current_* vacios (el apply solo aplicara los slots del Excel,
    # sin detectar "eliminar"). El operario lo vera como
    # "renombrar / agregar", no "eliminar".
    try:
        await proc_tx_b_detectar_eliminar_export(ctx)
        current_preal, current_pint, current_alm = (
            await proc_tx_b_detectar_eliminar_read(ctx)
        )
    except Exception as exc:
        logger.warning(
            f"proc_open_transaction: re-lectura de TIA para "
            f"detectar 'eliminar' fallo: {exc!r}. El apply solo "
            f"aplicara los slots del Excel (modo degradado)."
        )
        current_preal, current_pint, current_alm = {}, {}, {}

    proc_tx_b_calcular_apply_maps(ctx, current_preal, current_pint, current_alm)

    # 6 commits sobre el DB PARAM (PReal + 3 satellites + PInt + 2 satellites)
    # y 1 sobre el DB ALM. Cada commit opera sobre el archivo exportado.
    details: list[dict[str, Any]] = []
    operations_executed = 0
    param_modified = False
    alm_modified = False

    if self._ctx.exports_param_dir is not None:
        preal_apply_int = {int(k): v for k, v in self._ctx.apply_preal_map.items()}
        pint_apply_int = {int(k): v for k, v in self._ctx.apply_pint_map.items()}
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
            slot_map = preal_apply_int if array_name.startswith(("PReal", "Aux.PReal")) else pint_apply_int
            if not slot_map:
                continue
            result = commit_array_comments(
                SdPair(Path(self._ctx.exports_param_dir), self._ctx.slot_map.db_param_name).dcl,
                SdPair(Path(self._ctx.exports_param_dir), self._ctx.slot_map.db_param_name).res,
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
            if (len(result.injected) + len(result.updated) + len(result.removed)) > 0:
                param_modified = True

    if self._ctx.exports_alm_dir is not None:
        alm_apply_int = {int(k): v for k, v in self._ctx.apply_alm_map.items()}
        if alm_apply_int:
            from core.helpers.simatic_sd import commit_array_comments
            from core.infrastructure.tia.tia_export_paths import SdPair
            result = commit_array_comments(
                SdPair(Path(self._ctx.exports_alm_dir), self._ctx.slot_map.db_alm_name).dcl,
                SdPair(Path(self._ctx.exports_alm_dir), self._ctx.slot_map.db_alm_name).res,
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
            if (len(result.injected) + len(result.updated) + len(result.removed)) > 0:
                alm_modified = True

    plc_name = (
        self._ctx.bloques_cache.plc_name if self._ctx.bloques_cache is not None else ""
    )
    import shutil
    from areas.alimentacion.helpers.build_cache import build_cache

    if (param_modified or alm_modified) and plc_name:
        proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
        modified_root = proc_ctx.modified_bloques

        if param_modified and self._ctx.exports_param_dir is not None:
            modified_param_dir = (
                str(Path(modified_root) / self._ctx.slot_map.param_subpath)
                if self._ctx.slot_map.param_subpath
                else str(modified_root)
            )
            if Path(self._ctx.exports_param_dir).exists():
                Path(modified_param_dir).mkdir(parents=True, exist_ok=True)
                shutil.copytree(
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
                shutil.copytree(
                    self._ctx.exports_alm_dir, modified_alm_dir,
                    dirs_exist_ok=True,
                )

        # Un solo import_block: TIA recorre modified_bloques y hace
        # match UPDATE por nombre de bloque preservando su subpath.
        await dispatch_async(
            self._ctx.tia_client,
            "import_block",
            {
                "plc_name": plc_name,
                "import_dir": str(modified_root),
                "target_folder": "",
            },
            timeout_s=600.0,
        )

    self._ctx.tx_result = {
        "operations_executed": operations_executed,
        "details": details,
    }


def proc_compute_nmax_ops(self) -> None:
    """Calcula las ops de N_MAX con ``proc_compute_nmax_diff``.

    Los N_MAX del proceso viven en su tabla (``slot_map.table_name``),
    no en la tabla global de dispositivos. Si la tabla no esta
    exportada en TIA, el helper lanza ``RuntimeError`` y el FB aborta.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )

    if self._ctx.tags_base is None:
        proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
        self._ctx.tags_base = proc_ctx.preview_variables

    self._ctx.nmax_ops = proc_compute_nmax_diff(
        self._ctx.tags_base, self._ctx.proc_uid, self._ctx.slot_map,
    )


async def proc_sync_nmax(self) -> None:
    """Despacha ``commit_user_constants_online`` con las ops de N_MAX.

    El handler abre y cierra su propia tx TIA (mix de set_property +
    import_plc_tags en la misma tx hacia rollback silencioso en V21).

    Siempre se despacha, incluso con ``nmax_ops=[]``, para que el flujo
    completo se ejecute.
    """
    nmax_result = await dispatch_async(
        self._ctx.tia_client,
        "commit_user_constants_online",
        {
            "plc_name": self._ctx.plc_name,
            "nmax_ops": self._ctx.nmax_ops,
            "rename_ops": [],
            "undo_text": f"Sync N_MAX proceso {self._ctx.proc_uid} ({self._ctx.plc_name})",
        },
    )
    if not nmax_result.get("ok"):
        raise RuntimeError(
            f"commit_user_constants_online fallo: "
            f"{nmax_result.get('error') or '<sin error>'}"
        )
    self._ctx.nmax_result = nmax_result.get("result") or {}


async def proc_wait_consolidation(self) -> None:
    """Sleep 2s para que TIA consolide internamente tras Tx A.

    Mismo patron que ``disp_Sincronizar.wait_consolidation``.
    Antes del compile, TIA necesita haber aplicado los N_MAX en su
    modelo interno; si no, el resize de los DBs PARAM/ALM no esta
    visible para ``compile_blocks``.
    """
    await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)


def proc_discover_compile_dbs(self) -> list[str]:
    """Devuelve los nombres canonicos de DBs a compilar tras Tx A.

    Para proc son los 2 DBs del proceso actual:
      - ``db_param_name`` (PReal + PInt)
      - ``db_alm_name`` (Alarmas)

    Si ``self._ctx.slot_map`` no esta inicializado aun, retorna ``[]``.
    El FB se asegura de invocar este helper DESPUES de
    ``proc_build_slot_maps_commit``.
    """
    if self._ctx.slot_map is None:
        return []
    return [self._ctx.slot_map.db_param_name, self._ctx.slot_map.db_alm_name]


async def proc_compile_blocks(self) -> None:
    """Compila los DBs PARAM + ALM del proceso actual.

    Patron paralelo a ``disp_Sincronizar.compilar_bloques``: dispatch
    de ``compile_blocks`` con ``block_names=[param_db, alm_db]``.
    Timeout 120s para PLCs grandes (la compilacion tras un resize de
    N_MAX puede tardar).

    Si TIA reporta errores parciales, marca ``self._ctx.compile_ok=False``
    y guarda el mensaje en ``self._ctx.compile_error`` (el FB lo evalua
    en su post-step).
    """
    block_names = proc_discover_compile_dbs(ctx)
    if not block_names:
        self._ctx.compile_ok = False
        self._ctx.compile_error = (
            "proc_discover_compile_dbs retorno []: self._ctx.slot_map no "
            "inicializado. Fallo previo en build_slot_maps_commit."
        )
        return

    try:
        compile_result = await dispatch_async(
            self._ctx.tia_client,
            "compile_blocks",
            {"plc_name": self._ctx.plc_name, "block_names": block_names},
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
        n_not_found = len((self._ctx.compile_result or {}).get("not_found", []))
        self._ctx.compile_error = (
            f"TIA reporta errores de compilacion post-N_MAX: "
            f"{n_had} bloque(s) con errores, "
            f"{n_err} excepcion(es), "
            f"{n_not_found} no encontrado(s). "
            f"Revisa el proyecto en TIA Portal: los DBs pueden haber "
            f"quedado con tamano inconsistente tras el resize."
        )
        logger.warning(
            f"[{self._ctx.plc_name}] Compilacion parcial proc tras N_MAX: "
            f"{compile_result}"
        )


def proc_done_summary_commit(self) -> dict[str, Any]:
    """Compone el ``self._ctx.result`` con el shape legacy de la SPA.

    Inspecciona ``self._ctx.tx_result`` para extraer el resumen del lote
    (``operations_executed``, ``details``) y los warnings del
    slot_map.

    Args:
        ctx: contexto con todos los pasos previos ejecutados.

    Returns:
        El mismo dict que se asigna a ``self._ctx.result``.
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
    return self._ctx.result


async def proc_post_preview(self) -> None:
    """Genera el preview post-sync para que la SPA vea 'todo en sync'.

    Reusa las 5 funciones de ``proc_generar_preview``
    (``proc_check_state``, ``proc_check_blocks``,
    ``proc_build_slot_maps``, ``proc_compute_nmax``,
    ``proc_export_and_diff`` y ``proc_compose_response``). Crea un
    ``ProcPreviewContext`` con las mismas deps y lo ejecuta en orden.

    Si el helper falla (e.g. TIA acabo de consolidar Tx A y aun no
    responde), captura la excepcion y deja ``self._ctx.post_sync_preview =
    None`` para que ``proc_done_summary_commit`` siga emitiendo el
    shape legacy completo (con ``post_sync_preview=None``). El operario
    puede entonces lanzar un preview manual desde la SPA.
    """
    from areas.alimentacion.helpers.proc.proc_generar_preview import (
        ProcPreviewContext,
        proc_build_slot_maps as pv_build_slot_maps,
        proc_check_blocks as pv_check_blocks,
        proc_check_state as pv_check_state,
        proc_compose_response as pv_compose_response,
        proc_compute_nmax as pv_compute_nmax,
        proc_export_and_diff as pv_export_and_diff,
    )

    pv_ctx = ProcPreviewContext(
        plc_name=self._ctx.plc_name,
        proc_uid=self._ctx.proc_uid,
        tia_client=self._ctx.tia_client,
        config_manager=self._ctx.config_manager,
        app_state=self._ctx.app_state,
        build_cache_root=self._ctx.build_cache_root,
        bloques_cache=self._ctx.bloques_cache,
    )

    try:
        pv_check_state(pv_ctx)
        pv_check_blocks(pv_ctx)
        pv_build_slot_maps(pv_ctx)
        await pv_compute_nmax(pv_ctx)
        await pv_export_and_diff(pv_ctx)
        pv_compose_response(pv_ctx)
        self._ctx.post_sync_preview = pv_ctx.result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[{self._ctx.plc_name}/proceso {self._ctx.proc_uid}] Post-sync "
            f"preview fallo (commit ya aplicado): {exc!r}. "
            f"El operario puede lanzar preview manual desde la SPA."
        )
        self._ctx.post_sync_preview = None


# Cada fase es una funcion publica testeable. ``proc_open_transaction``
# las orquesta en orden y luego hace el dispatch final.


def proc_tx_b_limpiar(self) -> None:
    """Fase limpia el workdir antes del batch.

    Borra ``exports/`` y ``modified/`` para evitar archivos stale de
    runs anteriores (stale = "Import failed because object with name
    X already exists").
    """
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
    proc_ctx.clean()
    self._ctx.work_dir = proc_ctx.modified_bloques
    self._ctx.exports_subdir = proc_ctx.exports_bloques


async def proc_tx_b_detectar_eliminar_export(self) -> None:
    """Fase re-exporta los 2 DBs a ``exports/<subpath>/``.

    Si falla, el FB aborta (no tiene sentido continuar sin estado
    actual fiable).
    """
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=self._ctx.build_cache_root).procesos
    plc_name = (
        self._ctx.bloques_cache.plc_name
        if self._ctx.bloques_cache is not None
        else ""
    )

    param_subpath = self._ctx.slot_map.param_subpath or ""
    alm_subpath = self._ctx.slot_map.alm_subpath or ""

    exports_param_dir = (
        str(proc_ctx.exports_bloques / param_subpath)
        if param_subpath else str(proc_ctx.exports_bloques)
    )
    exports_alm_dir = (
        str(proc_ctx.exports_bloques / alm_subpath)
        if alm_subpath else str(proc_ctx.exports_bloques)
    )

    await dispatch_async(
        self._ctx.tia_client,
        "export_block",
        {
            "plc_name": plc_name,
            "block_name": self._ctx.slot_map.db_param_name,
            "target_dir": exports_param_dir,
        },
        timeout_s=120.0,
    )
    await dispatch_async(
        self._ctx.tia_client,
        "export_block",
        {
            "plc_name": plc_name,
            "block_name": self._ctx.slot_map.db_alm_name,
            "target_dir": exports_alm_dir,
        },
        timeout_s=120.0,
    )
    self._ctx.exports_param_dir = exports_param_dir
    self._ctx.exports_alm_dir = exports_alm_dir


async def proc_tx_b_detectar_eliminar_read(
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
        dcl_param = SdPair(Path(self._ctx.exports_param_dir), self._ctx.slot_map.db_param_name).dcl
        res_param = SdPair(Path(self._ctx.exports_param_dir), self._ctx.slot_map.db_param_name).res
        dcl_alm = SdPair(Path(self._ctx.exports_alm_dir), self._ctx.slot_map.db_alm_name).dcl
        res_alm = SdPair(Path(self._ctx.exports_alm_dir), self._ctx.slot_map.db_alm_name).res

        dcl_param_text = dcl_param.read_text(encoding="utf-8-sig") \
            if dcl_param.exists() else ""
        res_param_text = res_param.read_text(encoding="utf-8-sig") \
            if res_param.exists() else ""
        dcl_alm_text = dcl_alm.read_text(encoding="utf-8-sig") \
            if dcl_alm.exists() else ""
        res_alm_text = res_alm.read_text(encoding="utf-8-sig") \
            if res_alm.exists() else ""

        preal_slots = sorted(
            set(self._ctx.slot_map.preal.keys())
            | find_array_slots(dcl_param_text, "PReal", "UDT")
        )
        pint_slots = sorted(
            set(self._ctx.slot_map.pint.keys())
            | find_array_slots(dcl_param_text, "PInt", "UDT")
        )
        alm_slots = sorted(
            set(self._ctx.slot_map.alm.keys())
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
            f"proc_tx_b_detectar_eliminar_read: parseo de 'es-ES' "
            f"fallo ({exc!r}). apply solo aplicara slots del Excel "
            f"(modo degradado)."
        )
        return {}, {}, {}

    return current_preal, current_pint, current_alm


def proc_tx_b_calcular_apply_maps(
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

    preal_apply = _merge(self._ctx.slot_map.preal, current_preal)
    pint_apply = _merge(self._ctx.slot_map.pint, current_pint)
    alm_apply = _merge(self._ctx.slot_map.alm, current_alm)

    self._ctx.apply_preal_map = preal_apply
    self._ctx.apply_pint_map = pint_apply
    self._ctx.apply_alm_map = alm_apply
    return preal_apply, pint_apply, alm_apply


def proc_tx_b_construir_ops(self) -> list[dict[str, Any]]:
    """Fase compone las 2 OT ops (PARAM + ALM).

    1 op combinada para PReal + PInt sobre el mismo DB PARAM
    (evita el bug del doble export_block que sobreescribia el
    cambio de PReal al re-exportar para PInt).

    ``db_subpath`` es la subcarpeta TIA donde esta el DB (de
    ``DataBloqueCache.blocks[<db>].ruta``). TIA Portal V21
    requiere reimportar en la MISMA ruta donde ya existe el
    bloque, si no, falla con "object with the name already
    exists" (validado 2026-09-07).

    Guarda ``self._ctx.tx_b_ops`` y devuelve la lista.
    """
    target_folder = self._ctx.config_manager.get_tia_folder_proceso()

    operations: list[dict[str, Any]] = [
        {
            "command": "update_proc_comments_db_param",
            "args": {
                "plc_name": self._ctx.plc_name,
                "db_name": self._ctx.slot_map.db_param_name,
                "db_subpath": self._ctx.slot_map.param_subpath,
                "preal_slot_map": self._ctx.apply_preal_map,
                "pint_slot_map": self._ctx.apply_pint_map,
                "work_dir": str(self._ctx.work_dir),
                "exports_subdir": str(self._ctx.exports_subdir),
                "target_folder": target_folder,
            },
        },
        {
            "command": "update_proc_comments_db_alm",
            "args": {
                "plc_name": self._ctx.plc_name,
                "db_name": self._ctx.slot_map.db_alm_name,
                "db_subpath": self._ctx.slot_map.alm_subpath,
                "array_name": "ALM",
                "slot_map": self._ctx.apply_alm_map,
                "work_dir": str(self._ctx.work_dir),
                "exports_subdir": str(self._ctx.exports_subdir),
                "target_folder": target_folder,
            },
        },
    ]
    self._ctx.tx_b_ops = operations
    return operations


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
    "proc_check_state_commit",
    "proc_check_blocks_commit",
    "proc_build_slot_maps_commit",
    "proc_open_transaction",
    "proc_done_summary_commit",
    "proc_tx_b_limpiar",
    "proc_tx_b_detectar_eliminar_export",
    "proc_tx_b_detectar_eliminar_read",
    "proc_tx_b_calcular_apply_maps",
    "proc_tx_b_construir_ops",
    "TIA_CONSOLIDATION_SLEEP_S",
    "proc_compute_nmax_ops",
    "proc_sync_nmax",
    "proc_wait_consolidation",
    "proc_discover_compile_dbs",
    "proc_compile_blocks",
]



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
