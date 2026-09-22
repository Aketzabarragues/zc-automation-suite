"""FB de area: preview de dispositivos vs PLC (diff read-only).

State machine sobre el helper ``disp_generate_preview``
(areas/alimentacion/helpers/disp/disp_generate_preview.py). El helper
expone funciones independientes (``exportar_tags``, ``compute_devices``,
``compute_nmax``, ``build_response``) que reciben un
``DispPreviewContext`` y mutan sus campos. **Aqui en el FB vive la
state machine**: el orden de las 4 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Antes: 2 de los 4 steps eran checkpoints vacios
(combinado con...); el resto ejecutaba el helper monolitico de golpe.

Despues: cada step del FB ejecuta una funcion real del
helper contra el ``DispPreviewContext`` compartido entre los 4 ticks.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 4 deps
comunes + 1 especifica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      'agregados':   list[dict],
      'eliminados':  list[dict],
      'renombrados': list[dict],
      'todos':       list[dict],
      'nmax':        dict,
      'summary':     dict,
    }

Steps (4, mismo orden que el legacy ``generar_prevision``):
  - exportar_tags      -> helper.disp_generate_preview.exportar_tags
  - compute_devices    -> helper.disp_generate_preview.compute_devices
  - compute_nmax       -> helper.disp_generate_preview.compute_nmax
  - build_response     -> helper.disp_generate_preview.build_response
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


class FunctionDispGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (N_MAX + devices) de un PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # export_plc_tags_xml sobre 7 tablas puede tardar ~10-30s en S7-1500.
    # 60s cubre holgadamente.
    STEP_TIMEOUT_S: float = 60.0

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
        (1, "exportar_tags",   "_stage_1_exportar_tags"),
        (2, "compute_devices", "_stage_2_compute_devices"),
        (3, "compute_nmax",    "_stage_3_compute_nmax"),
        (4, "build_response",  "_stage_4_build_response"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "disp_generar_preview",
        titulo: str = "Generar preview de dispositivos vs PLC",
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
                {"nombre": "exportar_tags"},
                {"nombre": "compute_devices"},
                {"nombre": "compute_nmax"},
                {"nombre": "build_response"},
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
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        # DispPreviewContext compartido entre los 4 ticks. Se
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
                "FunctionDispGenerarPreview requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionDispGenerarPreview requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDispGenerarPreview.start(plc_name=...) es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Crear el DispPreviewContext que las 4 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/sync/.
        self._ctx = DispPreviewContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando preview de {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``disp_generate_preview``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``DispPreviewContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        if self._ctx is None:
            raise RuntimeError(
                "DispPreviewContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los stages se declaran arriba de la clase. Asi el
        # flujo del FB es visible de un vistazo (modo SFC) y los tests
        # pueden mockear ``fb._stage_N_<nombre>`` directamente sin
        # parchear el ``match`` interno.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 3/4").
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                await handler()
                # Resumen legible del step que acaba de correr.
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionDispGenerarPreview"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        if self._ctx is None:
            # Error temprano: deps no inyectadas o plc_name ausente.
            self.result = {
                "agregados": [],
                "eliminados": [],
                "renombrados": [],
                "todos": [],
                "nmax": {"current": {}, "desired": {}, "todos": [],
                         "summary": {"actualizar": 0, "sin_cambios": 0,
                                     "total": 0}},
                "summary": {"agregados": 0, "eliminados": 0,
                            "renombrados": 0, "sin_cambios": 0,
                            "total": 0},
            }
            return

        self.result = self._ctx.result

        # Log de cierre, igual que hacia el helper monolitico.
        s = self._ctx.result["summary"]
        nmax_summary = self._ctx.result["nmax"]["summary"]
        logger.debug(
            f"[{self.nombre}] preview calculado para "
            f"{self._ctx.plc_name}: "
            f"{s['agregados']} agregados, {s['eliminados']} eliminados, "
            f"{s['renombrados']} renombrados, "
            f"{nmax_summary['actualizar']} N_MAX actualizar"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    async def _stage_1_exportar_tags(self) -> None:
        """Stage 1: limpia preview/ y exporta las tablas selectivas al snapshot."""
        from areas.alimentacion.helpers.build_cache import build_cache

        disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
        disp_ctx.clean_preview()
        self._ctx.tags_base = disp_ctx.preview_variables
        self._ctx.selective_tables = _selective_table_names(self._ctx.config_manager)
        logger.debug(f"workdir (preview): {self._ctx.tags_base}")
        await dispatch_async(
            self._ctx.tia_client,
            "export_plc_tags_xml",
            {
                "plc_name": self._ctx.plc_name,
                "target_dir": str(self._ctx.tags_base),
                "table_names": self._ctx.selective_tables,
            },
        )

    async def _stage_2_compute_devices(self) -> None:
        """Stage 2: calcula el diff de devices entre los XMLs exportados y AppState."""
        assert self._ctx.tags_base is not None, (
            "compute_devices requiere exportar_tags previo"
        )
        self._ctx.desired_state_per_table = _build_desired_state_from_app(
            self._ctx.app_state, self._ctx.config_manager,
        )
        (
            self._ctx.added_per_table,
            self._ctx.removed_per_table,
            self._ctx.renamed_per_table,
            self._ctx.base_state_per_table,
        ) = await asyncio.to_thread(
            _compute_diff_readonly, self._ctx.tags_base, self._ctx.desired_state_per_table,
        )

    async def _stage_3_compute_nmax(self) -> None:
        """Stage 3: calcula el diff de N_MAX entre el TIA (export bulk) y AppState."""
        assert self._ctx.tags_base is not None, (
            "compute_nmax requiere exportar_tags previo"
        )
        self._ctx.nmax_block = await asyncio.to_thread(
            _extract_nmax_diff,
            self._ctx.tags_base, self._ctx.config_manager, self._ctx.app_state,
        )

    async def _stage_4_build_response(self) -> None:
        """Stage 4: compone la shape legacy final con todos los resultados intermedios."""
        agregados: list[dict[str, Any]] = [
            {"uid": uid, "table": tk, "plc_tag": td.get(uid, "")}
            for tk, td in self._ctx.desired_state_per_table.items()
            for uid in self._ctx.added_per_table.get(tk, []) if uid in td
        ]
        eliminados: list[dict[str, Any]] = [
            {"uid": uid, "table": tk, "plc_tag": tb.get(uid, "")}
            for tk, tb in self._ctx.base_state_per_table.items()
            for uid in self._ctx.removed_per_table.get(tk, []) if uid in tb
        ]
        renombrados: list[dict[str, Any]] = [
            {
                "uid": uid.split(":", 1)[1] if ":" in uid else uid,
                "table": uid.split(":", 1)[0] if ":" in uid else "",
                "actual": old,
                "nuevo": new,
            }
            for uid, (old, new) in self._ctx.renamed_per_table.items()
        ]

        def _type_from_table(table_key: str) -> str:
            """``2000_Disp_ED`` -> ``"ed"``, ``2000_Disp_M_VF`` -> ``"m_vf"``."""
            stem = table_key.split("_Disp_", 1)[-1]
            return stem.lower()

        todos: list[dict[str, Any]] = []
        for table_key, base in self._ctx.base_state_per_table.items():
            type_key = _type_from_table(table_key)
            renamed_for_table: dict[str, str] = {}
            for uid, (_old, new) in self._ctx.renamed_per_table.items():
                if uid.startswith(f"{table_key}:"):
                    renamed_for_table[uid.split(":", 1)[1]] = new

            removed_uids = set(self._ctx.removed_per_table.get(table_key, []))

            for uid_str, plc_tag in base.items():
                try:
                    numero = int(uid_str)
                except (TypeError, ValueError):
                    numero = 0
                if uid_str in renamed_for_table:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": renamed_for_table[uid_str],
                        "status": "renombrar",
                    })
                elif uid_str in removed_uids:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": None,
                        "status": "eliminar",
                    })
                else:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": plc_tag,
                        "status": "sin_cambios",
                    })

        for table_key, desired in self._ctx.desired_state_per_table.items():
            type_key = _type_from_table(table_key)
            for uid_str in self._ctx.added_per_table.get(table_key, []):
                try:
                    numero = int(uid_str)
                except (TypeError, ValueError):
                    numero = 0
                todos.append({
                    "table": table_key,
                    "type": type_key,
                    "uid": uid_str,
                    "numero": numero,
                    "actual": None,
                    "nuevo": desired.get(uid_str, ""),
                    "status": "agregar",
                })

        todos.sort(
            key=lambda r: (
                r["type"],
                r["numero"] if isinstance(r["numero"], int) else 0,
            )
        )

        self._ctx.result = {
            "agregados": agregados,
            "eliminados": eliminados,
            "renombrados": renombrados,
            "todos": todos,
            "nmax": self._ctx.nmax_block,
            "summary": {
                "agregados": len(agregados),
                "eliminados": len(eliminados),
                "renombrados": len(renombrados),
                "sin_cambios": sum(
                    1 for r in todos if r["status"] == "sin_cambios"
                ),
                "total": len(todos),
            },
        }


# ============================================================================
# Codigo absorbido de helpers/disp/disp_generate_preview.py (commit 23, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora los 4 stages viven como metodos del FB (mutando ``self._ctx``). Solo
# permanece aqui el ``DispPreviewContext`` (dataclass compartido entre stages)
# y las helpers puras (``_selective_table_names``, ``_build_desired_state_from_app``,
# ``_extract_nmax_diff``, ``_compute_diff_readonly``).
# ============================================================================

@dataclass
class DispPreviewContext:
    """Estado compartido entre las 4 funciones de ``disp_generate_preview``.

    Cada funcion toma un ``DispPreviewContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionDispGenerarPreview`` instancia uno y lo reusa entre sus 4
    ticks para que los resultados intermedios esten disponibles para
    las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path

    # ── Resultados de exportar_tags ──
    tags_base: Path | None = None
    selective_tables: list[str] = field(default_factory=list)

    # ── Resultados de compute_devices ──
    desired_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)
    added_per_table: dict[str, list[str]] = field(default_factory=dict)
    removed_per_table: dict[str, list[str]] = field(default_factory=dict)
    renamed_per_table: dict[str, tuple[str, str]] = field(default_factory=dict)
    base_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)

    # ── Resultados de compute_nmax ──
    nmax_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultado de build_response (shape legacy final) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Helpers puros (cada uno opera sobre los finales; sin state machine aqui)
