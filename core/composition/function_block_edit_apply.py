"""FB core: aplicar edicion de Name/Number de N bloques TIA en transaccion atomica.

Cruza las ``edits`` del operario (path -> {name?, number?}) con el cache
``app_cache.block_edit_prepared[plc_name]`` (poblado por
``FunctionBlockEditPrepare``), calcula el diff y emite las ops
``update_block_property`` dentro de un unico ``execute_transactional_batch``
con rollback atomico si cualquier op revienta.

Solo Name y Number son editables: la whitelist del handler
``update_block_property`` (``tia_cmd_blocks.py``) acepta unicamente esas
dos properties, y este FB replica esa whitelist en ``on_start`` para
fallar rapido antes de tocar TIA si el payload trae keys no soportadas.

Estado del FB (Zona 3): el ctx del run (``self._ctx``), un
``BlockEditApplyContext`` con:

  - ``plc_name``: PLC destino (de ``params["plc_name"]``).
  - ``edits``: ``{path: {"name"?: str, "number"?: int}}``, donde
    ``path`` es la clave que la SPA uso en ``/prepare``
    (``block_edit_prepared``).
  - ``ops``: lista de ``{"command", "args"}`` para el batch (vacia si no hay diff).
  - ``batch_result``: payload ``{"success", "operations_executed", "details"}``
    retornado por el worker OT en el batch transaccional. ``None`` si no
    se llego a ejecutar.
  - ``noop_mode``: ``True`` si el diff quedo vacio (cache == edits); en ese
    caso los steps ``transaccion`` y ``verificar`` se saltean sin dispatch.

El ctx es el estado del run en curso: ``on_start()`` lo crea y
``reset_run_state()`` lo anula, de modo que un ``execute()`` no arrastra
el estado del anterior.

Runtime params via ``start(**kwargs)``:

  - ``plc_name`` (str): nombre del PLC. Obligatorio.
  - ``edits`` (dict[str, dict[str, Any]]): ``{path: {name?, number?}}``.
    ``path`` es la clave de fila devuelta por ``/prepare``. Solo keys
    ``"name"`` y/o ``"number"`` admitidas. Obligatorio (no vacio).

Tras commit OK: refresca ``app_cache.plc_blocks[plc_name]`` via
``scan_plc_blocks(force_refresh=True)`` para que el arbol refleje los
nuevos nombres/numeros, y limpia ``app_cache.block_edit_prepared[plc_name]``
(queda obsoleto: los DTOs tienen los valores pre-commit).

``self.result`` se popula con la shape::

    {
        "ok": True,
        "plc_name": str,
        "n_ops": int,                    # ops en el batch (0 si no-op).
        "operations_executed": int,      # ops reportadas por el worker.
        "no_op": bool,                   # True si se skipeo el batch.
    }

Steps (5). Cada step se declara encima de su propio codigo con ``@step``
y devuelve su detail:
  - Validar edits       -> confirma los edits ya validados en el pre-flight
  - Calcular diff       -> cruza los edits contra el cache de prepare y
                           monta las ops del batch
  - Aplicar transaccion -> ejecuta el batch transaccional contra TIA
  - Verificar resultado -> comprueba el resultado del batch
  - Refrescar cache     -> re-escanea los bloques del PLC y limpia el
                           cache de prepare
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase
from core.infrastructure.tia.tia_cache import scan_plc_blocks
from core.runtime.app_cache import AppCache, get_app_cache

logger = logging.getLogger(__name__)

# Whitelist de keys aceptadas en ``edits``. Debe coincidir con la del
# handler ``_h_update_block_property`` (``frozenset({"Name", "Number"})``).
# Sincronizar si Aketza ampla la whitelist del handler.
_ALLOWED_EDIT_KEYS: frozenset[str] = frozenset({"name", "number"})


class FunctionBlockEditApply(FunctionBase):
    """FB core: aplicar Name/Number edits a N bloques TIA atomicamente."""

    # El batch transaccional puede tardar ~5-15s por bloque (set_property
    # + verificaciones internas). Holgura generosa para ~50 bloques.
    STEP_TIMEOUT_S: float = 600.0

    def __init__(
        self,
        nombre: str = "block_edit_apply",
        titulo: str = (
            "Aplicar edicion de bloques TIA bajo transaccion atomica"
        ),
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # No usado en este FB.
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ZONA 3: estado del run. Lo crea ``on_start()`` y lo anula
        # ``reset_run_state()``.
        self._ctx: "BlockEditApplyContext | None" = None

    # ==================================================================
    # Reset del estado de Zona 3
    # ==================================================================

    def reset_run_state(self) -> None:
        """Reinicia el estado de Zona 3 antes de cada ``execute()``.

        Sin esto el batch transaccional arrastra las operaciones del run
        anterior: el dispatcher del OB1 reutiliza la instancia del FB, y
        un segundo ``execute()`` volveria a mandar a TIA los cambios ya
        aplicados. El flag ``noop_mode`` tampoco puede quedar en True de
        un run sin cambios, o el siguiente se creeria no-op.

        El ctx se anula en vez de reiniciarse campo a campo: ``on_start()``
        crea uno nuevo para el run que empieza.
        """
        self._ctx = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params y deps)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: validar params y deps, y crear el ctx del run."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionBlockEditApply.execute(plc_name=...) es obligatorio"
            )
        edits_raw = params.get("edits") or {}
        if not isinstance(edits_raw, dict) or not edits_raw:
            raise ValueError(
                "FunctionBlockEditApply.start(edits=...) debe ser un dict "
                "no vacio mapeando path -> {name?, number?}"
            )

        # Validar keys por entrada (whitelist + tipos basicos).
        # Cualquier key fuera de name/number -> fail-fast (antes de TIA).
        for path, new_props in edits_raw.items():
            if not isinstance(new_props, dict):
                raise ValueError(
                    f"FunctionBlockEditApply: edits[{path!r}] debe ser dict, "
                    f"recibido {type(new_props).__name__}"
                )
            for key in new_props.keys():
                if key not in _ALLOWED_EDIT_KEYS:
                    raise ValueError(
                        f"FunctionBlockEditApply: edits[{path!r}] "
                        f"contiene key {key!r} no permitida. Solo se "
                        f"admiten {sorted(_ALLOWED_EDIT_KEYS)}."
                    )
            if "name" in new_props and not isinstance(
                new_props["name"], str,
            ):
                raise ValueError(
                    f"FunctionBlockEditApply: edits[{path!r}]['name'] "
                    f"debe ser str, recibido "
                    f"{type(new_props['name']).__name__}"
                )
            if "number" in new_props and (
                not isinstance(new_props["number"], int)
                or isinstance(new_props["number"], bool)
            ):
                raise ValueError(
                    f"FunctionBlockEditApply: edits[{path!r}]['number'] "
                    f"debe ser int (no bool), recibido "
                    f"{type(new_props['number']).__name__}"
                )

        # Deps del worker OT: sin tia_client (o sin portal attached) no
        # hay a quien preguntar por los bloques. Fail-fast aqui: el
        # pre-flight de TIA va antes de tocar el portal.
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionBlockEditApply requiere tia_client explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client.wrapper is None:
            raise RuntimeError(
                "FunctionBlockEditApply requiere tia_client con portal "
                "attached. Llama a attach_portal antes de ejecutar el FB."
            )

        self._ctx = BlockEditApplyContext(
            plc_name=str(plc_name),
            edits={
                str(path): dict(new_props)
                for path, new_props in edits_raw.items()
            },
            ops=[],
            batch_result=None,
            noop_mode=False,
        )
        logger.debug(
            f"[{self.nombre}] Iniciando aplicacion: "
            f"plc={self._ctx.plc_name!r} n_edits={len(self._ctx.edits)}"
        )

    # ==================================================================
    # LOS STEPS
    #
    # Cada ``_stage_N_<slug>`` es un step declarado con ``@step``. El
    # motor los recoge en orden de definicion (que es el orden del
    # flujo) y hace el dispatch. El metodo devuelve su detail.
    # ==================================================================

    @step(
        "Validar edits",
        descripcion="Confirma los edits ya validados en el pre-flight",
    )
    def _stage_1_validar_edits(self) -> str:
        """Detail del step: los edits que pasaron el pre-flight."""
        # La validacion completa esta en ``on_start`` (fuerza fail-fast
        # antes de tocar TIA). Aqui solo retornamos un detalle.
        detail = (
            f"edits validados: {len(self._ctx.edits)} paths en "
            f"PLC '{self._ctx.plc_name}'"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Calcular diff",
        descripcion="Cruza los edits contra el cache de prepare y monta las ops",
    )
    def _stage_2_calcular_diff(self) -> str:
        """Compara los edits contra el cache de prepare y monta las ops."""
        # Leer cache de prepare via helper (slot declarado en
        # ``AppCache``, commit A.3). Si vacio -> fail-fast.
        prepared = self._app_cache.get_block_edit_prepared(
            self._ctx.plc_name,
        )
        if not prepared:
            raise RuntimeError(
                f"FunctionBlockEditApply: PLC '{self._ctx.plc_name}' "
                f"no esta en app_cache.block_edit_prepared. "
                f"Ejecuta block_edit_prepare primero."
            )

        # Para cada edit, comparar contra DTO cacheado y
        # construir la op solo si hay diff real.
        for path, new_props in self._ctx.edits.items():
            cached_dto = prepared.get(path)
            if cached_dto is None:
                raise RuntimeError(
                    f"FunctionBlockEditApply: bloque "
                    f"{path!r} no preparado en "
                    f"app_cache.block_edit_prepared['"
                    f"{self._ctx.plc_name}']. Ejecuta "
                    f"block_edit_prepare de nuevo."
                )

            if "name" in new_props:
                if str(new_props["name"]) == str(cached_dto.nombre):
                    continue
                self._ctx.ops.append({
                    "command": "update_block_property",
                    "args": {
                        "plc_name": self._ctx.plc_name,
                        "block_name": cached_dto.nombre,
                        "property_name": "Name",
                        "new_value": str(new_props["name"]),
                    },
                })
            if "number" in new_props:
                if int(new_props["number"]) == int(cached_dto.numero):
                    continue
                self._ctx.ops.append({
                    "command": "update_block_property",
                    "args": {
                        "plc_name": self._ctx.plc_name,
                        "block_name": cached_dto.nombre,
                        "property_name": "Number",
                        "new_value": int(new_props["number"]),
                    },
                })

        if not self._ctx.ops:
            logger.info(
                f"[{self.nombre}] {self._ctx.plc_name}: no-op, "
                f"ningun edit produce diff real contra el cache"
            )
            self._ctx.noop_mode = True

        detail = f"diff: {len(self._ctx.ops)} ops a aplicar"
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Aplicar transaccion",
        descripcion="Ejecuta el batch transaccional contra TIA Portal",
    )
    def _stage_3_aplicar_transaccion(self) -> str:
        """Manda las ops al worker OT dentro de un batch transaccional."""
        if self._ctx.noop_mode:
            return "transaccion omitida (no-op)"

        result = self._tia_client.submit_and_wait(
            "execute_transactional_batch",
            {"operations": self._ctx.ops},
            timeout=self.STEP_TIMEOUT_S,
        )
        # Shape esperada: ``{"ok": bool, "result": {"success": bool,
        # "operations_executed": int, "details": [...]}}``.
        # ``inner = {"success": False, "error": ...}`` tambien se
        # contempla por si el worker reporta error sin raise.
        if not isinstance(result, dict) or not result.get("ok"):
            err = (
                result.get("error") if isinstance(result, dict)
                else result
            )
            raise RuntimeError(
                f"FunctionBlockEditApply: dispatch fallo: {err}"
            )
        inner = result.get("result")
        if not isinstance(inner, dict):
            raise RuntimeError(
                f"FunctionBlockEditApply: dispatch result sin "
                f"'result' dict: {result!r}"
            )
        if inner.get("success") is False:
            raise RuntimeError(
                f"FunctionBlockEditApply: batch retorno "
                f"success=False: "
                f"{inner.get('error') or inner!r}"
            )

        self._ctx.batch_result = inner
        executed = inner.get("operations_executed", 0)
        detail = f"transaccion OK: {executed} ops"
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Verificar resultado",
        descripcion="Comprueba el resultado del batch transaccional",
    )
    def _stage_4_verificar_resultado(self) -> str:
        """Comprueba que el batch transaccional reporto success."""
        if self._ctx.noop_mode:
            return "verificacion omitida (no-op)"
        if self._ctx.batch_result is None:
            raise RuntimeError(
                "FunctionBlockEditApply: batch_result es None "
                "(el step 'Aplicar transaccion' no se ejecuto o fallo)"
            )
        if self._ctx.batch_result.get("success") is not True:
            raise RuntimeError(
                f"FunctionBlockEditApply: verificacion fallo, "
                f"success={self._ctx.batch_result.get('success')!r}"
            )
        executed = self._ctx.batch_result.get(
            "operations_executed", 0,
        )
        detail = f"verificado: {executed} ops ejecutadas"
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Refrescar cache",
        descripcion="Re-escanea los bloques del PLC y limpia el cache de prepare",
    )
    def _stage_5_refrescar_cache(self) -> str:
        """Re-escanea los bloques del PLC y invalida el cache de prepare."""
        cache = scan_plc_blocks(
            self._ctx.plc_name,
            force_refresh=True,
            tia_client=self._tia_client,
            app_cache=self._app_cache,
            timeout_s=60.0,
        )
        # El cache de prepare queda obsoleto (DTOs con valores
        # pre-commit). Forzar re-lectura en el siguiente Editar.
        self._app_cache.clear_block_edit_prepared(self._ctx.plc_name)
        detail = (
            f"refresh OK: {len(cache.blocks)} bloques re-escaneados"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape del FB."""
        ctx = self._ctx
        executed = (
            ctx.batch_result.get("operations_executed", 0)
            if ctx.batch_result
            else 0
        )
        self.result = {
            "ok": True,
            "plc_name": ctx.plc_name,
            "n_ops": len(ctx.ops),
            "operations_executed": executed,
            "no_op": ctx.noop_mode,
        }


@dataclass
class BlockEditApplyContext:
    """Estado del run del FB de aplicacion de edits."""

    plc_name: str
    edits: dict[str, dict[str, Any]]
    ops: list[dict[str, Any]]
    batch_result: dict[str, Any] | None
    noop_mode: bool


__all__ = ["BlockEditApplyContext", "FunctionBlockEditApply"]
