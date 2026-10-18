"""FB core: preparar los 10 campos extendidos del DTO ``DataBloquePLC``.

Operacion READ-ONLY. Para cada path seleccionado:

  1. Busca el bloque en ``app_cache.plc_blocks[plc_name].blocks`` (cache IT
     ya poblado por ``scan_blocks``). NO navega el arbol .NET de TIA.
  2. Extrae las 6 props extendidas que ya trae el cache (``title`` /
     ``comment`` / ``author`` / ``version`` / ``programming_language`` /
     ``memory_layout``; ``comment`` siempre ``None`` en el cache).
  3. Exporta el bloque a ``.s7dcl`` en
     ``layout.preview_for_plc(plc_name)`` via dispatch del comando OT
     ``export_block``.
  4. Parsea el header SCL del ``.s7dcl`` para extraer ``S7_BlockTitle`` y
     ``S7_BlockComment`` (los unicos que ``get_property`` NO expone y el
     scan no captura).
  5. Cruza las 2 fuentes en un ``DataBloquePLC`` de 10 campos y lo guarda
     en ``app_cache.block_edit_prepared[plc_name][path]``.

Los exports SD se escriben en ``./.build_cache/blocks_edit/preview/<plc>/``
para que el operario pueda inspeccionarlos tras un bug de parseo. No
hay limpieza automatica en ``on_finish``: los archivos quedan en disco.
No hay transaccion: si TIA falla en cualquier punto del lote, los bloques
ya preparados siguen en ``app_cache`` (la SPA los muestra aunque el
batch no haya completado).

Runtime params via ``start(**kwargs)``:

  - ``plc_name`` (str): nombre del PLC. Obligatorio.
  - ``selected_block_paths`` (list[str]): rutas TIA tipo
    ``"2000_Dispositivos/DB2000_ED"`` (separador ``"/"``). El ultimo
    segmento es el nombre del bloque; el resto es la jerarquia de
    grupos. Obligatorio (no vacio).

``self.result`` se popula con la shape::

    {
        "ok": bool,
        "plc_name": str,
        "n_blocks": int,
        "n_with_title": int,
        "n_with_comment": int,
    }
"""
from __future__ import annotations

import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.data.data_block_plc import DataBloquePLC
from core.helpers.blocks_edit._workdir_layout import (
    BlocksEditLayout,
    blocks_edit_cache,
)
from core.infrastructure.tia.tia_export_paths import SdPair
from core.runtime.app_cache import AppCache, get_app_cache

logger = logging.getLogger(__name__)


