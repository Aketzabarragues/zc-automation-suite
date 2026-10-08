"""FB de area: sincronizacion transaccional de entidades vs PLC.

State machine sobre el helper ``entidades_generate_preview``
(areas/alimentacion/helpers/entidades/entidades_generate_preview.py).
El helper expone funciones independientes (``compute_diff_entities``,
``compute_nmax_diff_entidades``, ``compute_comments_diff``) que reciben
un ``EntidadesSyncContext`` y mutan sus campos. **Aqui en el FB vive
la state machine**: el orden de las 11 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Replica el patron de ``FunctionDispSincronizar`` (11 stages):
  - Tx A online puro para el NMAX update (redimensiona el array ENT[]).
  - Wait consolidacion 2s (TIA internaliza el redimensionado).
  - Re-exportar tras Tx A (el DB ya tiene el nuevo tamanyo).
  - Editar XMLs offline (constants + slot comments).
  - Tx B offline para constantes (import_plc_tags_xml).
  - Compilar bloques (DB6_ENT cambio de tamanyo).
  - Tx C offline para comentarios del array (commit_array_comments).
  - Preview post-sync (re-export + re-run preview).

Sin ``save_project``: politica del repo, el operario hace Save manual
en TIA Portal tras validar el sync. ``save_required=False`` en el
resultado (1:1 con Disp; el operario ya sabe la politica).

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

        # 2/3: export_plc_tags_xml (2 tablas) con subcarpeta TIA.
        # keep_folder_structure=True (mirror Disp): TIA V21 hace
        # match UPDATE recursivo por subpath TIA en el import. Sin
        # la subcarpeta, el archivo queda FLAT y TIA no encuentra
        # la ruta esperada al re-importar.
        tags_result = await dispatch_async(
            self._ctx.tia_client,
            "export_plc_tags_xml",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.sync_variables_export),
                "table_names": [config_table, tag_table],
                "keep_folder_structure": True,
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
            logger.debug(
                f"  {config_table} + {tag_table} exportadas a "
                f"{self._ctx.sync_variables_export}"
            )

        # 3/3: export_block (DB6_ENT) preservando estructura TIA.
        # keep_folder_structure=True (mirror Disp): sin esto,
        # import_block en Tx C falla con "Import failed because an
        # object with the name 'DB6_ENT' already exists" porque TIA
        # no puede determinar la subcarpeta destino del UPDATE.
        block_result = await dispatch_async(
            self._ctx.tia_client,
            "export_block",
            {
                "plc_name": self._ctx.plc_name,
                "block_name": db_name,
                "target_dir": str(self._ctx.sync_bloques_export),
                "keep_folder_structure": True,
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
            logger.debug(
                f"  {db_name} exportado a {self._ctx.sync_bloques_export}"
            )

    async def _stage_2_compute_diff(self) -> None:
        """Stage 2: calcula el diff completo (NMAX + constantes + comments).

        Reutiliza los helpers ``compute_diff_entities`` (devuelve
        ``ops: list[dict]`` en orden de aplicacion),
        ``compute_nmax_diff_entidades`` y ``compute_comments_diff`` del
        preview FB. Stage 3 (preparar_ops) dispatcha las ops por kind.
        """
        assert self._ctx.sync_variables_export is not None
        assert self._ctx.sync_bloques_export is not None

        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_comments_diff,
            compute_diff_entities,
            compute_nmax_diff_entidades,
        )

        desired = get_entidades(self._ctx.app_state, self._ctx.plc_name)
        # Stage 1 exporta con keep_folder_structure=True, asi que
        # los XML viven en subcarpeta TIA dentro de export/.
        tia_folder_tags = (
            self._ctx.config_manager.get_tia_folder_entidades_tags()
        )
        tia_folder_config = (
            self._ctx.config_manager.get_tia_folder_entidades_config()
        )
        variables_xml = (
            self._ctx.sync_variables_export
            / tia_folder_tags
            / f"{self._ctx.tag_table}.xml"
        )
        config_xml = (
            self._ctx.sync_variables_export
            / tia_folder_config
            / f"{self._ctx.config_table}.xml"
        )

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
        # Lista unica de ops a aplicar por el sync (orden de aplicacion).
        # Stage 3 dispatcha por kind.
        self._ctx.entities_ops = list(diff_ent_dm.ops)
        # Entities del Excel (para generar comment_ops del slot del DB
        # en stage 3 bucle 3/3: SIEMPRE actualizar, no diff).
        self._ctx.desired_entities = list(desired)
        self._ctx.nmax_block = {
            "current":     nmax_dm.current,
            "desired":     nmax_dm.desired,
            "todos":       nmax_dm.todos,
            "summary":     nmax_dm.summary,
            "missing_xml": nmax_dm.missing_xml,
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

    async def _stage_3_preparar_ops(self) -> None:
        """Stage 3: walk ``entities_ops`` y agrupa ops para Tx A / B / C.

        Output (mutaciones de ``self._ctx``):
          - ``nmax_op``: dict o None con la op del NMAX_ENTIDAD (si cambia)
            -> ira a Tx A (stage 4, online puro).
          - ``constant_ops``: lista de dicts con ops de PlcUserConstants
            (add/remove/rename) -> iran a Tx B (stage 8, offline puro,
            via ``import_plc_tags_xml`` del XML FLAT modificado en stage 7).
          - ``comment_ops``: lista de dicts con ops de slot comments
            (add/update) -> iran a Tx C (stage 10, offline puro,
            via ``commit_array_comments``).

        El caso "mismo plc_tag + distinto value" del diff unificado
        produce 2 filas separadas (eliminar PLC + agregar Excel). Aqui
        se traducen a 2 ops: un remove + un add, en ese orden (el remove
        se ejecuta primero para evitar colision de plc_tags en el XML).

        Sin ``save_project`` (politica del repo): el FB deja los cambios
        en memoria de TIA Portal; el operario pulsa Save manual.
        """
        has_comment_op = any(
            getattr(e, "plc_comentario", "") for e in self._ctx.desired_entities
        )
        if (
            not self._ctx.entities_ops
            and not self._ctx.nmax_block.get("todos")
            and not has_comment_op
        ):
            # Sin ops de entities, NMAX update ni comment ops: stage no-op.
            return

        # ── 1/3 NMAX op ──
        # El NMAX_ENTIDAD solo cambia si hay 1+ entradas en
        # ``nmax_block.todos`` con status="actualizar".
        for entry in self._ctx.nmax_block.get("todos", []):
            if entry.get("status") == "actualizar":
                self._ctx.nmax_op = {
                    "command": "update_user_constant_value",
                    "args": {
                        "plc_name":   self._ctx.plc_name,
                        "table_name": self._ctx.config_table,
                        "constant_name": entry["name"],
                        "new_value":  int(entry["nuevo"]),
                    },
                }
                break

        # ── 2/3 Constant ops (per-constant) ──
        # Itera ``entities_ops`` (lista unica de ops) y traduce a
        # ``constant_ops`` con el shape que espera el stage 7 (el
        # ``PlcUserConstantModifier`` offline) y el TX B (import XML).
        for op in self._ctx.entities_ops:
            kind = op.get("kind")
            if kind == "delete":
                self._ctx.constant_ops.append({
                    "kind":     "remove",
                    "plc_tag": op["plc_tag"],
                })
            elif kind == "add":
                self._ctx.constant_ops.append({
                    "kind":     "add",
                    "plc_tag": op["plc_tag"],
                    "uid":      op["value_excel"],
                    "comment":  op.get("comment_excel") or "",
                })
            elif kind == "rename":
                # TIA conserva el value, cambia el ``Name`` al plc_tag
                # del Excel. Stage 7 hace un remove + add con el
                # mismo value (es la unica forma de "renombrar" una
                # PlcUserConstant: delete la vieja, add la nueva con
                # el mismo value).
                self._ctx.constant_ops.append({
                    "kind":     "remove",
                    "plc_tag": op["plc_tag_tia"],
                })
                self._ctx.constant_ops.append({
                    "kind":     "add",
                    "plc_tag": op["plc_tag_new"],
                    "uid":      op["value_tia"],
                    "comment":  "",
                })
            elif kind == "update_comment":
                self._ctx.constant_ops.append({
                    "kind":        "rename_comment",
                    "plc_tag":     op["plc_tag"],
                    "new_comment": op.get("comment_excel") or "",
                })
            elif kind == "sin_cambios":
                # D.8.12: op informativa (la SPA pinta ✓ OK). El sync
                # FB no toca TIA: la constant ya esta en sync.
                pass
            # delete/add/rename/update_comment/sin_cambios cubiertos.

        # ── 3/3 Comment ops (slot del array ENT[]) ──
        # SIEMPRE actualizar con el comment del Excel (politica
        # Aketza: Excel manda). Para cada entity del Excel con
        # comment no vacio, 1 op update_comment con slot=numero
        # y new_comment=plc_comentario.
        for entidad in self._ctx.desired_entities:
            slot = getattr(entidad, "numero", None)
            comment = getattr(entidad, "plc_comentario", "") or ""
            if not comment:
                continue
            if slot is None:
                continue
            self._ctx.comment_ops.append({
                "kind":        "update_comment",
                "slot":        int(slot),
                "new_comment": comment,
            })

    async def _stage_4_tx_a_nmax(self) -> None:
        """Stage 4: Tx A online puro para el NMAX update.

        Cambia el value de la PlcUserConstant ``N_MAX_ENTIDAD`` en
        ``0_Config_Generales`` (e.g. 4 -> 15). Esto redimensiona el
        array ``ENT[]`` del ``DB6_ENT`` en la sesion de TIA Portal.
        Stage 5 espera la consolidacion interna y stage 6 re-exporta
        para que Tx B opere con la estructura ya actualizada.

        Wrap en ``execute_transactional_batch`` para atomicidad. Si
        falla, TIA hace rollback del NMAX update.

        Tras el commit se dispara un ``compile_blocks`` defensivo sobre
        el DB para forzar a TIA a regenerar la estructura del array
        redimensionado. Si falla, log warning y sigue: stage 9 compila
        de nuevo tras Tx C.

        Sin ``save_project``: los cambios quedan en memoria de TIA
        Portal. El operario pulsa Save manual tras validar el resultado.

        Stage no-op si no hay NMAX op.
        """
        if not self._ctx.nmax_op:
            return

        logger.debug(
            f"[{self.nombre}] Tx A online: {self._ctx.nmax_op}"
        )

        result = await dispatch_async(
            self._ctx.tia_client,
            "execute_transactional_batch",
            {
                "undo_text": "Actualizando N_MAX_ENTIDAD (redimensiona array ENT[])...",
                "operations": [self._ctx.nmax_op],
            },
            timeout_s=60.0,
        )

        if result is None:
            raise RuntimeError(
                "Tx A (NMAX update) fallo: el worker TIA no devolvio "
                "resultado. TIA Portal puede no estar conectado o el "
                "PLC no tiene la tabla de configuracion."
            )
        self._ctx.nmax_result = result

        # Compile defensivo post-Tx-A. Si TIA rechaza o retorna None,
        # log warning y sigue: stage 9 compila de nuevo tras Tx C.
        try:
            compile_result = await dispatch_async(
                self._ctx.tia_client,
                "compile_blocks",
                {
                    "plc_name":   self._ctx.plc_name,
                    "block_names": [self._ctx.db_name],
                },
                timeout_s=120.0,
            )
            if compile_result is None:
                logger.warning(
                    f"[{self.nombre}] compile defensivo post-Tx-A no "
                    f"devolvio resultado. Stage 9 compila de nuevo."
                )
            else:
                logger.debug(
                    f"[{self.nombre}] compile defensivo post-Tx-A OK"
                )
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] compile defensivo post-Tx-A fallo: {exc}. "
                f"Stage 9 compila de nuevo."
            )

    async def _stage_5_wait_consolidation(self) -> None:
        """Stage 5: sleep para que TIA consolide el NMAX update de Tx A.

        Constante ``TIA_CONSOLIDATION_SLEEP_S = 2.0s`` (mismo patron que
        FunctionDispSincronizar). Tras el ``update_user_constant_value``
        online (Tx A), TIA necesita tiempo para redimensionar el array
        ENT[] en DB6_ENT internamente. Sin el sleep, stage 6 re-exportaria
        con el tamanyo antiguo.

        Si no hubo NMAX op (no hay cambios), el stage es no-op.
        """
        if not self._ctx.nmax_op:
            return
        logger.debug(
            f"[{self.nombre}] Esperando consolidacion TIA tras Tx A "
            f"({TIA_CONSOLIDATION_SLEEP_S}s)..."
        )
        await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)

    async def _stage_6_exportar_post_tx_a(self) -> None:
        """Stage 6: re-export FLAT tras Tx A (DB6_ENT con tamanyo actualizado).

        Mismo patron que stage 1 pero llamado despues de Tx A + wait.
        Sobrescribe los archivos en ``sync_variables_export/`` y
        ``sync_bloques_export/`` con el estado actual del PLC tras el
        NMAX update.

        Si Tx A fue no-op (no hubo NMAX op), el stage es no-op.
        """
        if not self._ctx.nmax_op:
            return

        logger.debug(
            f"[{self.nombre}] Re-exportando tras Tx A NMAX..."
        )

        tags_result = await dispatch_async(
            self._ctx.tia_client,
            "export_plc_tags_xml",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.sync_variables_export),
                "table_names": [self._ctx.config_table, self._ctx.tag_table],
                "keep_folder_structure": True,
            },
        )
        if tags_result is None:
            warning = (
                f"Re-export post Tx A fallo (export_plc_tags_xml). "
                f"Sync continuara con snapshot pre-Tx-A."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)
            return

        block_result = await dispatch_async(
            self._ctx.tia_client,
            "export_block",
            {
                "plc_name": self._ctx.plc_name,
                "block_name": self._ctx.db_name,
                "target_dir": str(self._ctx.sync_bloques_export),
                "keep_folder_structure": True,
            },
            timeout_s=60.0,
        )
        if block_result is None:
            warning = (
                f"Re-export post Tx A fallo (export_block {self._ctx.db_name})."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)


    async def _stage_7_editar_xmls_offline(self) -> None:
        """Stage 7: edita XMLs offline (constants + slot comments).

        Pre-condiciones: stage 1 exporto a ``sync_variables_export/`` y
        ``sync_bloques_export/``. Stage 6 (si Tx A tuvo NMAX) los re-exporto
        con el tamanyo actualizado. Aqui:

          1. ``copytree`` filtrado ``sync_variables_export/`` ->
            ``sync_variables_modified/``. Excluimos ``0_Config_Generales.xml``
            (la tabla NMAX) porque el NMAX ya se aplico online en Tx A;
            Tx B re-importaria los valores pre-commit y anularia Tx A.

          2. Edicion offline de ``6_Entidades.xml`` en ``modified/`` con
            las ``constant_ops`` de stage 3 (remove/add/rename_comment).

          3. ``copytree`` simple ``sync_bloques_export/`` ->
            ``sync_bloques_modified/`` (DBs FLAT).

          4. ``commit_array_comments`` sobre
            ``sync_bloques_modified/DB6_ENT.{s7dcl,s7res}`` con las
            ``comment_ops`` de stage 3 (update_comment por slot).

        Si no hay constant_ops ni comment_ops, los pasos 1-2 y 4 son
        no-ops (no editamos nada en ``modified/``).
        """
        import shutil
        from core.helpers.simatic_ml import PlcUserConstantModifier
        from core.helpers.simatic_sd.simatic_sd_db_array_comment_updater import (
            commit_array_comments,
        )

        src_vars = self._ctx.sync_variables_export
        dst_vars = self._ctx.sync_variables_modified
        src_bloq = self._ctx.sync_bloques_export
        dst_bloq = self._ctx.sync_bloques_modified

        # ── 1/4: copytree filtrado variables ──
        if src_vars and src_vars.exists():
            # Filtro: excluye 0_Config_Generales.xml (NMAX online-only).
            def _ignore(src: str, names: list[str]) -> list[str]:
                return [
                    n for n in names
                    if n == f"{self._ctx.config_table}.xml"
                ]

            dst_vars.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_vars, dst_vars, ignore=_ignore, dirs_exist_ok=True)
            logger.debug(
                f"[{self.nombre}] copytree {src_vars} -> {dst_vars} "
                f"(filtrado: {self._ctx.config_table}.xml excluido)"
            )
        else:
            logger.warning(
                f"[{self.nombre}] origen variables no existe: {src_vars}."
            )

        # ── 2/4: edit offline de 6_Entidades.xml ──
        # El XML vive en la subcarpeta TIA (mirror Disp). El copytree
        # de 1/4 preserva la estructura export/ → modified/.
        if self._ctx.constant_ops and dst_vars:
            tia_folder_tags = (
                self._ctx.config_manager.get_tia_folder_entidades_tags()
            )
            xml_path = dst_vars / tia_folder_tags / f"{self._ctx.tag_table}.xml"
            if xml_path.is_file():
                modifier = PlcUserConstantModifier(xml_path)
                adds = [
                    {"plc_tag": op["plc_tag"], "uid": op["uid"], "comment": op.get("comment", "")}
                    for op in self._ctx.constant_ops if op["kind"] == "add"
                ]
                removes = {
                    op["plc_tag"] for op in self._ctx.constant_ops if op["kind"] == "remove"
                }
                renames = [
                    (op["plc_tag"], op["new_comment"])
                    for op in self._ctx.constant_ops if op["kind"] == "rename_comment"
                ]

                if adds:
                    modifier.add_user_constants_by_table(
                        self._ctx.tag_table,
                        [{"plc_tag": a["plc_tag"], "uid": str(a["uid"]), "comment": a["comment"]}
                         for a in adds],
                    )
                if removes:
                    modifier.remove_user_constants_by_name(removes)
                for plc_tag, new_comment in renames:
                    modifier.update_user_constant_comment(plc_tag, new_comment)

                if modifier.was_modified():
                    modifier.save(xml_path)
                    logger.debug(
                        f"[{self.nombre}] edit offline {xml_path}: "
                        f"{len(adds)} adds, {len(removes)} removes, "
                        f"{len(renames)} renames"
                    )
            else:
                warning = (
                    f"XML '{xml_path.name}' no esta en {dst_vars}. "
                    f"Const ops omitidas del sync."
                )
                logger.warning(warning)
                self._ctx.warnings.append(warning)

        # ── 3/4: copytree simple bloques ──
        if src_bloq and src_bloq.exists():
            dst_bloq.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_bloq, dst_bloq, dirs_exist_ok=True)
            logger.debug(
                f"[{self.nombre}] copytree {src_bloq} -> {dst_bloq}"
            )
        else:
            logger.warning(
                f"[{self.nombre}] origen bloques no existe: {src_bloq}."
            )

        # ── 4/4: edit offline de DB6_ENT.{s7dcl,s7res} ──
        # Stage 1 exporta el bloque con keep_folder_structure=True,
        # asi que el archivo esta en
        # ``<dst_bloq>/<tia_folder>/DB6_ENT.s7dcl`` (no FLAT). El
        # SdPair debe construirse con la subcarpeta TIA, igual que
        # Disp hace con ``Path(modified_bloques) / target_folder``.
        if self._ctx.comment_ops and dst_bloq:
            from core.infrastructure.tia.tia_export_paths import SdPair
            tia_folder_bloques = (
                self._ctx.config_manager.get_tia_folder_entidades_tags()
            )
            sdpair = SdPair(
                dst_bloq / tia_folder_bloques, self._ctx.db_name,
            )
            slot_map = {
                op["slot"]: op["new_comment"]
                for op in self._ctx.comment_ops
                if op["kind"] == "update_comment"
            }
            if slot_map and sdpair.dcl.exists() and sdpair.res.exists():
                commit_array_comments(
                    dcl_path=sdpair.dcl,
                    res_path=sdpair.res,
                    array_name=self._ctx.db_array_name,
                    slot_map=slot_map,
                    array_type="UDT",
                    write_to_original=True,
                )
                logger.debug(
                    f"[{self.nombre}] edit offline {self._ctx.db_name}: "
                    f"{len(slot_map)} slot comments actualizados"
                )


    async def _stage_8_tx_b_constants(self) -> None:
            """Stage 8: Tx B (offline puro) - importa constantes modificadas.

            ``import_plc_tags_xml`` con el ``sync_variables_modified/`` que
            stage 7 produjo. Solo se importa ``6_Entidades.xml`` (NMAX ya
            se aplico online en Tx A — excluido del copytree en stage 7).

            Wrap en ``execute_transactional_batch`` para atomicidad
            semantica. Si falla, TIA hace rollback.

            Si no hay constant_ops (no hay adds/removes/renames), el stage
            es no-op.
            """
            if not self._ctx.constant_ops:
                return

            from core.helpers.tia import validate_execute_batch_result

            modified_dir = self._ctx.sync_variables_modified
            if not modified_dir or not modified_dir.is_dir():
                warning = (
                    f"sync_variables_modified/ no existe ({modified_dir}). "
                    f"Tx B omitida."
                )
                logger.warning(warning)
                self._ctx.warnings.append(warning)
                return

            logger.debug(
                f"[{self.nombre}] Tx B constants: import {self._ctx.tag_table}.xml "
                f"desde {modified_dir}"
            )

            batch_result = await dispatch_async(
                self._ctx.tia_client,
                "execute_transactional_batch",
                {
                    "undo_text": "Sincronizando constantes de entidades...",
                    "operations": [
                        {
                            "command": "import_plc_tags_xml",
                            # target_folder="" (string vacio) activa la
                            # rama default del handler que omite el
                            # argumento en TIA y mantiene match UPDATE
                            # recursivo por subpath.
                            "args": {
                                "plc_name":      self._ctx.plc_name,
                                "import_dir":    str(modified_dir),
                                "target_folder": "",
                            },
                        }
                    ],
                },
                timeout_s=300.0,
            )
            validate_execute_batch_result(
                batch_result,
                undo_text=f"Tx B constantes ({self._ctx.tag_table})",
            )

    async def _stage_9_compilar_bloques(self) -> None:
        """Stage 9: compila DB6_ENT para consolidar cambios estructurales.

        Compila tras Tx B (constants importadas) y antes de Tx C
        (import del DB modificado). Necesario cuando:
          - Tx A redimensiona el array ``ENT[]`` (NMAX cambio), o
          - hay ``comment_ops`` que Tx C va a importar al DB.
        Sin recompilar entre Tx B y Tx C, TIA puede tener la tabla
        de constantes y el DB con estructuras inconsistentes.

        Stage no-op si no hay NMAX op ni comment ops (solo cambian
        PlcUserConstants del tag table, sin tocar el DB).

        Wrap en try/except: si TIA rechaza el compile, marcamos
        ``compile_ok=False`` pero NO raise. El sync sigue y el FB
        reporta el error al operario via ``compile_error``.
        """
        if not self._ctx.nmax_op and not self._ctx.comment_ops:
            return

        try:
            compile_result = await dispatch_async(
                self._ctx.tia_client,
                "compile_blocks",
                {
                    "plc_name": self._ctx.plc_name,
                    "block_names": [self._ctx.db_name],
                },
                timeout_s=300.0,
            )
            if compile_result is None:
                self._ctx.compile_ok = False
                self._ctx.compile_error = (
                    f"compile_blocks retorno None para {self._ctx.db_name}"
                )
                logger.warning(
                    f"[{self.nombre}] compile_blocks no devolvio "
                    f"resultado. Sync continuara."
                )
            else:
                self._ctx.compile_ok = compile_result.get("success", True)
                if not self._ctx.compile_ok:
                    self._ctx.compile_error = compile_result.get(
                        "error", "compile_blocks reporto fallo"
                    )
                    logger.warning(
                        f"[{self.nombre}] compile fallo: {self._ctx.compile_error}"
                    )
        except Exception as exc:
            self._ctx.compile_ok = False
            self._ctx.compile_error = str(exc)
            logger.warning(
                f"[{self.nombre}] compile exception: {exc}. "
                f"Sync continuara sin abortar."
            )


# ============================================================================
# Estado compartido entre los 11 stages
# ============================================================================


@dataclass
class EntidadesSyncContext:
    """Estado mutable compartido entre los 11 stages del FB.

    Cada stage toma este context por argumento (via ``self._ctx``), lee
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

    # ── Resultados de compute_diff (stage 2) ──
    entities_block: dict[str, Any] = field(default_factory=dict)
    comments_block: dict[str, Any] = field(default_factory=dict)
    nmax_block: dict[str, Any] = field(default_factory=dict)
    # Lista unica de ops a aplicar por el sync. Stage 3 dispatcha por kind.
    entities_ops: list[dict[str, Any]] = field(default_factory=list)
    # Entities del Excel (para generar comment_ops del slot del DB:
    # SIEMPRE actualizar, sin diff).
    desired_entities: list[Any] = field(default_factory=list)

    # ── Resultados de Tx A (stage 4) ──
    nmax_result: dict[str, Any] | None = None

    # ── Resultados de preparar_ops (stage 3) ──
    nmax_op: dict[str, Any] | None = None
    constant_ops: list[dict[str, Any]] = field(default_factory=list)
    comment_ops: list[dict[str, Any]] = field(default_factory=list)

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
    if step_nombre == "Preparar operaciones":
        n_const = len(ctx.constant_ops)
        n_com = len(ctx.comment_ops)
        n_nmax = 1 if ctx.nmax_op else 0
        return (
            f"{step_nombre}: {n_const} const ops + "
            f"{n_com} comment ops + {n_nmax} NMAX op"
        )
    if step_nombre == "Aplicar NMAX online (Tx A)":
        if ctx.nmax_op:
            return (
                f"{step_nombre}: {ctx.nmax_op['args']['constant_name']} "
                f"value -> {ctx.nmax_op['args']['new_value']}"
            )
        return f"{step_nombre}: sin cambios"
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


