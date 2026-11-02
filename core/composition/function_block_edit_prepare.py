"""FB core: preparar los 10 campos extendidos del DTO ``DataBloquePLC``.

Operacion READ-ONLY. Para cada path seleccionado:

  1. Busca el bloque en ``app_cache.plc_blocks[plc_name].blocks`` (cache IT
     ya poblado por ``scan_blocks``). NO navega el arbol .NET de TIA.
  2. Extrae las 6 props extendidas que ya trae el cache (``title`` /
     ``comment`` / ``author`` / ``version`` / ``programming_language`` /
     ``memory_layout``; ``comment`` siempre ``None`` en el cache).
  3. Exporta el bloque a ``.s7dcl`` en ``layout.preview_dir`` via
     dispatch del comando OT ``export_blocks`` (1 IPC con whitelist
     de todos los nombres).
  4. Parsea el header SCL del ``.s7dcl`` para extraer ``S7_BlockTitle`` y
     ``S7_BlockComment`` (los unicos que ``get_property`` NO expone y el
     scan no captura).
  5. Cruza las 2 fuentes en un ``DataBloquePLC`` de 10 campos y lo guarda
     en ``app_cache.block_edit_prepared[plc_name][path]``.

Los exports SD se escriben en ``./.build_cache/blocks_edit/preview/``
(FLAT) para que el operario pueda inspeccionarlos tras un bug de parseo.
El step ``Exportar bloques SD`` invoca ``layout.clean_preview()`` al inicio
para borrar exports previos (asi un bloque que dejo de existir en TIA no
contamina el siguiente prepare). Los archivos del prepare actual quedan en
disco hasta el siguiente ``prepare`` del mismo PLC.
No hay transaccion: si TIA falla en cualquier punto del lote, los bloques
ya preparados siguen en ``app_cache`` (la SPA los muestra aunque el
batch no haya completado).

Runtime params via ``start(**kwargs)``:

  - ``plc_name`` (str): nombre del PLC. Obligatorio.
  - ``selected_block_paths`` (list[str]): rutas TIA tipo
    ``"2000_Dispositivos/DB2000_ED"`` (separador ``"/"``). El ultimo
    segmento es el nombre del bloque; el resto es la jerarquia de
    grupos. Obligatorio (no vacio).

Dos conceptos que no son intercambiables:

  - ``path``: clave de la fila dentro de
    ``app_cache.block_edit_prepared``. Es el elemento de
    ``selected_block_paths`` verbatim (``ruta + "/" + nombre``, o
    ``nombre`` si el bloque esta en la raiz). La SPA la construye asi y
    la devuelve en ``edits`` al aplicar.
  - ``ruta`` (``DataBloquePLC.ruta``): jerarquia de GRUPOS tal como la
    devuelve TIA (``ProgramBlock.get_path()``): ``""`` en la raiz del
    PLC, ``"Grupo/Subgrupo"`` anidado, separador ``"/"``. Nunca incluye
    el nombre del bloque.

``self.result`` se popula con la shape::

    {
        "ok": bool,
        "plc_name": str,
        "n_blocks": int,
        "n_with_title": int,
        "n_with_comment": int,
    }

Steps (5). Cada step se declara encima de su propio codigo con ``@step``
y devuelve su detail:
  - "Validar selección"      -> comprueba la seleccion del operario
  - "Leer bloques desde cache" -> lee los bloques del cache IT del scan
  - "Exportar bloques SD"    -> exporta los bloques a .s7dcl en el preview
  - "Parsear headers SCL"    -> extrae title y comment del header SCL
  - "Combinar DTOs en cache" -> cruza las 2 fuentes y guarda el DTO
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.composition.fb_step import step
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

    # Cada bloque exportado puede tardar ~5-10s en cold-start. Los N
    # bloques se exportan en serie dentro de un unico dispatch al worker OT.
    STEP_TIMEOUT_S: float = 60.0

    def __init__(
        self,
        nombre: str = "block_edit_prepare",
        titulo: str = "Preparar datos de edicion de bloques TIA",
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,  # ignorado si ``layout`` presente
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
        layout: BlocksEditLayout | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # ignorado si layout presente.
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # Workdir de exports SD. Si el caller no lo inyecta, usamos el
        # default (``.build_cache/blocks_edit/``, absoluto via ``os.getcwd``
        # dentro del layout).
        self._layout: BlocksEditLayout = layout or blocks_edit_cache()
        # ZONA 3: estado entre ticks. El ctx se recrea en cada
        # ``on_start()``: es el estado del run en curso.
        self._ctx: "BlockEditPrepareContext | None" = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``plc_name`` y ``selected_block_paths``."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionBlockEditPrepare.execute(plc_name=...) es obligatorio"
            )
        selected_block_paths = params.get("selected_block_paths") or []
        if not selected_block_paths:
            raise ValueError(
                "FunctionBlockEditPrepare.start(selected_block_paths=...) "
                "debe ser una lista no vacia"
            )
        # FB re-arrancable: una sola instancia se reusa entre prepares.
        # El ctx se recrea en cada ``on_start``: ``blocks_data`` se popula
        # en el step de lectura del cache y se consume en los steps
        # siguientes; si arrastra entries del prepare anterior, el merge
        # itera sobre ellos y el cache ``block_edit_prepared[plc_name]``
        # acaba con bloques que el operario NO selecciono en este prepare.
        self._ctx = BlockEditPrepareContext(
            plc_name=str(plc_name),
            selected_block_paths=[str(p) for p in selected_block_paths],
            blocks_data=[],
        )
        logger.debug(
            f"[{self.nombre}] Iniciando preparacion de "
            f"{len(self._ctx.selected_block_paths)} bloques "
            f"en '{self._ctx.plc_name}'"
        )

    # ==================================================================
    # LOS STEPS
    #
    # Cada ``_stage_N_<slug>`` es un step declarado con ``@step``. El
    # motor los recoge en orden de definicion (que es el orden del
    # flujo) y hace el dispatch. El metodo devuelve su detail.
    # ==================================================================

    @step(
        "Validar selección",
        descripcion="Comprueba la seleccion de bloques del operario",
    )
    def _stage_1_validar_seleccion(self) -> str:
        """La validacion fuerte ya esta en ``on_start`` (fail-fast antes
        de tocar TIA). Aqui solo se devuelve el detalle."""
        detail = (
            f"seleccion valida: {len(self._ctx.selected_block_paths)} "
            f"bloques en PLC '{self._ctx.plc_name}'"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Leer bloques desde cache",
        descripcion="Lee los bloques seleccionados del cache IT del scan",
    )
    def _stage_2_leer_bloques_desde_cache(self) -> str:
        """Lee del cache IT poblado por ``scan_blocks``.

        NO navega el arbol TIA (mismo patron que entidades/proc preview).
        """
        # Lazy import para evitar ciclo con core.infrastructure.tia.
        from core.infrastructure.tia.tia_cache import plc_blocks_get

        plc_cache = plc_blocks_get(self._app_cache, self._ctx.plc_name)
        if plc_cache is None:
            raise RuntimeError(
                f"plc_blocks no cacheado para '{self._ctx.plc_name}'; "
                "ejecuta scan_blocks primero"
            )
        cached_blocks = plc_cache.blocks

        read_count = 0
        for path in self._ctx.selected_block_paths:
            block_name = path.rsplit("/", 1)[-1].strip('"')
            if not block_name:
                continue
            cached = cached_blocks.get(
                DataBloquePLC.normalize_name(block_name)
            )
            if cached is None:
                logger.warning(
                    f"[{self.nombre}] '{block_name}' no esta en "
                    f"plc_blocks[{self._ctx.plc_name}].blocks; skip"
                )
                continue
            entry = {
                "path": path,
                # ``ruta`` es la JERARQUIA DE GRUPOS tal como la
                # devuelve TIA (``ProgramBlock.get_path()``,
                # separador "/"): "" para bloques en la raiz del
                # PLC, "Grupo/Subgrupo" para los anidados. NO
                # confundir con ``path``, que es la clave que
                # identifica la fila en este cache y que la SPA
                # construye como ``ruta + "/" + nombre``.
                "ruta": cached.ruta,
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
            self._ctx.blocks_data.append(entry)
            read_count += 1

        detail = (
            f"leidos {read_count} bloques via app_cache.plc_blocks"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Exportar bloques SD",
        descripcion="Exporta los bloques a .s7dcl en el preview",
    )
    def _stage_3_exportar_bloques_sd(self) -> str:
        """Exporta los bloques seleccionados a ``.s7dcl``.

        ``tia_client`` solo se necesita aqui para dispatch del comando
        OT ``export_blocks``. NO se usa para navegar el arbol TIA (eso
        lo hace el worker OT internamente).
        """
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionBlockEditPrepare requiere tia_client "
                "para dispatch de export_blocks."
            )
        # Directorio de exports SD via layout (path absoluto,
        # requisito del SDK Openness de TIA). Limpiamos exports
        # previos para que el workdir contenga solo los SD del
        # prepare actual (si un bloque dejo de existir en TIA, su
        # ``.s7dcl``/``.s7res`` no contamina el nuevo).
        self._layout.clean_preview()
        plc_dir = self._layout.preview_dir

        # 1 dispatch con TODOS los bloques seleccionados en vez de N
        # dispatchs en serie.
        block_names = [
            (entry.get("name") or "")
            for entry in self._ctx.blocks_data
        ]
        block_names = [n for n in block_names if n]

        if not block_names:
            return f"exportados 0 bloques SD a {plc_dir} (sin seleccion)"

        try:
            dispatch_result = self._tia_client.dispatch(
                "export_blocks",
                {
                    "plc_name": self._ctx.plc_name,
                    "target_dir": str(plc_dir),
                    "block_names": block_names,
                    "keep_folder_structure": False,
                },
            )
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] export_blocks exception: "
                f"{type(exc).__name__}: {exc}"
            )
            return f"exportados 0 bloques SD a {plc_dir} (exception)"

        if not isinstance(dispatch_result, dict) or not dispatch_result.get("ok"):
            logger.warning(
                f"[{self.nombre}] export_blocks fallo: "
                f"{dispatch_result.get('error') if isinstance(dispatch_result, dict) else dispatch_result}"
            )
            return f"exportados 0 bloques SD a {plc_dir} (fallo)"

        # El handler retorna ``exported_names`` (subconjunto OK).
        # Solo los que vienen en esa lista reciben ``sd_path``; los
        # skipped (p.ej. bloques no encontrados en TIA) quedan sin
        # sd_path y se omiten del merge.
        result = dispatch_result["result"]
        exported_set = set(result.get("exported_names", []))
        exported_count = 0
        for entry in self._ctx.blocks_data:
            name = entry.get("name") or ""
            if name in exported_set:
                entry["sd_path"] = SdPair(plc_dir, name).dcl
                exported_count += 1

        detail = (
            f"exportados {exported_count}/{len(block_names)} "
            f"bloques SD a {plc_dir}"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Parsear headers SCL",
        descripcion="Extrae title y comment del header SCL exportado",
    )
    def _stage_4_parsear_headers_scl(self) -> str:
        """Parsea el header SCL de cada ``.s7dcl`` exportado."""
        # Lazy import para evitar ciclo con core.infrastructure.tia.
        from core.infrastructure.tia.tia_helpers import (
            parse_extended_props_from_sd,
        )

        parsed_count = 0
        for entry in self._ctx.blocks_data:
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

        detail = f"parseados {parsed_count} headers SCL"
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    @step(
        "Combinar DTOs en cache",
        descripcion="Cruza las 2 fuentes y guarda el DTO en el cache",
    )
    def _stage_5_combinar_dtos_en_cache(self) -> str:
        """Cruza el cache IT y el header SCL en el DTO de 10 campos.

        Slot ``block_edit_prepared`` declarado formalmente en
        ``AppCache``; helper set/get/clear usan ``mutate(slot=...)``
        para reemplazar atomicamente.
        """
        prepared: dict[str, DataBloquePLC] = {}
        merged_count = 0
        for entry in self._ctx.blocks_data:
            ext = entry.get("extended_props") or {}
            dto = DataBloquePLC(
                nombre=entry.get("name", "") or "",
                numero=int(entry.get("number", 0) or 0),
                tipo=entry.get("tipo", "OTHER") or "OTHER",
                ruta=entry.get("ruta", "") or "",
                title=ext.get("title"),
                comment=ext.get("comment"),
                author=ext.get("author"),
                version=ext.get("version"),
                programming_language=ext.get("programming_language"),
                memory_layout=ext.get("memory_layout"),
            )
            prepared[entry["path"]] = dto
            merged_count += 1

        self._app_cache.set_block_edit_prepared(
            self._ctx.plc_name, prepared,
        )

        self._stats["merge_cache"] = {
            "n_blocks": merged_count,
            "n_with_title": sum(
                1 for e in self._ctx.blocks_data
                if (e.get("extended_props") or {}).get("title")
            ),
            "n_with_comment": sum(
                1 for e in self._ctx.blocks_data
                if (e.get("extended_props") or {}).get("comment")
            ),
        }
        detail = (
            f"merge OK: {merged_count} bloques en app_cache"
        )
        logger.info(
            f"[{self.nombre}] {self._ctx.plc_name}: {detail}"
        )
        return detail

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result``. Los SD quedan en
        ``layout.preview_dir`` para inspeccion post-mortem del
        operario hasta el siguiente ``prepare`` (el step de exportacion
        invoca ``clean_preview`` al inicio)."""
        merge_stats = self._stats.get("merge_cache", {})
        blocks_data = self._ctx.blocks_data if self._ctx is not None else []
        plc_name = self._ctx.plc_name if self._ctx is not None else ""
        self.result = {
            "ok": True,
            "plc_name": plc_name,
            "n_blocks": merge_stats.get("n_blocks", len(blocks_data)),
            "n_with_title": merge_stats.get("n_with_title", 0),
            "n_with_comment": merge_stats.get("n_with_comment", 0),
        }


@dataclass
class BlockEditPrepareContext:
    """Estado del run del FB de preparacion de bloques."""

    plc_name: str
    selected_block_paths: list[str]
    blocks_data: list[dict[str, Any]]


__all__ = ["BlockEditPrepareContext", "FunctionBlockEditPrepare"]
