"""FB de area: sincronizacion transaccional de entidades vs PLC.

State machine sobre el helper ``entidades_generate_preview``
(areas/alimentacion/helpers/entidades/entidades_generate_preview.py).
El helper expone funciones independientes (``compute_diff_entities``,
``compute_nmax_diff_entidades``, ``compute_comments_diff``,
``compute_unified_diff_entities``) que reciben un ``EntidadesSyncContext``
y mutan sus campos. **Aqui en el FB vive la state machine**: el orden de
las 11 llamadas, el mapping step -> funcion del helper, y la
instanciacion del ctx.

Mirror 1:1 del patron ``FunctionDispSincronizar`` (11 stages):
  - Tx A online puro para el NMAX update (redimensiona el array ENT[]).
  - Wait consolidacion 2s (TIA internaliza el redimensionado).
  - Re-exportar tras Tx A (el DB ya tiene el nuevo tamanyo).
  - Editar XMLs offline (constants + slot comments).
  - Tx B offline para constantes (import_plc_tags_xml).
  - Compilar bloques (DB6_ENT cambio de tamanyo).
  - Tx C offline para comentarios del array (commit_array_comments).
  - Preview post-sync (re-export + re-run preview).

SIN save_project (decision humana; la politica del repo es "Save manual
en TIA Portal tras sync"). Con save_required=False en el resultado
(1:1 con Disp; el operario ya sabe la politica).

Hereda directo de ``FunctionBase``. Zona 0 con 4 deps comunes + 1
especifica (``app_state``).

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy-compatible con Disp::

    {
      'success':            True,
      'message':            str,
      'operations':         int,
      'n_max_updates':      int,
      'post_sync_preview':  dict | None,
      'compile_ok':         bool,
      'compile_error':      str | None,
      'comments_sync':      dict,
    }

Steps (11):
  - exportar
  - compute_diff
  - preparar_ops
  - tx_a_nmax                (online puro)
  - wait_consolidation
  - exportar_post_tx_a
  - editar_xmls_offline
  - tx_b_constants           (offline puro)
  - compilar_bloques
  - tx_c_comments            (offline puro)
  - post_preview
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async
from core.helpers.tia.active_cache import get_entidades, get_nmax_entidades
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia
from core.helpers.tia.with_plc import with_plc
from core.runtime.app_state import AppState, get_app_state
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)


# Sleep para que TIA consolide el redimensionado del array ENT[] en
# DB6_ENT tras el NMAX update online (Tx A).
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


class FunctionEntidadesSincronizar(FunctionBase):
    """FB que sincroniza entidades contra TIA (11 etapas transaccionales)."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 3 transacciones TIA + compile + post preview.
    # TIA V21 puede tardar varios minutos para PLCs grandes con el
    # array ENT[] redimensionado. 600s cubre holgadamente.
    STEP_TIMEOUT_S: float = 600.0

    # Tabla declarativa de stages. Cada tupla: (idx, "nombre_step",
    # "atributo_metodo_en_el_FB"). El ``run_step`` dispatcha contra
    # esta tabla en vez de un ``match``/``case`` inline, para que el
    # flujo sea legible arriba de la clase y los tests puedan
    # mockear ``fb._stage_N_<nombre>`` directamente.
    STAGES: list[tuple[int, str, str]] = [
        (1,  "Exportar etiquetas y DB",                "_stage_1_exportar"),
        (2,  "Calcular diferencias",                   "_stage_2_compute_diff"),
        (3,  "Preparar operaciones",                   "_stage_3_preparar_ops"),
        (4,  "Aplicar NMAX online (Tx A)",             "_stage_4_tx_a_nmax"),
        (5,  "Esperar consolidacion TIA",              "_stage_5_wait_consolidation"),
        (6,  "Re-exportar etiquetas y DB",             "_stage_6_exportar_post_tx_a"),
        (7,  "Editar XMLs offline",                    "_stage_7_editar_xmls_offline"),
        (8,  "Aplicar constantes offline (Tx B)",      "_stage_8_tx_b_constants"),
        (9,  "Compilar bloques",                       "_stage_9_compilar_bloques"),
        (10, "Aplicar comentarios offline (Tx C)",     "_stage_10_tx_c_comments"),
        (11, "Generar preview post-sincronizacion",    "_stage_11_post_preview"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "entidades_sincronizar",
        titulo: str = "Sincronizar entidades contra PLC",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_state: AppState | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Exportar etiquetas y DB"},
                {"nombre": "Calcular diferencias"},
                {"nombre": "Preparar operaciones"},
                {"nombre": "Aplicar NMAX online (Tx A)"},
                {"nombre": "Esperar consolidacion TIA"},
                {"nombre": "Re-exportar etiquetas y DB"},
                {"nombre": "Editar XMLs offline"},
                {"nombre": "Aplicar constantes offline (Tx B)"},
                {"nombre": "Compilar bloques"},
                {"nombre": "Aplicar comentarios offline (Tx C)"},
                {"nombre": "Generar preview post-sincronizacion"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # Deps especificas.
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        # EntidadesSyncContext compartido entre los 11 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior.
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + crear ctx."""
        if self._config is None:
            raise RuntimeError(
                "FunctionEntidadesSincronizar requiere config_manager. "
                "Inyectalo en el constructor."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionEntidadesSincronizar requiere tia_client. "
                "Inyectalo en el constructor."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionEntidadesSincronizar.start(plc_name=...) es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Validar contra TIA Portal (fail-late).
        validate_plc_in_tia(self._tia_client, self._plc_name)
        # Validar contra el Excel cargado.
        validate_plc_in_excel(self._state, self._plc_name)
        # Propagar al AppState.
        with_plc(self._state, self._plc_name)

        # Crear el EntidadesSyncContext que las 11 funciones iran mutando.
        self._ctx = EntidadesSyncContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando sync transaccional de entidades "
            f"para {self._plc_name} (11 etapas)"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a su handler en este FB.

        Aqui vive la state machine: cada step llama a UN metodo del FB
        (``_stage_N_<nombre>``) contra el ``EntidadesSyncContext``
        compartido. El lookup es por ``nombre`` (no por ``idx``), mismo
        patron que ``FunctionDispSincronizar`` y ``FunctionEntidadesGenerarPreview``.
        """
        if self._ctx is None:
            raise RuntimeError(
                "EntidadesSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                await handler()
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionEntidadesSincronizar"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que espera la SPA.

        Shape legacy-compatible con Disp (mismas keys). Los stages 5+
        (compute post Tx A / Tx B / Tx C) mutan ``ctx.result``; si el FB
        fallo antes de llegar a on_finish, el helper dejara el result
        parcial con ``success=False``.
        """
        if self._ctx is None:
            self.result = _empty_result()
            return

        self.result = self._ctx.result

        operations = (
            len(self._ctx.constant_ops)
            + len(self._ctx.comment_ops)
            + (1 if self._ctx.nmax_op else 0)
        )
        self.result["operations"] = operations
        self.result["n_max_updates"] = 1 if self._ctx.nmax_op else 0
        logger.debug(
            f"[{self.nombre}] sync de entidades de "
            f"{self._ctx.plc_name} finalizado: "
            f"{operations} ops aplicadas, "
            f"{len(self._ctx.warnings)} warnings, "
            f"compile_ok={self._ctx.compile_ok}"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 11 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    async def _stage_1_exportar(self) -> None:
        """Stage 1: limpia ``sincronizar/`` y exporta las 2 tablas + el DB.

        Layout usado (.build_cache/alimentacion/entidades/sincronizar/):
          - variables/export/   (0_Config_Generales.xml + 6_Entidades.xml)
          - bloques/export/     (DB6_ENT.s7dcl + DB6_ENT.s7res)

        Politica ante fallos del worker TIA (mismo patron que
        entidades_generar_preview): si una tabla o el DB no existen en
        TIA, el FB NO aborta: marca el bloque como ``missing_xml`` y
        emite un warning. Los stages posteriores ven el bloque vacio y
        el sync queda como no-op para esa parte.
        """
        from areas.alimentacion.helpers.layout.build_cache import build_cache

        ent_ctx = build_cache(root=self._ctx.build_cache_root).entidades
        ent_ctx.clean_sincronizar()
        self._ctx.sync_variables_export = ent_ctx.sync_variables_export
        self._ctx.sync_variables_modified = ent_ctx.sync_variables_modified
        self._ctx.sync_bloques_export = ent_ctx.sync_bloques_export
        self._ctx.sync_bloques_modified = ent_ctx.sync_bloques_modified

        # 1/3: validar config_manager expone los getters del feature.
        entidades_cfg = self._ctx.config_manager.get_entidades_config()
        if not entidades_cfg:
            raise RuntimeError(
                "ConfigManager.get_entidades_config() devolvio {}. "
                "El config.json no define el bloque 'entidades'."
            )
        db_name = entidades_cfg.get("db_name", "DB6_ENT")
        db_array_name = entidades_cfg.get("db_array_name", "ENT")
        tag_table = entidades_cfg.get("tag_table", "6_Entidades")
        config_table = entidades_cfg.get("config_table", "0_Config_Generales")

        self._ctx.db_name = db_name
        self._ctx.db_array_name = db_array_name
        self._ctx.tag_table = tag_table
        self._ctx.config_table = config_table

        # 2/3: export_plc_tags_xml (2 tablas) en 1 dispatch FLAT.
        tags_result = await dispatch_async(
            self._ctx.tia_client,
            "export_plc_tags_xml",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.sync_variables_export),
                "table_names": [config_table, tag_table],
                "keep_folder_structure": False,
            },
        )
        if tags_result is None:
            warning = (
                f"export_plc_tags_xml fallo (Tia puede no tener "
                f"'{config_table}' o '{tag_table}' todavia). "
                f"Variables marcadas como missing_xml."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)
        else:
            self._ctx.tags_export = tags_result
            logger.debug(
                f"  {config_table} + {tag_table} exportadas a "
                f"{self._ctx.sync_variables_export}"
            )

        # 3/3: export_block (DB6_ENT) a sincronizar/bloques/export/.
        block_result = await dispatch_async(
            self._ctx.tia_client,
            "export_block",
            {
                "plc_name": self._ctx.plc_name,
                "block_name": db_name,
                "target_dir": str(self._ctx.sync_bloques_export),
            },
            timeout_s=60.0,
        )
        if block_result is None:
            warning = (
                f"export_block fallo: bloque '{db_name}' no encontrado "
                f"en PLC '{self._ctx.plc_name}'. "
                f"Bloques marcados como missing_xml."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)
        else:
            self._ctx.db_export = block_result
            logger.debug(
                f"  {db_name} exportado a {self._ctx.sync_bloques_export}"
            )

    async def _stage_2_compute_diff(self) -> None:
        """Stage 2: calcula el diff completo (NMAX + constantes + comments).

        Reutiliza los helpers ``compute_diff_entities``,
        ``compute_nmax_diff_entidades`` y ``compute_comments_diff`` del
        preview FB. Tambien computa ``compute_unified_diff_entities``
        para que stages 3+ (preparar_ops) tenga la lista consolidada
        con shape {plc_tag, numero_tia, comment_tia, numero_excel,
        comment_excel, status}.
        """
        assert self._ctx.sync_variables_export is not None
        assert self._ctx.sync_bloques_export is not None

        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_comments_diff,
            compute_diff_entities,
            compute_nmax_diff_entidades,
            compute_unified_diff_entities,
            DiffComments,
            DiffEntities,
        )

        desired = get_entidades(self._ctx.app_state, self._ctx.plc_name)
        variables_xml = self._ctx.sync_variables_export / f"{self._ctx.tag_table}.xml"
        config_xml = self._ctx.sync_variables_export / f"{self._ctx.config_table}.xml"

        def _compute_constants() -> Any:
            return compute_diff_entities(
                table_name=self._ctx.tag_table,
                desired_entities=desired,
                xml_path=variables_xml,
            )

        def _compute_nmax() -> Any:
            return compute_nmax_diff_entidades(
                table_name=self._ctx.config_table,
                desired_nmax=get_nmax_entidades(self._ctx.app_state),
                xml_path=config_xml,
            )

        diff_ent_dm, nmax_dm = await asyncio.gather(
            asyncio.to_thread(_compute_constants),
            asyncio.to_thread(_compute_nmax),
        )

        self._ctx.entities_block = {
            "base":         diff_ent_dm.base,
            "base_comments": diff_ent_dm.base_comments,
            "desired":      diff_ent_dm.desired,
            "added":        diff_ent_dm.added,
            "removed":      diff_ent_dm.removed,
            "renamed":      diff_ent_dm.renamed,
            "missing_xml":  diff_ent_dm.missing_xml,
        }
        self._ctx.nmax_block = {
            "current":     nmax_dm.current,
            "desired":     nmax_dm.desired,
            "todos":       nmax_dm.todos,
            "summary":     nmax_dm.summary,
            "nmax_error":  nmax_dm.nmax_error,
        }

        # Comments: lee .s7dcl/.s7res de sincronizar/bloques/export/.
        from core.infrastructure.tia.tia_export_paths import SdPair
        dcl_path = SdPair(self._ctx.sync_bloques_export, self._ctx.db_name).dcl
        res_path = SdPair(self._ctx.sync_bloques_export, self._ctx.db_name).res
        dcl_text = dcl_path.read_text(encoding="utf-8-sig") if dcl_path.exists() else ""
        res_text = res_path.read_text(encoding="utf-8-sig") if res_path.exists() else ""

        def _compute_comments() -> Any:
            return compute_comments_diff(
                db_name=self._ctx.db_name,
                array_name=self._ctx.db_array_name,
                desired_entities=desired,
                dcl_text=dcl_text,
                res_text=res_text,
            )

        diff_com = await asyncio.to_thread(_compute_comments)
        self._ctx.comments_block = {
            "slots_tia":   diff_com.slots_tia,
            "current":     diff_com.current,
            "desired":     diff_com.desired,
            "added":       diff_com.added,
            "removed":     diff_com.removed,
            "updated":     diff_com.updated,
            "unchanged":   diff_com.unchanged,
            "missing_xml": diff_com.missing_xml,
        }

        # Diff unificado (C.22) con shape simplificado (C.25: base_comments).
        # Stage 3 (preparar_ops) leera de ``unified_todos``.
        diff_ent_recon = DiffEntities(
            table_name=self._ctx.tag_table,
            base=self._ctx.entities_block["base"],
            desired=self._ctx.entities_block["desired"],
            added=self._ctx.entities_block["added"],
            removed=self._ctx.entities_block["removed"],
            renamed=self._ctx.entities_block["renamed"],
            base_comments=self._ctx.entities_block["base_comments"],
            missing_xml=self._ctx.entities_block["missing_xml"],
        )
        diff_com_recon = DiffComments(
            db_name=self._ctx.db_name,
            array_name=self._ctx.db_array_name,
            slots_tia=set(self._ctx.comments_block["slots_tia"]),
            current=self._ctx.comments_block["current"],
            desired=self._ctx.comments_block["desired"],
            added=self._ctx.comments_block["added"],
            removed=self._ctx.comments_block["removed"],
            updated=self._ctx.comments_block["updated"],
            unchanged=self._ctx.comments_block["unchanged"],
            missing_xml=self._ctx.comments_block["missing_xml"],
        )
        self._ctx.unified_todos = compute_unified_diff_entities(
            diff_ent_recon, diff_com_recon
        )


# ============================================================================
# Estado compartido entre los 11 stages
# ============================================================================


@dataclass
class EntidadesSyncContext:
    """Estado mutable compartido entre los 11 stages del FB.

    Cada stage toma este context por argumento (vía ``self._ctx``), lee
    las deps inyectadas + resultados de stages previos, y muta los
    campos que representan resultados de su trabajo.
    """

    # ── Deps inyectadas ──
    plc_name: str
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path

    # ── Estado del config ──
    db_name: str = "DB6_ENT"
    db_array_name: str = "ENT"
    tag_table: str = "6_Entidades"
    config_table: str = "0_Config_Generales"

    # ── Workdirs (sincronizar/) ──
    sync_variables_export: Path | None = None
    sync_variables_modified: Path | None = None
    sync_bloques_export: Path | None = None
    sync_bloques_modified: Path | None = None

    # ── Resultados de exportar (stage 1) ──
    tags_export: dict[str, Any] | None = None
    db_export: dict[str, Any] | None = None

    # ── Resultados de compute_diff (stage 2) ──
    entities_block: dict[str, Any] = field(default_factory=dict)
    comments_block: dict[str, Any] = field(default_factory=dict)
    nmax_block: dict[str, Any] = field(default_factory=dict)
    unified_todos: list[dict[str, Any]] = field(default_factory=list)

    # ── Resultados de preparar_ops (stage 3, D.2) ──
    nmax_op: dict[str, Any] | None = None
    constant_ops: list[dict[str, Any]] = field(default_factory=list)
    comment_ops: list[dict[str, Any]] = field(default_factory=list)

    # ── Resultados de Tx A / B / C (stages 4/8/10) ──
    nmax_result: dict[str, Any] | None = None
    devices_result: dict[str, Any] | None = None
    comments_result: dict[str, Any] | None = None

    # ── Compile (stage 9) ──
    compile_ok: bool = True
    compile_error: str | None = None

    # ── Post preview (stage 11) ──
    post_sync_preview: dict[str, Any] | None = None

    # ── Warnings acumulados ──
    warnings: list[str] = field(default_factory=list)

    # ── Resultado final (poblado progresivamente) ──
    result: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Helpers internos privados al modulo
# ============================================================================


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "Exportar etiquetas y DB":
        n_warn = len(ctx.warnings)
        return (
            f"{step_nombre}: 2 tablas + DB6_ENT exportados "
            f"({n_warn} warnings)"
        )
    if step_nombre == "Calcular diferencias":
        adds = len(ctx.entities_block.get("added", []))
        rems = len(ctx.entities_block.get("removed", []))
        renames = len(ctx.entities_block.get("renamed", {}))
        c_adds = len(ctx.comments_block.get("added", []))
        c_updates = len(ctx.comments_block.get("updated", []))
        nmax_update = ctx.nmax_block.get("summary", {}).get("actualizar", 0)
        return (
            f"{step_nombre}: {adds} const adds, {rems} const removes, "
            f"{renames} renames; {c_adds} comments adds, "
            f"{c_updates} comments updates; NMAX={nmax_update}"
        )
    return f"{step_nombre}: OK"


def _empty_result() -> dict[str, Any]:
    """Shape legacy-compatible con Disp para cuando el FB falla temprano."""
    return {
        "success":            False,
        "message":            "FB no ejecutado (on_start fallo)",
        "operations":         0,
        "n_max_updates":      0,
        "post_sync_preview":  None,
        "compile_ok":         False,
        "compile_error":      "FB no ejecutado",
        "comments_sync":      {"added": 0, "updated": 0, "unchanged": 0},
    }


# Stage 5/6/7/8/9/10/11 declarados como stubs vacios; se implementan
# en commits D.2-D.6. Mantenerlos aqui (no-op) para que la tabla
# ``STAGES`` se valide al instanciar el FB.
async def _stage_3_preparar_ops(self: Any) -> None:  # noqa: D401
    """Stage 3: implementar en D.2."""
    raise NotImplementedError("Stage 3 implementado en D.2")


async def _stage_4_tx_a_nmax(self: Any) -> None:  # noqa: D401
    """Stage 4: implementar en D.2."""
    raise NotImplementedError("Stage 4 implementado en D.2")


async def _stage_5_wait_consolidation(self: Any) -> None:  # noqa: D401
    """Stage 5: implementar en D.3."""
    raise NotImplementedError("Stage 5 implementado en D.3")


async def _stage_6_exportar_post_tx_a(self: Any) -> None:  # noqa: D401
    """Stage 6: implementar en D.3."""
    raise NotImplementedError("Stage 6 implementado en D.3")


async def _stage_7_editar_xmls_offline(self: Any) -> None:  # noqa: D401
    """Stage 7: implementar en D.4."""
    raise NotImplementedError("Stage 7 implementado en D.4")


async def _stage_8_tx_b_constants(self: Any) -> None:  # noqa: D401
    """Stage 8: implementar en D.5."""
    raise NotImplementedError("Stage 8 implementado en D.5")


async def _stage_9_compilar_bloques(self: Any) -> None:  # noqa: D401
    """Stage 9: implementar en D.5."""
    raise NotImplementedError("Stage 9 implementado en D.5")


async def _stage_10_tx_c_comments(self: Any) -> None:  # noqa: D401
    """Stage 10: implementar en D.6."""
    raise NotImplementedError("Stage 10 implementado en D.6")


async def _stage_11_post_preview(self: Any) -> None:  # noqa: D401
    """Stage 11: implementar en D.6."""
    raise NotImplementedError("Stage 11 implementado en D.6")


# Inyectar los stubs como metodos del FB (para que el STAGES dispatch los
# encuentre). Se sobreescribiran en commits D.2-D.6.
FunctionEntidadesSincronizar._stage_3_preparar_ops = _stage_3_preparar_ops  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_4_tx_a_nmax = _stage_4_tx_a_nmax  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_5_wait_consolidation = _stage_5_wait_consolidation  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_6_exportar_post_tx_a = _stage_6_exportar_post_tx_a  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_7_editar_xmls_offline = _stage_7_editar_xmls_offline  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_8_tx_b_constants = _stage_8_tx_b_constants  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_9_compilar_bloques = _stage_9_compilar_bloques  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_10_tx_c_comments = _stage_10_tx_c_comments  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_11_post_preview = _stage_11_post_preview  # type: ignore[attr-defined]


__all__ = [
    "FunctionEntidadesSincronizar",
    "EntidadesSyncContext",
    "TIA_CONSOLIDATION_SLEEP_S",
]