# ===========================================================================

# Nota: ``dispatch_async`` se importa arriba desde
# ``core.helpers.tia.dispatch_async``. Antes vivia
# duplicado aqui (4 copias en total: 2 disp + 2 proc); ahora vive
# como helper compartido para que cualquier modulo del area lo use.


def _selective_table_names(config_manager: Any) -> list[str]:
    """Lista las tablas que el sync dispositivos toca (data-driven)."""
    nmax_table = config_manager.get_global_config_table_name()
    device_tables = [
        config_manager.get_tag_table_name(hw)
        for hw in config_manager.list_hw_types_active()
        if config_manager.get_tag_table_name(hw) is not None
    ]
    return [nmax_table, *device_tables]


def _build_desired_state_from_app(
    app_state: Any,
    config_manager: Any,
) -> dict[str, dict[str, str]]:
    """Construye ``{tag_table: {uid: plc_tag}}`` desde el AppState."""
    result: dict[str, dict[str, str]] = {}
    for hw in config_manager.list_hw_types_active():
        cfg = config_manager.get_dispositivo_config(hw)
        if cfg is None:
            continue
        # ``DispositivoTIAConfig`` es un dataclass (atributos, NO keys).
        table_name = cfg.tag_table
        # API generica del AppState (data-driven, no ligada a
        # alimentacion). Tras la limpieza de las state extensions
        # legacy (commit 1513ac1) ya no existen properties
        # ``dispositivos_<hw>``; ``get_devices(hw)`` es la unica fuente
        # de verdad (``set_devices`` lo alimenta al subir el Excel).
        devices = app_state.get_devices(hw) if hasattr(app_state, "get_devices") else []
        table_dict: dict[str, str] = {}
        for device in devices:
            numero = int(getattr(device, "numero", 0) or 0)
            plc_tag = str(getattr(device, "plc_tag", "") or "")
            if numero > 0 and plc_tag:
                table_dict[str(numero)] = plc_tag
        if table_dict:
            result[table_name] = table_dict
    return result


