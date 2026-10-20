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

Estado del FB (Zona 3):

  - ``_plc_name``: PLC destino (de ``params["plc_name"]``).
  - ``_edits``: ``{path: {"name"?: str, "number"?: int}}``, donde
    ``path`` es la clave que la SPA uso en ``/prepare``
    (``block_edit_prepared``).
  - ``_ops``: lista de ``{"command", "args"}`` para el batch (vacia si no hay diff).
  - ``_batch_result``: payload ``{"success", "operations_executed", "details"}``
    retornado por ``dispatch_batch_async``. ``None`` si no se llego a ejecutar.
  - ``_noop_mode``: ``True`` si el diff quedo vacio (cache == edits); en ese
    caso los steps ``transaccion`` y ``verificar`` se saltean sin dispatch.

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
"""
from __future__ import annotations

import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia.tia_dispatch_async import dispatch_batch_async
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
        steps: list[dict[str, Any]] | None = None,
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
            steps=steps if steps is not None else [
                {"nombre": "Validar edits"},
                {"nombre": "Calcular diff"},
                {"nombre": "Aplicar transaccion"},
                {"nombre": "Verificar resultado"},
                {"nombre": "Refrescar cache"},
            ],
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
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._edits: dict[str, dict[str, Any]] = {}
        self._ops: list[dict[str, Any]] = []
        self._batch_result: dict[str, Any] | None = None
        self._noop_mode: bool = False

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``plc_name`` y ``edits``."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionBlockEditApply.start(plc_name=...) es obligatorio"
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

        self._plc_name = str(plc_name)
        self._edits = {
            str(path): dict(new_props)
            for path, new_props in edits_raw.items()
        }
        logger.debug(
            f"[{self.nombre}] Iniciando aplicacion: plc={self._plc_name!r} "
            f"n_edits={len(self._edits)}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 5 pasos."""
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

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "Validar edits":
                # Validacion ya en on_start (fuerza fail-fast antes de
                # tocar TIA). Aqui solo retornamos un detalle.
                detail = (
                    f"edits validados: {len(self._edits)} paths en "
                    f"PLC '{self._plc_name}'"
                )
                logger.info(
                    f"[{self.nombre}] {self._plc_name}: {detail}"
                )
                return detail

            case "Calcular diff":
                # Leer cache de prepare via helper (slot declarado en
                # ``AppCache``, commit A.3). Si vacio -> fail-fast.
                prepared = self._app_cache.get_block_edit_prepared(
                    self._plc_name,
                )
                if not prepared:
                    raise RuntimeError(
                        f"FunctionBlockEditApply: PLC '{self._plc_name}' "
                        f"no esta en app_cache.block_edit_prepared. "
                        f"Ejecuta block_edit_prepare primero."
                    )

                # Para cada edit, comparar contra DTO cacheado y
                # construir la op solo si hay diff real.
                for path, new_props in self._edits.items():
                    cached_dto = prepared.get(path)
                    if cached_dto is None:
                        raise RuntimeError(
                            f"FunctionBlockEditApply: bloque "
                            f"{path!r} no preparado en "
                            f"app_cache.block_edit_prepared['"
                            f"{self._plc_name}']. Ejecuta "
                            f"block_edit_prepare de nuevo."
                        )

                    if "name" in new_props:
                        if str(new_props["name"]) == str(cached_dto.nombre):
                            continue
                        self._ops.append({
                            "command": "update_block_property",
                            "args": {
                                "plc_name": self._plc_name,
                                "block_name": cached_dto.nombre,
                                "property_name": "Name",
                                "new_value": str(new_props["name"]),
                            },
                        })
                    if "number" in new_props:
                        if int(new_props["number"]) == int(cached_dto.numero):
                            continue
                        self._ops.append({
                            "command": "update_block_property",
                            "args": {
                                "plc_name": self._plc_name,
                                "block_name": cached_dto.nombre,
                                "property_name": "Number",
                                "new_value": int(new_props["number"]),
                            },
                        })

                if not self._ops:
                    logger.info(
                        f"[{self.nombre}] {self._plc_name}: no-op, "
                        f"ningun edit produce diff real contra el cache"
                    )
                    self._noop_mode = True

                detail = f"diff: {len(self._ops)} ops a aplicar"
                logger.info(
                    f"[{self.nombre}] {self._plc_name}: {detail}"
                )
                return detail

            case "Aplicar transaccion":
                if self._noop_mode:
                    return "transaccion omitida (no-op)"

                result = await dispatch_batch_async(
                    self._tia_client,
                    self._ops,
                    timeout_s=self.STEP_TIMEOUT_S,
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

                self._batch_result = inner
                executed = inner.get("operations_executed", 0)
                detail = f"transaccion OK: {executed} ops"
                logger.info(
                    f"[{self.nombre}] {self._plc_name}: {detail}"
                )
                return detail

            case "Verificar resultado":
                if self._noop_mode:
                    return "verificacion omitida (no-op)"
                if self._batch_result is None:
                    raise RuntimeError(
                        "FunctionBlockEditApply: _batch_result es None "
                        "(el step 'transaccion' no se ejecuto o fallo)"
                    )
                if self._batch_result.get("success") is not True:
                    raise RuntimeError(
                        f"FunctionBlockEditApply: verificacion fallo, "
                        f"success={self._batch_result.get('success')!r}"
                    )
                executed = self._batch_result.get(
                    "operations_executed", 0,
                )
                detail = f"verificado: {executed} ops ejecutadas"
                logger.info(
                    f"[{self.nombre}] {self._plc_name}: {detail}"
                )
                return detail

            case "Refrescar cache":
                cache = await scan_plc_blocks(
                    self._plc_name,
                    force_refresh=True,
                    tia_client=self._tia_client,
                    app_cache=self._app_cache,
                    timeout_s=60.0,
                )
                # El cache de prepare queda obsoleto (DTOs con valores
                # pre-commit). Forzar re-lectura en el siguiente Editar.
                self._app_cache.clear_block_edit_prepared(self._plc_name)
                detail = (
                    f"refresh OK: {len(cache.blocks)} bloques re-escaneados"
                )
                logger.info(
                    f"[{self.nombre}] {self._plc_name}: {detail}"
                )
                return detail

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape del FB."""
        executed = (
            self._batch_result.get("operations_executed", 0)
            if self._batch_result
            else 0
        )
        self.result = {
            "ok": True,
            "plc_name": self._plc_name,
            "n_ops": len(self._ops),
            "operations_executed": executed,
            "no_op": self._noop_mode,
        }


__all__ = ["FunctionBlockEditApply"]