async def _stage_10_tx_c_comments(self) -> None:
    """Stage 10: Tx C (offline puro) - importa DB6_ENT modificado.

    ``import_block`` con el ``sync_bloques_modified/`` que stage 7 produjo
    (ya tiene los slot comments aplicados via ``commit_array_comments``).

    Wrap en ``execute_transactional_batch`` para atomicidad semantica.
    Si falla, TIA hace rollback del import.

    Si no hay comment_ops (no hay updates de slot comments), el stage
    es no-op.
    """
    if not self._ctx.comment_ops:
        return

    from core.helpers.tia import validate_execute_batch_result

    modified_dir = self._ctx.sync_bloques_modified
    if not modified_dir or not modified_dir.is_dir():
        warning = (
            f"sync_bloques_modified/ no existe ({modified_dir}). "
            f"Tx C omitida."
        )
        logger.warning(warning)
        self._ctx.warnings.append(warning)
        return

    logger.debug(
        f"[{self.nombre}] Tx C comments: import {self._ctx.db_name} "
        f"desde {modified_dir}"
    )

    batch_result = await dispatch_async(
        self._ctx.tia_client,
        "execute_transactional_batch",
        {
            "undo_text": "Sincronizando comentarios del array ENT[]...",
            "operations": [
                {
                    "command": "import_block",
                    "args": {
                        "plc_name": self._ctx.plc_name,
                        "import_dir": str(modified_dir),
                        "target_folder": "",  # TIA escanea recursivo
                    },
                }
            ],
        },
        timeout_s=600.0,
    )
    validate_execute_batch_result(
        batch_result,
        undo_text=f"Tx C comentarios ({self._ctx.db_name})",
    )

    # Resumen legacy-compatible con Disp.
    if self._ctx.result is None or not isinstance(self._ctx.result, dict):
        self._ctx.result = _empty_result()
    self._ctx.result["comments_sync"] = {
        "added":   sum(1 for op in self._ctx.comment_ops if op["kind"] == "update_comment"),
        "updated": 0,
        "unchanged": 0,
    }