class FunctionBlockEditPrepare(FunctionBase):
    """FB core: preparar los 10 campos extendidos del DTO de bloques.

    NO navega el arbol de TIA Portal (no usa ``_find_block_in_plc``):
    sigue el mismo patron que ``entidades_generar_preview`` y
    ``proc_db_generar_preview``, que iteran ``app_cache.plc_blocks``
    (cache IT del scan) y usan ``SdPair`` para los paths de los SD.
    """

    # Cada export ``export_block`` puede tardar ~5-10s en cold-start.
    # Holgura generosa para un lote de N bloques.
    STEP_TIMEOUT_S: float = 60.0

    def __init__(
        self,
        nombre: str = "block_edit_prepare",
        titulo: str = "Preparar datos de edicion de bloques TIA",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,  # legacy; ignorado si ``layout`` presente
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
        layout: BlocksEditLayout | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "validar"},
                {"nombre": "leer_tia"},
                {"nombre": "exportar_sd"},
                {"nombre": "parsear_scl"},
                {"nombre": "merge_cache"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # legacy; ignorado si layout presente.
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # Workdir de exports SD. Si el caller no lo inyecta, usamos el
        # default (``.build_cache/blocks_edit/``, absoluto via ``os.getcwd``
        # dentro del layout).
        self._layout: BlocksEditLayout = layout or blocks_edit_cache()
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._selected_block_paths: list[str] = []
        self._blocks_data: list[dict[str, Any]] = []

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``plc_name`` y ``selected_block_paths``."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionBlockEditPrepare.start(plc_name=...) es obligatorio"
            )
        selected_block_paths = params.get("selected_block_paths") or []
        if not selected_block_paths:
            raise ValueError(
                "FunctionBlockEditPrepare.start(selected_block_paths=...) "
                "debe ser una lista no vacia"
            )
        self._plc_name = str(plc_name)
        self._selected_block_paths = [
            str(p) for p in selected_block_paths
        ]
        logger.debug(
            f"[{self.nombre}] Iniciando preparacion de "
            f"{len(self._selected_block_paths)} bloques en '{self._plc_name}'"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 5 pasos."""
        # Lazy import para evitar ciclo con core.infrastructure.tia.
        from core.infrastructure.tia.tia_cache import plc_blocks_get
        from core.infrastructure.tia.tia_helpers import (
            parse_extended_props_from_sd,
        )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "validar":
                # Validacion ya en on_start (fuerza fail-fast antes de
                # tocar TIA). Aqui solo retornamos un detalle.
                return (
                    f"seleccion valida: {len(self._selected_block_paths)} "
                    f"bloques en PLC '{self._plc_name}'"
                )

            case "leer_tia":
                # Lee del cache IT poblado por ``scan_blocks``. NO navega
                # el arbol TIA (mismo patron que entidades/proc preview).
                plc_cache = plc_blocks_get(self._app_cache, self._plc_name)
                if plc_cache is None:
                    raise RuntimeError(
                        f"plc_blocks no cacheado para '{self._plc_name}'; "
                        "ejecuta scan_blocks primero"
                    )
                cached_blocks = plc_cache.blocks

                read_count = 0
                for path in self._selected_block_paths:
                    block_name = path.rsplit("/", 1)[-1].strip('"')
                    if not block_name:
                        continue
                    cached = cached_blocks.get(
                        DataBloquePLC.normalize_name(block_name)
                    )
                    if cached is None:
                        logger.warning(
                            f"[{self.nombre}] '{block_name}' no esta en "
                            f"plc_blocks[{self._plc_name}].blocks; skip"
                        )
                        continue
                    entry = {
                        "path": path,
                        "name": cached.nombre,
                        "number": cached.numero,
                        "tipo": (
                            cached.tipo
                            or DataBloquePLC.detect_tipo(cached.nombre)
                        ),
                        "base_props": {
                            "title": cached.title,
                            "comment": cached.comment,
                            "author": cached.author,
                            "version": cached.version,
                            "programming_language": cached.programming_language,
                            "memory_layout": cached.memory_layout,
                        },
                    }
                    self._blocks_data.append(entry)
                    read_count += 1

                return f"leidos {read_count} bloques via app_cache.plc_blocks"

            case "exportar_sd":
                # ``tia_client`` solo se necesita aqui para dispatch del
                # comando OT ``export_block``. NO se usa para navegar el
                # arbol TIA (eso lo hace el worker OT internamente).
                if self._tia_client is None:
                    raise RuntimeError(
                        "FunctionBlockEditPrepare requiere tia_client "
                        "para dispatch de export_block."
                    )
                # Directorio de exports SD via layout (path absoluto,
                # requisito del SDK Openness de TIA).
                plc_dir = self._layout.preview_for_plc(self._plc_name)
                plc_dir.mkdir(parents=True, exist_ok=True)

                exported_count = 0
                for entry in self._blocks_data:
                    block_name = entry.get("name") or ""
                    if not block_name:
                        continue
                    try:
                        dispatch_result = self._tia_client.dispatch(
                            "export_block",
                            {
                                "plc_name": self._plc_name,
                                "block_name": block_name,
                                "target_dir": str(plc_dir),
                                "keep_folder_structure": False,
                            },
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[{self.nombre}] export_block exception "
                            f"para '{block_name}': "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue
                    if not isinstance(dispatch_result, dict) or not dispatch_result.get("ok"):
                        logger.warning(
                            f"[{self.nombre}] export_block fallo para "
                            f"'{block_name}': "
                            f"{dispatch_result.get('error') if isinstance(dispatch_result, dict) else dispatch_result}"
                        )
                        continue
                    entry["sd_path"] = SdPair(plc_dir, block_name).dcl
                    exported_count += 1

                return f"exportados {exported_count} bloques SD a {plc_dir}"

            case "parsear_scl":
                parsed_count = 0
                for entry in self._blocks_data:
                    sd_path = entry.get("sd_path")
                    base_props = entry.get("base_props") or {
                        "title": None,
                        "comment": None,
                        "author": None,
                        "version": None,
                        "programming_language": None,
                        "memory_layout": None,
                    }
                    try:
                        extended = parse_extended_props_from_sd(
                            sd_path, base_props,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[{self.nombre}] parse_extended_props_from_sd "
                            f"exception para '{entry.get('name')}': "
                            f"{type(exc).__name__}: {exc}"
                        )
                        extended = dict(base_props)
                    entry["extended_props"] = extended
                    parsed_count += 1

                return f"parseados {parsed_count} headers SCL"

            case "merge_cache":
                # Inicializar el slot global en app_cache si no existe.
                # (Commit A.3 declarara el slot formalmente en AppCache;
                # este commit lo crea ad-hoc para mantener compat con el
                # FB ``block_edit_apply`` y el router ``blocks_edit``.)
                if not hasattr(self._app_cache, "block_edit_prepared"):
                    self._app_cache.block_edit_prepared = {}
                target = self._app_cache.block_edit_prepared.setdefault(
                    self._plc_name, {},
                )

                merged_count = 0
                for entry in self._blocks_data:
                    ext = entry.get("extended_props") or {}
                    dto = DataBloquePLC(
                        nombre=entry.get("name", "") or "",
                        numero=int(entry.get("number", 0) or 0),
                        tipo=entry.get("tipo", "OTHER") or "OTHER",
                        ruta=entry.get("path", "") or "",
                        title=ext.get("title"),
                        comment=ext.get("comment"),
                        author=ext.get("author"),
                        version=ext.get("version"),
                        programming_language=ext.get("programming_language"),
                        memory_layout=ext.get("memory_layout"),
                    )
                    target[entry["path"]] = dto
                    merged_count += 1

                self._stats["merge_cache"] = {
                    "n_blocks": merged_count,
                    "n_with_title": sum(
                        1 for e in self._blocks_data
                        if (e.get("extended_props") or {}).get("title")
                    ),
                    "n_with_comment": sum(
                        1 for e in self._blocks_data
                        if (e.get("extended_props") or {}).get("comment")
                    ),
                }
                return f"merge OK: {merged_count} bloques en app_cache"

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result``. Los SD quedan en ``layout.preview`` para
        inspeccion post-mortem del operario (NO hay cleanup automatico)."""
        merge_stats = self._stats.get("merge_cache", {})
        n_blocks = merge_stats.get("n_blocks", len(self._blocks_data))
        self.result = {
            "ok": True,
            "plc_name": self._plc_name,
            "n_blocks": n_blocks,
            "n_with_title": merge_stats.get("n_with_title", 0),
            "n_with_comment": merge_stats.get("n_with_comment", 0),
        }


__all__ = ["FunctionBlockEditPrepare"]