def _extract_nmax_diff(
    tags_base: Path,
    config_manager: Any,
    app_state: Any,
) -> dict[str, Any]:
    """Calcula el diff de N_MAX entre el TIA (export bulk) y AppState.

    Las N_MAX son PlcUserConstant de la tabla ``000_Config_Dispositivos``
    que siempre existen en TIA (las 6 dimensiones: ED, EA, SA, V, M,
    M_VF). No se crean ni eliminan: solo se modifica su valor.
    """
    from core.helpers.simatic_ml import PlcUserConstantParser

    nmax_folder = config_manager.get_tia_folder_nmax()
    nmax_table = config_manager.get_global_config_table_name()
    xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

    current: dict[str, int] = {}
    nmax_error: str | None = None
    if xml_path.is_file():
        try:
            current = PlcUserConstantParser.parse_user_constants(xml_path)
        except Exception as e:
            logger.error(f"[N_MAX] Parse FAIL {xml_path}: {e}")
            nmax_error = f"parse fail: {e}"
    else:
        # Si TIA no devolvio nada, current={} lleva al diff a marcar
        # TODAS las dims como "actualizar" enmascarando una falla de
        # export. Marcamos ``nmax_error`` y devolvemos todos=[] para
        # que la SPA muestre el error en vez de proponer cambios
        # falsos.
        logger.warning(f"[N_MAX] XML esperado no encontrado: {xml_path}")
        nmax_error = (
            f"XML de N_MAX no encontrado en TIA export: {xml_path}"
        )

    d = app_state.dimensiones or {}
    desired: dict[str, int] = {}
    for nmax_name in config_manager.list_nmax_active():
        v = d.get(nmax_name)
        if v is None:
            v = 0
        desired[nmax_name] = int(v)

    # Si hubo error de export, NO generamos ``todos``: seria un diff
    # contra current={} que marcaria TODO como actualizar.
    if nmax_error is not None:
        return {
            "current": {},
            "desired": desired,
            "todos": [],
            "summary": {
                "actualizar": 0,
                "sin_cambios": len(desired),
                "total": len(desired),
            },
            "nmax_error": nmax_error,
        }

    todos: list[dict[str, Any]] = []
    for name in desired.keys():
        cur_val = current.get(name)
        des_val = desired[name]
        if cur_val is not None and cur_val == des_val:
            status = "sin_cambios"
        else:
            status = "actualizar"
        todos.append({
            "name": name,
            "actual": cur_val,
            "nuevo": des_val,
            "status": status,
        })

    return {
        "current": current,
        "desired": desired,
        "todos": todos,
        "summary": {
            "actualizar": sum(
                1 for r in todos if r["status"] == "actualizar"
            ),
            "sin_cambios": sum(
                1 for r in todos if r["status"] == "sin_cambios"
            ),
            "total": len(todos),
        },
        "nmax_error": None,
    }