async def _stage_11_post_preview(self) -> None:
    """Stage 11: genera preview post-sync (la SPA ve 'todo en sync').

    Re-exporta FLAT (N_MAX + entidades + DB6_ENT) tras Tx A/B/C, recalcula
    el diff unificado y compone ``post_sync_preview`` con la misma shape
    que el preview FB. Asi, la SPA muestra "0 entidades analizadas" o
    solo los warnings de inconsistencias restantes.

    Si el re-export falla (TIA en estado invalido tras rollback), emite
    warning pero NO aborta (post_sync_preview=None).
    """
    from areas.alimentacion.helpers.layout.build_cache import build_cache

    ent_ctx = build_cache(root=self._ctx.build_cache_root).entidades
    ent_ctx.clean_preview()

    tags_result = await dispatch_async(
        self._ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": self._ctx.plc_name,
            "target_dir": str(ent_ctx.preview_disp),
            "table_names": [self._ctx.config_table, self._ctx.tag_table],
            # FLAT: el preview FB parsea ``<preview_disp>/6_Entidades.xml``
            # y ``<preview_disp>/0_Config_Generales.xml`` en el root
            # (no espera subcarpeta TIA).
            "keep_folder_structure": False,
        },
    )
    block_result = await dispatch_async(
        self._ctx.tia_client,
        "export_block",
        {
            "plc_name": self._ctx.plc_name,
            "block_name": self._ctx.db_name,
            "target_dir": str(ent_ctx.preview_bloques),
            "keep_folder_structure": True,
        },
        timeout_s=60.0,
    )
    if tags_result is None or block_result is None:
        warning = (
            "Re-export post-sync fallo. post_sync_preview sera None."
        )
        logger.warning(warning)
        self._ctx.warnings.append(warning)
        self._ctx.post_sync_preview = None
        return

    # Reusa el helper puro del preview FB para componer el shape.
    from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
        compute_comments_diff,
        compute_diff_entities,
        compute_nmax_diff_entidades,
        DiffComments,
        DiffEntities,
    )

    desired = get_entidades(self._ctx.app_state, self._ctx.plc_name)
    variables_xml = ent_ctx.preview_disp / f"{self._ctx.tag_table}.xml"
    config_xml = ent_ctx.preview_disp / f"{self._ctx.config_table}.xml"
    from core.infrastructure.tia.tia_export_paths import SdPair
    sdpair = SdPair(ent_ctx.preview_bloques, self._ctx.db_name)
    dcl_text = sdpair.dcl.read_text(encoding="utf-8-sig") if sdpair.dcl.exists() else ""
    res_text = sdpair.res.read_text(encoding="utf-8-sig") if sdpair.res.exists() else ""

    def _recompute() -> dict[str, Any]:
        diff_ent = compute_diff_entities(
            table_name=self._ctx.tag_table,
            desired_entities=desired,
            xml_path=variables_xml,
        )
        nmax = compute_nmax_diff_entidades(
            table_name=self._ctx.config_table,
            desired_nmax=get_nmax_entidades(self._ctx.app_state),
            xml_path=config_xml,
        )
        diff_com = compute_comments_diff(
            db_name=self._ctx.db_name,
            array_name=self._ctx.db_array_name,
            desired_entities=desired,
            dcl_text=dcl_text,
            res_text=res_text,
        )
        return {
            "precondiciones_ok": True,
            "db_name": self._ctx.db_name,
            "tag_table": self._ctx.tag_table,
            "config_table": self._ctx.config_table,
            "db_present": not diff_com.missing_xml,
            "table_present": not diff_ent.missing_xml,
            "ops": list(diff_ent.ops),
            "nmax": {
                "todos": nmax.todos,
                "summary": nmax.summary,
            },
            "warnings": list(self._ctx.warnings),
        }

    self._ctx.post_sync_preview = await asyncio.to_thread(_recompute)

    if self._ctx.result is None or not isinstance(self._ctx.result, dict):
        self._ctx.result = _empty_result()
    self._ctx.result["post_sync_preview"] = self._ctx.post_sync_preview
    self._ctx.result["success"] = True
    self._ctx.result["message"] = "Sincronización completada"


# Inyectar los stubs como metodos del FB (para que el STAGES dispatch
# los encuentre). Stages 3-11 ya son metodos reales (en la clase o aqui).
FunctionEntidadesSincronizar._stage_10_tx_c_comments = _stage_10_tx_c_comments  # type: ignore[attr-defined]
FunctionEntidadesSincronizar._stage_11_post_preview = _stage_11_post_preview  # type: ignore[attr-defined]


__all__ = [
    "FunctionEntidadesSincronizar",
    "EntidadesSyncContext",
    "TIA_CONSOLIDATION_SLEEP_S",
]