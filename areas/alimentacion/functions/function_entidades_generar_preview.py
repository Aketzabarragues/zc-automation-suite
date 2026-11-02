"""FB de area: preview de entidades vs PLC (diff read-only).

State machine sobre el helper ``entidades_generate_preview``
(areas/alimentacion/helpers/entidades/entidades_generate_preview.py).
El helper expone funciones independientes (``compute_diff_entities``,
``compute_nmax_diff_entidades``, ``compute_comments_diff``,
``compute_summary``) que reciben un ``EntidadesPreviewContext`` y mutan
sus campos. **Aqui en el FB vive la state machine**: el orden de las
5 llamadas, el mapping step -> funcion del helper, y la instanciacion
del ctx.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 4 deps
comunes + 1 especifica (``app_cache``).

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape::

    {
      'precondiciones_ok':  bool,
      'missing_blocks':     [str],
      'db_name':            "DB6_ENT",
      'db_array_name':      "ENT",
      'tag_table':          "6_Entidades",
      'config_table':       "0_Config_Generales",
      'db_present':         bool,
      'table_present':      bool,
      'arrays':             {"ENT": [...]},
      'constants':          {"agregados": [...], "eliminados": [...], ...},
      'nmax':               {current, desired, todos, summary, nmax_error},
      'summary':            {constants_agregados, ..., total},
      'warnings':           [str],
    }

Al terminar (``on_finish``) publica ese ``result`` en el AppCache
(slot ``preview_disp``): es el canal por el que la SPA recibe el
preview (SSE ``cache_changed``). El router solo encola el trabajo.

Steps (5, en orden de flujo). Cada step se declara encima de su
propio codigo con ``@step`` y devuelve su detail:
  - Exportar etiquetas y DB              -> export_tables + export_blocks
  - Calcular diferencias de N_MAX_ENTIDAD -> compute_nmax_diff_entidades
  - Calcular diferencias de constantes    -> compute_diff_entities
  - Calcular diferencias de comentarios   -> compute_comments_diff
  - Componer respuesta                   -> compute_summary + shape final
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase
from core.helpers.tia.active_cache import (
    get_entidades,
    get_nmax,
    get_nmax_entidades,
)
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia
from core.helpers.tia.with_plc import with_plc
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.app_cache import AppCache, get_app_cache
from areas.alimentacion._area_id import AREA_ID
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen (idempotente).
install_web_level()


class FunctionEntidadesGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (N_MAX + constantes + comentarios) de entidades."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # export_tables (2 tablas) + export_blocks (1 DB con UDT array
    # de N_MAX_ENTIDAD slots) puede tardar ~30-60s en S7-1500 grandes.
    # 60s cubre holgadamente.
    STEP_TIMEOUT_S: float = 60.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "entidades_generar_preview",
        titulo: str = "Generar preview de entidades vs PLC",
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
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        # EntidadesPreviewContext compartido entre los 5 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + crear ctx."""
        if self._config is None:
            raise RuntimeError(
                "FunctionEntidadesGenerarPreview requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionEntidadesGenerarPreview requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionEntidadesGenerarPreview.execute(plc_name=...) es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Validar contra TIA Portal (fail-late).
        validate_plc_in_tia(self._tia_client, self._plc_name)
        # Validar contra el Excel cargado.
        validate_plc_in_excel(self._app_cache, self._plc_name, AREA_ID)
        # Propagar al AppCache (defensa redundante con el endpoint).
        with_plc(self._app_cache, self._plc_name, AREA_ID)

        # Crear el EntidadesPreviewContext que las 5 funciones iran mutando.
        self._ctx = EntidadesPreviewContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_cache=self._app_cache,
            build_cache_root=self._build_cache_root,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando preview de entidades de {self._plc_name}"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que espera la SPA.

        El router solo encola el trabajo, asi que la publicacion del
        preview en el AppCache ocurre aqui, cuando el FB ha terminado.
        """
        if self._ctx is None:
            # Error temprano: deps no inyectadas o plc_name ausente.
            self.result = _empty_result()
            return

        self.result = self._ctx.result

        s = self._ctx.result.get("summary", {})
        logger.debug(
            f"[{self.nombre}] preview calculado para "
            f"{self._ctx.plc_name}: "
            f"{s.get('constants_agregados', 0)} const adds, "
            f"{s.get('comments_added', 0)} comments adds, "
            f"{s.get('comments_updated', 0)} comments updates"
        )

        self._publish_result_to_cache()
        logger.ok(
            f"Prevision de entidades de '{self._ctx.plc_name}': "
            f"{s.get('constants_agregados', 0)} const adds, "
            f"{s.get('comments_added', 0)} comments adds, "
            f"{s.get('comments_updated', 0)} comments updates"
        )

    def _publish_result_to_cache(self) -> None:
        """Publica el preview de entidades en el AppCache.

        El AppCache es el canal por el que la SPA se entera: lee este
        slot y lo recibe por SSE (``cache_changed``). El router solo
        encola el trabajo, asi que la publicacion tiene que ocurrir
        aqui, cuando el FB ha terminado.

        Slot: ``preview_disp`` (el mismo que el preview de dispositivos:
        ambos bounded context operan sobre la misma "prevision de disp").
        """
        from core.runtime.app_cache import get_app_cache
        from core.runtime.area_preview_cache import area_set_preview_disp

        app_cache = get_app_cache()
        area_set_preview_disp(app_cache, "alimentacion", self.result)

    # ==================================================================
    # LOS STEPS
    #
    # Cada ``_stage_N_<slug>`` es un step declarado con ``@step``. El
    # motor los recoge en orden de definicion (que es el orden del
    # flujo) y hace el dispatch. El metodo devuelve su detail.
    # ==================================================================

    @step(
        "Exportar etiquetas y DB",
        descripcion="Exporta del PLC las tablas de etiquetas y el bloque DB",
    )
    def _stage_1_exportar_etiquetas_y_db(self) -> str:
        """Stage 1: limpia preview/ y exporta las 2 tablas selectivas + el DB.

        Layout nuevo (.build_cache/alimentacion/entidades/preview/):
          - config/         0_Config_Generales.xml (N_MAX_ENTIDAD)
          - disp/           6_Entidades.xml (ent_<plc_tag>)
          - bloques/        DB6_ENT.s7dcl + DB6_ENT.s7res

        Politica ante fallos del worker TIA (comportamiento mismo
        que proc_db_preview): si una tabla o el DB no existen en
        TIA (caso del operario que aun no creo DB6_ENT), el FB **NO**
        aborta: marca el bloque como ``missing_xml`` / emite un warning
        y los stages posteriores (n_max / constantes / comentarios)
        devolveran diff vacio para ese lado. El operario sigue viendo
        el preview de las partes que SI existen.

        Si el worker TIA retorna ``None``, el stage NO aborta:
        marca el bloque como ``missing_xml`` y continua.
        """
        from areas.alimentacion.helpers.layout.build_cache import build_cache

        ent_ctx = build_cache(root=self._ctx.build_cache_root).entidades
        ent_ctx.clean_preview()
        self._ctx.preview_disp_dir = ent_ctx.preview_disp
        self._ctx.preview_bloques_dir = ent_ctx.preview_bloques

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

        # 2/3: export_tables (2 tablas) en 1 dispatch FLAT.
        # Si el worker falla (Tia puede no tener las tablas aun),
        # el comando retorna None (no raise). Capturamos y
        # seguimos: compute_* vera ``missing_xml=True`` y devolvera
        # diff vacio para esa parte.
        tags_result = self._ctx.tia_client.submit_and_wait(
            "export_tables",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.preview_disp_dir),
                "table_names": [config_table, tag_table],
                "keep_folder_structure": False,
            },
            timeout=60.0,
        )
        if tags_result is None:
            warning = (
                f"export_tables fallo (Tia puede no tener "
                f"'{config_table}' o '{tag_table}' todavia). "
                f"Tablas entities marcadas como missing_xml."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)
        else:
            logger.debug(
                f"  {config_table} + {tag_table} exportadas a "
                f"{self._ctx.preview_disp_dir}"
            )

        # 3/3: export_blocks (DB6_ENT) a preview/bloques/.
        block_result = self._ctx.tia_client.submit_and_wait(
            "export_blocks",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.preview_bloques_dir),
                "block_names": [db_name],
            },
            timeout=60.0,
        )
        if block_result is None:
            warning = (
                f"export_blocks fallo: bloque '{db_name}' no encontrado "
                f"en PLC '{self._ctx.plc_name}'. "
                f"Comments diff no disponible."
            )
            logger.warning(warning)
            self._ctx.warnings.append(warning)
        else:
            logger.debug(
                f"  {db_name} exportado a {self._ctx.preview_bloques_dir}"
            )

        return "Exportar etiquetas y DB: 2 tablas + DB6_ENT exportados"

    @step(
        "Calcular diferencias de N_MAX_ENTIDAD",
        descripcion="Compara la tabla N_MAX_ENTIDAD del PLC con la del Excel",
    )
    def _stage_2_calcular_diferencias_de_n_max_entidad(self) -> str:
        """Stage 2: calcula el diff de N_MAX_ENTIDAD."""
        assert self._ctx.preview_disp_dir is not None
        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_nmax_diff_entidades,
        )

        # N_MAX_ENTIDAD vive en 0_Config_Generales. El cache del PLC
        # activo lo expone en ``DataDimensionesPLC.n_max_entidades``
        # (campo separado de ``extras``: su entrada en ``n_max_catalog``
        # tiene ``hw_type=""`` y por eso ``get_nmax`` NO lo incluye).
        # Usamos el helper dedicado ``get_nmax_entidades``.
        desired_nmax = get_nmax_entidades(self._ctx.app_cache, AREA_ID)

        # El export bulk del Stage 1 copio AMBAS tablas a preview_disp/
        # (FLAT). El de 0_Config_Generales esta entre ellos.
        xml_path = self._ctx.preview_disp_dir / f"{self._ctx.config_table}.xml"

        def _compute() -> Any:
            return compute_nmax_diff_entidades(
                table_name=self._ctx.config_table,
                desired_nmax=desired_nmax,
                xml_path=xml_path,
            )

        nmax_diff = _compute()

        self._ctx.nmax_block = {
            "current":   nmax_diff.current,
            "desired":   nmax_diff.desired,
            "todos":     nmax_diff.todos,
            "summary":   nmax_diff.summary,
            "nmax_error": (
                f"XML de N_MAX_ENTIDAD no encontrado en TIA export: {xml_path}"
                if nmax_diff.missing_xml else None
            ),
        }

        nmax_summary = self._ctx.nmax_block.get("summary", {})
        return (
            f"Calcular diferencias de N_MAX_ENTIDAD: "
            f"{nmax_summary.get('actualizar', 0)} N_MAX actualizar, "
            f"{nmax_summary.get('sin_cambios', 0)} sin cambios"
        )

    @step(
        "Calcular diferencias de constantes",
        descripcion="Compara las constantes de entidades del PLC con las del Excel",
    )
    def _stage_3_calcular_diferencias_de_constantes(self) -> str:
        """Stage 3: calcula el diff de PlcUserConstants ``ent_<plc_tag>``."""
        assert self._ctx.preview_disp_dir is not None
        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_diff_entities,
        )

        desired = get_entidades(self._ctx.app_cache, self._ctx.plc_name, AREA_ID)
        xml_path = self._ctx.preview_disp_dir / f"{self._ctx.tag_table}.xml"

        def _compute() -> Any:
            return compute_diff_entities(
                table_name=self._ctx.tag_table,
                desired_entities=desired,
                xml_path=xml_path,
            )

        diff = _compute()

        self._ctx.entities_block = {
            "base":         diff.base,
            "base_comments": diff.base_comments,
            "desired":      diff.desired,
            "added":        diff.added,
            "removed":      diff.removed,
            "renamed":      diff.renamed,
            "missing_xml":  diff.missing_xml,
        }
        # Lista unica de ops a aplicar por el sync. El preview FB la
        # reusa en stage 5; la SPA la consume desde ``data.ops``.
        self._ctx.entities_ops = list(diff.ops)

        if not self._ctx.entities_block:
            return "Calcular diferencias de constantes: sin datos"
        adds = len(self._ctx.entities_block.get("added", []))
        rems = len(self._ctx.entities_block.get("removed", []))
        rens = len(self._ctx.entities_block.get("renamed", {}))
        return (
            f"Calcular diferencias de constantes: {adds} adds, "
            f"{rems} removes, {rens} renames"
        )

    @step(
        "Calcular diferencias de comentarios",
        descripcion="Compara los comentarios del array ENT[] con los del Excel",
    )
    def _stage_4_calcular_diferencias_de_comentarios(self) -> str:
        """Stage 4: calcula el diff de comentarios del array ``ENT[]`` de ``DB6_ENT``."""
        assert self._ctx.preview_bloques_dir is not None
        from core.infrastructure.tia.tia_export_paths import SdPair
        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_comments_diff,
        )

        desired = get_entidades(self._ctx.app_cache, self._ctx.plc_name, AREA_ID)

        dcl_path = SdPair(self._ctx.preview_bloques_dir, self._ctx.db_name).dcl
        res_path = SdPair(self._ctx.preview_bloques_dir, self._ctx.db_name).res
        dcl_text = dcl_path.read_text(encoding="utf-8-sig") if dcl_path.exists() else ""
        res_text = res_path.read_text(encoding="utf-8-sig") if res_path.exists() else ""

        def _compute() -> Any:
            return compute_comments_diff(
                db_name=self._ctx.db_name,
                array_name=self._ctx.db_array_name,
                desired_entities=desired,
                dcl_text=dcl_text,
                res_text=res_text,
            )

        diff = _compute()

        self._ctx.comments_block = {
            "slots_tia":   list(diff.slots_tia),
            "current":     dict(diff.current),
            "desired":     dict(diff.desired),
            "added":       diff.added,
            "removed":     diff.removed,
            "updated":     diff.updated,
            "unchanged":   diff.unchanged,
            "missing_xml": diff.missing_xml,
        }

        if diff.missing_xml:
            warning = (
                f"DB '{self._ctx.db_name}' sin archivos .s7dcl/.s7res "
                f"en TIA export. Comments diff no disponible."
            )
            self._ctx.warnings.append(warning)

        if not self._ctx.comments_block:
            return "Calcular diferencias de comentarios: sin datos"
        added = len(self._ctx.comments_block.get("added", []))
        updated = len(self._ctx.comments_block.get("updated", []))
        unchanged = len(self._ctx.comments_block.get("unchanged", []))
        return (
            f"Calcular diferencias de comentarios: {added} adds, "
            f"{updated} updates, {unchanged} unchanged"
        )

    @step(
        "Componer respuesta",
        descripcion="Compone la vista unificada que consume la SPA",
    )
    def _stage_5_componer_respuesta(self) -> str:
        """Stage 5: compone la shape final con todos los resultados intermedios.

        Metodo sync: el motor lo invoca como ``handler()`` y usa su
        propio detail como texto del step.
        """
        from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
            compute_summary,
            detect_inconsistencias_plc_tags,
            DiffEntities,
            DiffComments,
        )

        if self._ctx.entities_block is None or self._ctx.comments_block is None:
            # Stages previos fallaron (missing_xml etc.). Devolvemos
            # shape vacio pero valido.
            self._ctx.result = _empty_result()
            self._ctx.result["precondiciones_ok"] = False
            self._ctx.result["missing_blocks"] = [
                "Stages previos no completaron (revisa warnings)."
            ]
            return "Componer respuesta: preview compuesto"

        # Reconstruir dataclasses frozen para reusar compute_summary().
        # Si el caller ya computo entities_ops (sync FB, preview FB
        # via stage 3), lo respetamos; si no, queda vacio.
        diff_ent = DiffEntities(
            table_name=self._ctx.tag_table,
            base=self._ctx.entities_block["base"],
            desired=self._ctx.entities_block["desired"],
            added=self._ctx.entities_block["added"],
            removed=self._ctx.entities_block["removed"],
            renamed=self._ctx.entities_block["renamed"],
            base_comments=self._ctx.entities_block.get("base_comments", {}),
            missing_xml=self._ctx.entities_block["missing_xml"],
            ops=list(getattr(self._ctx, "entities_ops", []) or []),
        )
        diff_com = DiffComments(
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

        summary = compute_summary(diff_ent, diff_com)

        # Tabla unificada "constants.todos": una fila por plc_tag con
        # status agregado (agregados / eliminados / renombrados /
        # sin_cambios). Mantenido por compat con consumers que ya lo leen.
        constants_todos = _build_constants_todos(diff_ent)

        # Tabla unificada "arrays.ENT" (compat con consumers externos).
        arrays_ent = _build_arrays_ent(diff_com)

        # Warnings de plc_tags NO canonicos: TIA tiene ``Constant_1``
        # con value=4 mientras el Excel tiene ``ENT_004`` con numero=4.
        # El sync no puede decidir por si solo; el operador debe
        # resolver manualmente.
        inconsistencies = detect_inconsistencias_plc_tags(diff_ent)

        self._ctx.result = {
            "precondiciones_ok": True,
            "missing_blocks":    [],
            "db_name":           self._ctx.db_name,
            "db_array_name":     self._ctx.db_array_name,
            "tag_table":         self._ctx.tag_table,
            "config_table":      self._ctx.config_table,
            "db_present":        not self._ctx.comments_block["missing_xml"],
            "table_present":     not self._ctx.entities_block["missing_xml"],
            "arrays": {
                self._ctx.db_array_name: arrays_ent,
            },
            # Lista unica de ops a aplicar por el sync (orden de
            # aplicacion del sync FB). La SPA consume ``data.ops``
            # directamente; las keys legacy (``constants`` / ``unified``)
            # se mantienen por compat con consumers externos.
            "ops": list(diff_ent.ops),
            "constants": {
                "agregados": [
                    {"plc_tag": plc_tag, "numero": diff_ent.desired[plc_tag],
                     "actual": None, "status": "agregar"}
                    for plc_tag in diff_ent.added
                ],
                "eliminados": [
                    {"plc_tag": plc_tag, "numero": diff_ent.base[plc_tag],
                     "actual": diff_ent.base[plc_tag], "nuevo": None,
                     "status": "eliminar"}
                    for plc_tag in diff_ent.removed
                ],
                "renombrados": [
                    {"plc_tag": plc_tag,
                     "actual": diff_ent.base[plc_tag],
                     "nuevo": diff_ent.desired[plc_tag],
                     "status": "renombrar"}
                    for plc_tag, (old, new) in diff_ent.renamed.items()
                ],
                "todos": constants_todos,
            },
            "nmax":    self._ctx.nmax_block,
            "summary": summary,
            "warnings": list(self._ctx.warnings) + inconsistencies,
        }

        return "Componer respuesta: preview compuesto"


# ============================================================================
# Helpers puros (estado entre stages + composicion del response)
# ============================================================================


@dataclass
class EntidadesPreviewContext:
    """Estado compartido entre las 5 funciones de ``entidades_generate_preview``.

    Cada stage toma este context por argumento, lee las deps inyectadas
    y los resultados de stages previos, y muta los campos que representan
    resultados de su trabajo.
    """

    # ── Deps inyectadas ──
    plc_name: str
    tia_client: Any
    config_manager: Any
    app_cache: AppCache
    build_cache_root: Path

    # ── Estado del config ──
    db_name: str = "DB6_ENT"
    db_array_name: str = "ENT"
    tag_table: str = "6_Entidades"
    config_table: str = "0_Config_Generales"

    # ── Resultados de exportar (stage 1) ──
    preview_disp_dir: Path | None = None
    preview_bloques_dir: Path | None = None

    # ── Resultados de n_max (stage 2) ──
    nmax_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de constantes (stage 3) ──
    entities_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de comentarios (stage 4) ──
    comments_block: dict[str, Any] = field(default_factory=dict)

    # ── Warnings acumulados ──
    warnings: list[str] = field(default_factory=list)

    # ── Resultado de la respuesta (stage 5) ──
    result: dict[str, Any] = field(default_factory=dict)


def _build_constants_todos(diff_ent: Any) -> list[dict[str, Any]]:
    """Lista unificada de entries de la tabla de constantes para la SPA.

    Shape por entry:
        plc_tag       : str. SIEMPRE la key del match (mismo nombre
                        en TIA y Excel cuando la entry matchea).
        plc_tag_tia   : str o None. plc_tag que tiene TIA (None si la
                        entry NO existe en TIA, p.ej. status=agregar).
        plc_tag_excel : str o None. plc_tag que tiene Excel (None si la
                        entry NO existe en Excel, p.ej. status=eliminar).
        actual        : int o None. value (numero) en TIA, None si no existe.
        nuevo         : int o None. value (numero) en Excel, None si no existe.
        status        : "agregar" | "renombrar" | "eliminar" | "sin_cambios".

    Los campos ``plc_tag_tia`` y ``plc_tag_excel`` permiten a la SPA
    renderizar 2 columnas independientes (TAG que tiene TIA y TAG que
    tiene Excel), una por lado, en lugar de mezclar ambas en una sola
    columna ``plc_tag`` redundante.
    """
    rows: list[dict[str, Any]] = []
    for plc_tag, numero in diff_ent.base.items():
        # plc_tag SIEMPRE viene de base.keys() aqui -> existe en TIA.
        if plc_tag in diff_ent.renamed:
            old, new = diff_ent.renamed[plc_tag]
            rows.append({
                "plc_tag":       plc_tag,
                "plc_tag_tia":   plc_tag,
                "plc_tag_excel": plc_tag,
                "actual":        old,
                "nuevo":         new,
                "status":        "renombrar",
            })
        elif plc_tag in diff_ent.removed:
            rows.append({
                "plc_tag":       plc_tag,
                "plc_tag_tia":   plc_tag,
                "plc_tag_excel": None,
                "actual":        numero,
                "nuevo":         None,
                "status":        "eliminar",
            })
        elif plc_tag in diff_ent.desired:
            rows.append({
                "plc_tag":       plc_tag,
                "plc_tag_tia":   plc_tag,
                "plc_tag_excel": plc_tag,
                "actual":        numero,
                "nuevo":         diff_ent.desired[plc_tag],
                "status":        "sin_cambios",
            })
    for plc_tag in diff_ent.added:
        # plc_tag SOLO existe en Excel (added = desired - base).
        rows.append({
            "plc_tag":       plc_tag,
            "plc_tag_tia":   None,
            "plc_tag_excel": plc_tag,
            "actual":        None,
            "nuevo":         diff_ent.desired[plc_tag],
            "status":        "agregar",
        })
    return rows


def _build_arrays_ent(diff_com: Any) -> list[dict[str, Any]]:
    """Lista unificada de slots del array ENT[] para la SPA."""
    rows: list[dict[str, Any]] = []
    for slot in sorted(diff_com.slots_tia):
        actual = diff_com.current.get(slot)
        desired = diff_com.desired.get(slot)
        if slot in diff_com.added:
            status = "agregar"
        elif slot in diff_com.updated:
            status = "renombrar"
        else:
            status = "sin_cambios"
        rows.append({
            "slot":    slot,
            "actual":  actual,
            "nuevo":   desired,
            "status":  status,
        })
    return rows


def _empty_result() -> dict[str, Any]:
    """Shape vacia pero valida, para errores tempranos (deps / plc_name)."""
    return {
        "precondiciones_ok": False,
        "missing_blocks":    ["FB no llego a ejecutar (deps no inyectadas "
                              "o plc_name no proporcionado)"],
        "db_name":           "DB6_ENT",
        "db_array_name":     "ENT",
        "tag_table":         "6_Entidades",
        "config_table":      "0_Config_Generales",
        "db_present":        False,
        "table_present":     False,
        "arrays":            {},
        "constants":         {"agregados": [], "eliminados": [],
                              "renombrados": [], "todos": []},
        "nmax":              {"current": {}, "desired": {}, "todos": [],
                               "summary": {"actualizar": 0, "sin_cambios": 0,
                                           "total": 0},
                               "nmax_error": None},
        "summary":           {"constants_agregados": 0,
                              "constants_eliminados": 0,
                              "constants_renombrados": 0,
                              "constants_sin_cambios": 0,
                              "comments_added": 0,
                              "comments_updated": 0,
                              "comments_unchanged": 0,
                              "total": 0},
        "warnings":          [],
    }


__all__ = ["FunctionEntidadesGenerarPreview"]