def _compute_diff_readonly(
    tags_base: Path,
    desired_state_per_table: dict[str, dict[str, str]],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, tuple[str, str]],
    dict[str, dict[str, str]],
]:
    """Calcula el diff de devices en modo read-only (no modifica XML)."""
    from core.infrastructure.tia.tia_export_paths import XmlTarget
    from core.helpers.simatic_ml import PlcUserConstantModifier

    base_state_per_table: dict[str, dict[str, str]] = {}
    missing_tables: list[str] = []
    for table_key in desired_state_per_table.keys():
        try:
            xml_path = XmlTarget(tags_base, table_key).path
        except FileNotFoundError:
            # El XML del tipo de dispositivo no esta en TIA
            # (ni en ruta directa ni en rglob fallback). Lo
            # marcamos como "missing" para avisar al operario
            # en el preview, pero seguimos con los otros tipos.
            logger.warning(
                f"[disp preview] XML no encontrado para tabla "
                f"'{table_key}' en {tags_base}. Se omite del diff."
            )
            missing_tables.append(table_key)
            continue
        modifier = PlcUserConstantModifier(xml_path)
        table_constants: dict[str, str] = {}
        for value_str, plc_tag in (
            modifier.read_user_constants_with_uids().items()
        ):
            if value_str and plc_tag:
                table_constants[value_str] = plc_tag
        if table_constants:
            base_state_per_table[table_key] = table_constants

    added_per_table: dict[str, list[str]] = {}
    removed_per_table: dict[str, list[str]] = {}
    renamed_per_table: dict[str, tuple[str, str]] = {}

    for table_key, desired in desired_state_per_table.items():
        base = base_state_per_table.get(table_key, {})
        base_values = set(base.keys())
        desired_values = set(desired.keys())
        added = sorted(desired_values - base_values)
        removed = sorted(base_values - desired_values)
        renamed: dict[str, tuple[str, str]] = {}
        for uid in base_values & desired_values:
            if base[uid] != desired[uid]:
                renamed[f"{table_key}:{uid}"] = (base[uid], desired[uid])
        if added:
            added_per_table[table_key] = added
        if removed:
            removed_per_table[table_key] = removed
        renamed_per_table.update(renamed)

    return (
        added_per_table,
        removed_per_table,
        renamed_per_table,
        base_state_per_table,
    )


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "exportar_tags":
        return (
            f"{step_nombre}: {len(ctx.selective_tables)} tablas exportadas"
        )
    if step_nombre == "compute_devices":
        adds = sum(len(v) for v in ctx.added_per_table.values())
        rems = sum(len(v) for v in ctx.removed_per_table.values())
        return (
            f"{step_nombre}: {adds} adds, {rems} removes, "
            f"{len(ctx.renamed_per_table)} renames"
        )
    if step_nombre == "compute_nmax":
        nmax_summary = ctx.nmax_block.get("summary", {})
        return (
            f"{step_nombre}: {nmax_summary.get('actualizar', 0)} N_MAX "
            f"actualizar, {nmax_summary.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "build_response":
        s = ctx.result.get("summary", {})
        return (
            f"{step_nombre}: {s.get('total', 0)} entradas en vista unificada"
        )
    return f"{step_nombre}: OK"


__all__ = ["FunctionDispGenerarPreview"]