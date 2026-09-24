"""FB de area: aplicar la clonacion de un proceso desde plantilla.

State machine sobre el contexto ``ProcProcessGenContext`` (definido al
final de este archivo). Los 9 stages viven como metodos del FB (mutando
``self._ctx``); las funciones puras del pipeline viven debajo del
dataclass en el mismo archivo.

El orquestador y la dataclass permanecen en el archivo del FB; los
helpers puros (filesystem puro, sin TIA) se exponen como funciones
module-level debajo del dataclass.

Ademas, este FB dispara 2 dispatches al worker OT:

  - Stage 7 (importar_proceso): ``execute_transactional_batch`` con 3
    ops bajo una sola transaccion TIA (import_plc_tags_xml +
    ``_wait`` 2s + import_blocks_sd). Si cualquier op falla, TIA hace
    rollback atomico de las 3 juntas.
  - Stage 8 (compilar): ``compile_plc`` (fuera de transaccion; TIA
    compila todos los cambios pendientes del PLC).

Si el lote transaccional falla, TIA hace rollback atomico de las
3 ops juntas, dejando el PLC en el mismo estado previo al apply.

Restricciones CRITICAS del dispatch al worker OT:
  - ``import_plc_tags_xml`` / ``import_blocks_sd`` distinguen entre
    ``target_folder_path=None`` (default, NO pasar el argumento; TIA
    hace match UPDATE recursivo preservando el subpath del archivo
    dentro del ``import_dir``) y ``target_folder_path=""`` (string
    vacio explicito; TIA intenta CREATE y falla con "Import failed
    because an object with the name X already exists in the plc").
  - Por eso en este FB NUNCA pasamos ``target_folder`` — lo omitimos
    para que el handler use el default ``None`` y TIA haga UPDATE
    correcto. Ver ``tia_handlers._h_import_block`` para detalle.

Hereda directo de ``FunctionBase``.

Runtime params via ``start(**kwargs)``:
  - ``plantillas_path`` (str): ruta base de las plantillas TIA. Oblig.
  - ``dir_plantilla_nombre`` (str): nombre de la plantilla concreta.
    Obligatorio.
  - ``base_nueva`` (int): UID base del proceso nuevo. Obligatorio.
  - ``codigo_nuevo`` (str): codigo corto. Obligatorio.
  - ``nombre_nuevo`` (str): nombre humano. Obligatorio.
  - ``minimos_usuario`` (dict[str, int]): 4 N_MAX del operario. Oblig.
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.
  - ``plc_blocks_cache`` (list[dict] | None): bloques que ya existen
    en el PLC destino. Cada item es ``{"nombre": str, "numero": int}``.
    Si es None, el helper emite warning; si hay colisiones, el FB
    aborta en ``detectar_colisiones`` (que SI se llama en este FB).
    ``set[str]`` / ``list[str]`` legacy se aceptan y se convierten
    defensivamente a ``[{"nombre": s}]``.
  - ``build_cache_root`` (Path): raiz del BuildCache del area.

El ``self.result`` se popula con la shape esperada por la SPA::

    {
      "manifest_plantilla": dict | None,
      "archivos_generados": list[str],
      "colisiones":         list[str],
      "nuevo_dir":          str,
      "success":            bool,
      "process_label":      str,       # "100_CPR"; sept-2026
      "import_result":      dict | None,
      "compile_result":     dict | None,
    }

``import_result`` es el dict que devuelve
``execute_transactional_batch``::

    {
      "success": True,
      "operations_executed": 3,
      "details": [
        {"step": 1, "command": "import_plc_tags_xml", "result": ...},
        {"step": 2, "command": "_wait", "result": "sleep 2.0s"},
        {"step": 3, "command": "import_blocks_sd", "result": ...},
      ],
    }

Steps (9):
  - Leer manifiesto              -> proc_process_leer_manifest (inline)
  - Validar mínimos              -> proc_process_validar_minimos (inline)
  - Copiar a vista previa        -> proc_process_copiar_a_preview (inline)
  - Construir diccionarios       -> proc_process_construir_diccionarios (inline)
  - Generar proceso nuevo        -> proc_process_aplicar_clonacion (inline)
  - Escribir manifiesto modified -> proc_process_escribir_manifest (inline)
  - Importar proceso             -> execute_transactional_batch (3 ops)
  - Compilar bloques             -> compile_plc (fuera de tx)
  - Componer respuesta           -> proc_process_done_summary (inline)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)

# Mismo sleep que usan ``proc_sincronizar.wait_consolidation`` y
# ``disp_Sincronizar.wait_consolidation`` tras un import masivo. TIA
# necesita consolidar internamente antes de aceptar un segundo import.
# Aqui el sleep vive DENTRO del handler
# ``_h_execute_transactional_batch`` (sub-comando ``_wait``), no en el
# FB — el FB solo lo declara como op del lote.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


# ============================================================================
# Constantes y errores del pipeline (duplicadas del FB preview por
# autonomía; cualquier cambio debe replicarse en ambos archivos).
# ============================================================================

EXTENSIONES_TEXTO: frozenset[str] = frozenset({
    ".s7dcl", ".s7res", ".scl", ".xml", ".awl",
})

N_MAX_KEYS: tuple[str, ...] = (
    "N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI",
)


class PlantillaMinimosNoCumplidos(ValueError):
    """Lanzada si los N_MAX del operario son menores que los de la plantilla."""


class ManifestInvalido(ValueError):
    """Lanzada si el manifest.json de la plantilla no existe o le faltan campos."""


@dataclass
class ProcProcessGenContext:
    """Estado compartido entre los 9 stages del FB sync.

    Copia local del dataclass en ``function_proc_crear_generar_preview``.
    Cada FB es autonomo (mismo patron que ``DispPreviewContext`` /
    ``ProcPreviewContext`` en los FBs del greenfield) — si en el
    futuro divergen, son contextos distintos.
    """

    # ── Deps inyectadas ──
    dir_plantilla: Path
    dir_plantilla_copia: Path
    dir_nuevo: Path
    base_nueva: int
    codigo_nuevo: str
    nombre_nuevo: str
    plc_blocks_cache: list[dict[str, Any]] | None
    minimos_usuario: dict[str, int]

    # ── Resultado de leer_manifest ──
    manifest_plantilla: dict[str, Any] | None = None
    base_vieja: int = 0
    codigo_viejo: str = ""
    nombre_viejo: str = ""

    # ── Resultado de construir_diccionarios ──
    dicc_bloques: dict[str, str] = field(default_factory=dict)
    dicc_xml: dict[str, str] = field(default_factory=dict)

    # ── Resultado de detectar_colisiones ──
    colisiones: list[str] = field(default_factory=list)
    colisiones_con: dict[str, str] = field(default_factory=dict)

    # ── Resultado de aplicar / generar_previstos ──
    archivos_previstos: list[dict[str, Any]] = field(default_factory=list)
    archivos_generados: list[str] = field(default_factory=list)

    # ── Resultado final ──
    result: dict[str, Any] = field(default_factory=dict)


class FunctionProcCrearSincronizar(FunctionBase):
    """FB que clona un proceso desde plantilla TIA y lo importa al PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # 2 dispatches al worker OT (1 lote transaccional + 1 compile).
    # En PLCs grandes el import masivo puede tardar 1-3 min, el compile
    # hasta 5 min. 600s cubre holgadamente.
    STEP_TIMEOUT_S: float = 600.0

    STAGES: list[tuple[int, str, str]] = [
        (1, "Leer manifiesto",             "_stage_1_leer_manifest"),
        (2, "Validar mínimos",             "_stage_2_validar_minimos"),
        (3, "Copiar a vista previa",       "_stage_3_copiar_a_preview"),
        (4, "Construir diccionarios",      "_stage_4_construir_diccionarios"),
        (5, "Generar proceso nuevo",       "_stage_5_generar_proceso_nuevo"),
        (6, "Escribir manifiesto modificado", "_stage_6_escribir_manifest_modified"),
        (7, "Importar proceso",            "_stage_7_importar_proceso"),
        (8, "Compilar bloques",            "_stage_8_compilar"),
        (9, "Refrescar BloqueCache",       "_stage_9_refresh_cache"),
        (10, "Componer respuesta",         "_stage_10_build_response"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_process_crear_aplicar",
        titulo: str = "Crear proceso desde plantilla (apply)",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Leer manifiesto"},
                {"nombre": "Validar mínimos"},
                {"nombre": "Copiar a vista previa"},
                {"nombre": "Construir diccionarios"},
                {"nombre": "Generar proceso nuevo"},
                {"nombre": "Escribir manifiesto modificado"},
                {"nombre": "Importar proceso"},
                {"nombre": "Compilar bloques"},
                {"nombre": "Refrescar BloqueCache"},
                {"nombre": "Componer respuesta"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # ZONA 3: estado entre ticks.
        self._plantillas_path: str = ""
        self._dir_plantilla_nombre: str = ""
        self._base_nueva: int = 0
        self._codigo_nuevo: str = ""
        self._nombre_nuevo: str = ""
        self._minimos_usuario: dict[str, int] = {}
        self._plc_name: str = ""
        self._plc_blocks_cache: list[dict[str, Any]] | None = None
        # Resultados intermedios de los 2 dispatches al worker OT.
        # ``_import_batch_result``: shape ``ok`` bool +
        # ``operations_executed`` int + ``details`` list (result del
        # ``execute_transactional_batch`` interno).
        self._import_batch_result: dict[str, Any] | None = None
        # ``_compile_result``: dict de ``compile_plc``.
        self._compile_result: dict[str, Any] | None = None
        # ProcProcessGenContext compartido entre los 9 ticks.
        self._ctx: ProcProcessGenContext | None = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar params + construir ``ProcProcessGenContext``.

        A diferencia del preview, este FB NECESITA ``tia_client``
        (obligatorio, lanza RuntimeError si es None) y ``plc_name``.
        ``plc_blocks_cache`` es opcional pero recomendado: si es None,
        el helper emite warning.
        """
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionProcCrearSincronizar requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )

        plantillas_path = params.get("plantillas_path", "")
        if not plantillas_path:
            raise ValueError(
                "FunctionProcCrearSincronizar.start(plantillas_path=...) "
                "es obligatorio"
            )
        dir_plantilla_nombre = params.get("dir_plantilla_nombre", "")
        if not dir_plantilla_nombre:
            raise ValueError(
                "FunctionProcCrearSincronizar.start("
                "dir_plantilla_nombre=...) es obligatorio"
            )
        base_nueva = params.get("base_nueva")
        if base_nueva is None or not isinstance(base_nueva, int):
            raise ValueError(
                "FunctionProcCrearSincronizar.start(base_nueva=int) "
                "es obligatorio"
            )
        codigo_nuevo = params.get("codigo_nuevo", "")
        if not codigo_nuevo:
            raise ValueError(
                "FunctionProcCrearSincronizar.start(codigo_nuevo=...) "
                "es obligatorio"
            )
        nombre_nuevo = params.get("nombre_nuevo", "")
        if not nombre_nuevo:
            raise ValueError(
                "FunctionProcCrearSincronizar.start(nombre_nuevo=...) "
                "es obligatorio"
            )
        minimos_usuario = params.get("minimos_usuario", {})
        if not isinstance(minimos_usuario, dict) or not minimos_usuario:
            raise ValueError(
                "FunctionProcCrearSincronizar.start(minimos_usuario=dict) "
                "es obligatorio (N_MAX_PREAL/PINT/ALM/ALM_HMI)"
            )
        plc_name = params.get("plc_name", "")
        if not plc_name:
            raise ValueError(
                "FunctionProcCrearSincronizar.start(plc_name=...) "
                "es obligatorio"
            )
        plc_blocks_cache = params.get("plc_blocks_cache")
        build_cache_root = params.get(
            "build_cache_root", self._build_cache_root
        )

        self._plantillas_path = str(plantillas_path)
        self._dir_plantilla_nombre = str(dir_plantilla_nombre)
        self._base_nueva = int(base_nueva)
        self._codigo_nuevo = str(codigo_nuevo)
        self._nombre_nuevo = str(nombre_nuevo)
        self._minimos_usuario = dict(minimos_usuario)
        self._plc_name = str(plc_name)
        self._plc_blocks_cache = (
            _coerce_plc_blocks_cache(plc_blocks_cache)
            if plc_blocks_cache is not None else None
        )

        dir_plantilla = Path(self._plantillas_path) / self._dir_plantilla_nombre
        if not dir_plantilla.exists():
            raise ValueError(
                f"No de la plantilla: {dir_plantilla}. "
                f"Verifica plantillas_path y dir_plantilla_nombre."
            )

        dir_plantilla_copia = (
            Path(build_cache_root) / "alimentacion" / "ProcesoNuevo" / "Plantilla"
        )
        dir_nuevo = (
            Path(build_cache_root) / "alimentacion" / "ProcesoNuevo" / "Nuevo"
        )

        # ``ProcProcessGenContext`` vive en este archivo (dataclass
        # local); acceso directo, sin import.
        self._ctx = ProcProcessGenContext(
            dir_plantilla=dir_plantilla,
            dir_plantilla_copia=dir_plantilla_copia,
            dir_nuevo=dir_nuevo,
            base_nueva=self._base_nueva,
            codigo_nuevo=self._codigo_nuevo,
            nombre_nuevo=self._nombre_nuevo,
            plc_blocks_cache=self._plc_blocks_cache,
            minimos_usuario=self._minimos_usuario,
        )

        logger.debug(
            f"[{self.nombre}] Aplicar crear proceso "
            f"{self._base_nueva}/{self._codigo_nuevo} en {self._plc_name} "
            f"desde {dir_plantilla}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al stage)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` al metodo ``_stage_N_*``."""
        if self._ctx is None:
            raise RuntimeError(
                "ProcProcessGenContext no inicializado. on_start() no se "
                "ejecuto (params invalidos o ausentes)."
            )

        step_nombre = self.steps[idx]["nombre"]
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                await handler()
                return _step_summary(self, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionProcCrearSincronizar"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que la SPA consume,
        incluyendo los resultados de los 2 dispatches al worker OT."""
        if self._ctx is None:
            self.result = {
                "success": False,
                "archivos_generados": [],
                "colisiones": [
                    "ProcProcessGenContext no inicializado. "
                    "Verifica los parametros del start()."
                ],
                "nuevo_dir": "",
                "manifest_plantilla": None,
                "process_label": "",
                "import_result": None,
                "compile_result": None,
            }
            return

        base_result = self._ctx.result
        # ``process_label``: ``"<base_nueva>_<codigo_nuevo>"`` del proceso
        # que se acaba de crear. La SPA lo lee para mostrar el mensaje
        # "Proceso XXXX creado correctamente" despues del apply OK.
        process_label = (
            f"{self._base_nueva}_{self._codigo_nuevo}"
        )
        self.result = {
            **base_result,
            "process_label": process_label,
            "import_result": self._import_batch_result,
            "compile_result": self._compile_result,
        }

        n_generados = len(base_result.get("archivos_generados", []))
        n_colisiones = len(base_result.get("colisiones", []))
        logger.debug(
            f"[{self.nombre}] Proceso {self._base_nueva}/"
            f"{self._codigo_nuevo} aplicado en {self._plc_name}: "
            f"{n_generados} archivos generados, "
            f"{n_colisiones} colision(es), compile="
            f"{'OK' if (self._compile_result or {}).get('ok') else 'FAIL'}"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 9 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Aqui el stage hace el trabajo inline llamando
    # a la funcion pura correspondiente (definida mas abajo) sobre
    # ``self._ctx``, o dispatch al worker OT (stages 7 y 8).
    # ==================================================================

    async def _stage_1_leer_manifest(self) -> None:
        """Stage 1: lee el ``manifest.json`` de la plantilla TIA."""
        await proc_process_leer_manifest(self._ctx)

    async def _stage_2_validar_minimos(self) -> None:
        """Stage 2: valida los N_MIN del operario contra la plantilla."""
        await proc_process_validar_minimos(self._ctx)

    async def _stage_3_copiar_a_preview(self) -> None:
        """Stage 3: copytree de la plantilla al workdir de preview."""
        await proc_process_copiar_a_preview(self._ctx)

    async def _stage_4_construir_diccionarios(self) -> None:
        """Stage 4: parsea bloques + XMLs y construye los diccionarios base."""
        await proc_process_construir_diccionarios(self._ctx)

    async def _stage_5_generar_proceso_nuevo(self) -> None:
        """Stage 5: aplica las reglas y materializa los archivos del proceso nuevo."""
        await proc_process_aplicar_clonacion(self._ctx)

    async def _stage_6_escribir_manifest_modified(self) -> None:
        """Stage 6: escribe el manifest.json en el workdir ``modified/``."""
        await proc_process_escribir_manifest(self._ctx)

    async def _stage_7_importar_proceso(self) -> None:
        """Stage 7: IMPORT bajo transaccion TIA unica (3 ops atomicas).

        3 ops en ``execute_transactional_batch``:
          1. import_plc_tags_xml sobre ``dir_nuevo/Variables PLC``.
          2. _wait 2s (sub-comando sync del handler
             ``_h_execute_transactional_batch`` que duerme sin tocar
             TIA, dando tiempo a consolidar entre el import de tags
             y el de bloques).
          3. import_blocks_sd sobre ``dir_nuevo/Bloques de programa``.

        Si cualquier op falla, TIA hace rollback atomico de las 3
        juntas, dejando el PLC en el mismo estado previo al apply.

        ORDEN CRITICO (sept-2026, validado en vivo): tags ANTES de
        blocks. Si invertimos, los bloques que referencian
        PlcUserConstant de la tag table fallan al compilar.

        REGLA (sept-2026): ``import_plc_tags_xml`` /
        ``import_blocks_sd`` se invocan SIN ``target_folder``
        (omitiendo el argumento); NUNCA pasar ``""``. Ver
        ``tia_handlers._h_import_block``.
        """
        batch_operations = [
            {
                "command": "import_plc_tags_xml",
                "args": {
                    "plc_name": self._plc_name,
                    "import_dir": str(
                        self._ctx.dir_nuevo / "Variables PLC"
                    ),
                },
            },
            {
                "command": "_wait",
                "args": {"seconds": TIA_CONSOLIDATION_SLEEP_S},
            },
            {
                "command": "import_blocks_sd",
                "args": {
                    "plc_name": self._plc_name,
                    "import_dir": str(
                        self._ctx.dir_nuevo / "Bloques de programa"
                    ),
                },
            },
        ]
        self._import_batch_result = await dispatch_async(
            self._tia_client,
            "execute_transactional_batch",
            {
                # ``undo_text`` especifico con el id del proceso
                # (base_codigo) para que el Undo de TIA Portal y el
                # dialog_text durante la transaccion sean trazables
                # al proceso concreto que se esta creando.
                "undo_text": (
                    f"Generando proceso "
                    f"{self._ctx.base_nueva}_{self._ctx.codigo_nuevo}"
                ),
                "operations": batch_operations,
            },
            timeout_s=600.0,
        )
        # CRITICO: si el batch fallo (rollback ejecutado), NO
        # continuar a ``compilar``. Si lo hicieramos, el compile
        # correria sobre el PLC sin cambios (rollback) y el FB
        # reportaria exito falso.
        if not self._import_batch_result.get("ok"):
            raise RuntimeError(
                f"execute_transactional_batch fallo: "
                f"{self._import_batch_result.get('error') or '<sin error>'}"
            )

    async def _stage_8_compilar(self) -> None:
        """Stage 8: dispatch ``compile_plc`` (fuera de transaccion)."""
        self._compile_result = await dispatch_async(
            self._tia_client,
            "compile_plc",
            {"plc_name": self._plc_name},
            timeout_s=600.0,
        )
        if not self._compile_result.get("ok"):
            raise RuntimeError(
                f"compile_plc fallo: "
                f"{self._compile_result.get('error') or '<sin error>'}"
            )

    async def _stage_9_refresh_cache(self) -> None:
        """Stage 9: reescanea el PLC y repuebla ``TIADataBloqueCache``.

        Tras el apply exitoso del nuevo proceso, el singleton del
        backend (``TIADataBloqueCache._caches[plc_name]``) contiene el
        snapshot anterior a la creacion. Sin este refresh, el siguiente
        preview/sync del proceso nuevo veria ``missing_blocks`` aunque
        los bloques ya existan en TIA, y el operario tendria que pulsar
        manualmente el boton ↻ del sidebar.

        Tolerancia a fallos: si el scan falla (TIA no responde, etc.),
        no abortamos el apply (ya fue exitoso). Loggeamos warning y el
        operario puede refrescar manualmente.
        """
        from core.infrastructure.tia.tia_cache import scan_plc_blocks
        try:
            await scan_plc_blocks(
                self._plc_name,
                force_refresh=True,
                tia_client=self._tia_client,
            )
            logger.debug(
                f"[{self.nombre}] BloqueCache refrescado para "
                f"'{self._plc_name}' tras apply "
                f"{self._base_nueva}/{self._codigo_nuevo}"
            )
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] Refresh de BloqueCache tras apply fallo: "
                f"{exc}. El operario puede refrescar manualmente con ↻ "
                "del sidebar."
            )

    async def _stage_10_build_response(self) -> None:
        """Stage 10: compone ``ctx.result`` con la shape final del apply."""
        await proc_process_done_summary(self._ctx)


# ============================================================================
# Codigo absorbido de helpers/proc/proc_crear_process_generator.py
# (commit F22-2, sept-2026). Antes era un orquestador separado que el FB
# llamaba via ``match step_nombre``. Ahora los 9 stages viven como
# metodos del FB (mutando ``self._ctx``); las funciones puras del pipeline
# (filesystem puro, sin TIA) viven aqui mismo, debajo del dataclass.
#
# Las 7 funciones puras del preview (leer_manifest, validar_minimos,
# copiar_a_preview, construir_diccionarios, detectar_colisiones,
# generar_previstos, done_summary) viven en el archivo del FB preview
# (``function_proc_crear_generar_preview``) — duplicadas aqui las que
# el apply necesita (leer_manifest, validar_minimos, copiar_a_preview,
# construir_diccionarios, done_summary) para autonomia. Aqui van las
# que SOLO usa el apply: aplicar_clonacion, escribir_manifest.
# ============================================================================


async def proc_process_leer_manifest(ctx: ProcProcessGenContext) -> None:
    """Lee ``manifest.json`` y popula ``ctx.{manifest_plantilla,
    base_vieja, codigo_viejo, nombre_viejo}``.

    Copia local del helper en ``function_proc_crear_generar_preview``
    (autonomia del FB; cualquier cambio debe replicarse).
    """
    manifest_path = ctx.dir_plantilla / "manifest.json"
    if not manifest_path.exists():
        raise ManifestInvalido(
            f"No se encontro manifest.json en: {ctx.dir_plantilla}"
        )

    try:
        manifest_text = await asyncio.to_thread(
            manifest_path.read_text, encoding="utf-8"
        )
        manifest = json.loads(manifest_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestInvalido(f"manifest.json invalido: {exc}") from exc

    if "base" not in manifest or not isinstance(manifest["base"], int):
        raise ManifestInvalido("manifest.json debe contener 'base' (int).")
    if "codigo" not in manifest or not str(manifest["codigo"]).strip():
        raise ManifestInvalido("manifest.json debe contener 'codigo' (str).")

    ctx.manifest_plantilla = manifest
    ctx.base_vieja = int(manifest["base"])
    ctx.codigo_viejo = str(manifest["codigo"])
    ctx.nombre_viejo = str(manifest.get("nombre", "") or "")


async def proc_process_validar_minimos(ctx: ProcProcessGenContext) -> None:
    """Valida que los N_MAX del operario cubran los minimos de la plantilla."""
    if ctx.manifest_plantilla is None:
        raise RuntimeError("Requiere proc_process_leer_manifest previo.")

    minimos_plantilla = ctx.manifest_plantilla.get("minimos", {}) or {}
    problemas: list[str] = []

    for key in N_MAX_KEYS:
        plantilla_val = int(minimos_plantilla.get(key, 0))
        usuario_val = int(ctx.minimos_usuario.get(key, 0))
        if usuario_val < plantilla_val:
            problemas.append(
                f"{key}: usuario={usuario_val} < plantilla={plantilla_val}"
            )

    if problemas:
        raise PlantillaMinimosNoCumplidos(
            "Los N_MAX del operario no cubren los minimos de la plantilla:\n"
            "  - " + "\n  - ".join(problemas)
        )


async def proc_process_copiar_a_preview(ctx: ProcProcessGenContext) -> None:
    """Copia ``dir_plantilla`` a ``dir_plantilla_copia`` (stage 3)."""
    if ctx.dir_plantilla_copia.exists():
        await asyncio.to_thread(shutil.rmtree, ctx.dir_plantilla_copia)
    await asyncio.to_thread(
        shutil.copytree,
        ctx.dir_plantilla,
        ctx.dir_plantilla_copia,
        dirs_exist_ok=False,
    )


async def proc_process_construir_diccionarios(ctx: ProcProcessGenContext) -> None:
    """Construye los diccionarios de renombrado (stage 4).

    Copia local del helper en ``function_proc_crear_generar_preview``.
    Estrategia completa (bloques + variables + metadatos + fallbacks)
    documentada alli.
    """
    base_viej = ctx.base_vieja
    base_nuev = ctx.base_nueva
    cod_viej = ctx.codigo_viejo
    cod_nuev = ctx.codigo_nuevo
    nom_viej = ctx.nombre_viejo
    nom_nuev = ctx.nombre_nuevo

    dicc_bloques: dict[str, str] = {}
    dicc_xml: dict[str, str] = {}
    numeros_usados: set[int] = set()

    patron_bloques = re.compile(r"(FC|FB|DB)(\d+)")

    def _walk_and_build() -> None:
        for item in ctx.dir_plantilla_copia.rglob("*"):
            if not item.exists():
                continue
            nombre_base = item.stem if item.is_file() else item.name

            def _repl_bloque(m: re.Match[str]) -> str:
                prefijo = m.group(1)
                num_viejo = int(m.group(2))
                num_nuevo = num_viejo - base_viej + base_nuev
                return f"{prefijo}{num_nuevo}"

            nuevo_nombre_base = patron_bloques.sub(_repl_bloque, nombre_base)

            if cod_viej:
                nuevo_nombre_base = nuevo_nombre_base.replace(cod_viej, cod_nuev)
            if nom_viej and nom_nuev:
                nuevo_nombre_base = nuevo_nombre_base.replace(nom_viej, nom_nuev)

            if nombre_base != nuevo_nombre_base:
                dicc_bloques[nombre_base] = nuevo_nombre_base

            for match in patron_bloques.finditer(nombre_base):
                numeros_usados.add(int(match.group(2)))

    await asyncio.to_thread(_walk_and_build)

    bases_viejas = [base_viej, base_viej + 3000, base_viej + 5000]
    bases_nuevas = [base_nuev, base_nuev + 3000, base_nuev + 5000]
    for b_vieja, b_nueva in zip(bases_viejas, bases_nuevas):
        regla_vieja = f"{b_vieja}_"
        regla_nueva = f"{b_nueva}_"
        dicc_xml[regla_vieja] = regla_nueva
        dicc_bloques[regla_vieja] = regla_nueva

    for num in numeros_usados:
        nuevo_num = num - base_viej + base_nuev
        dicc_bloques[f'S7_BlockNumber := "{num}"'] = (
            f'S7_BlockNumber := "{nuevo_num}"'
        )

    if cod_viej:
        dicc_xml[cod_viej] = cod_nuev
        dicc_bloques[cod_viej] = cod_nuev
    if nom_viej and nom_nuev:
        dicc_xml[nom_viej] = nom_nuev
        dicc_bloques[nom_viej] = nom_nuev

    ctx.dicc_bloques = dict(
        sorted(dicc_bloques.items(), key=lambda x: len(x[0]), reverse=True)
    )
    ctx.dicc_xml = dict(
        sorted(dicc_xml.items(), key=lambda x: len(x[0]), reverse=True)
    )


async def proc_process_aplicar_clonacion(ctx: ProcProcessGenContext) -> None:
    """Aplica la clonacion: ``dir_plantilla_copia`` -> ``dir_nuevo``.

    Borra ``dir_nuevo/`` antes de aplicar (regla de retencion: cada
    apply parte limpio).

    Pipeline:
      1. ``shutil.copytree(dir_plantilla_copia, dir_nuevo,
         ignore=manifest)``: copia bulk preservando la estructura de
         carpetas.
      2. Walk de ``dir_nuevo``: para cada path (file O folder) se
         aplica el rename al nombre del componente aplicando
         ``_aplicar_diccionario(nombre, dicc_bloques)``.
      3. Walk final para rewrite de contenido segun extension.

    Por extension (paso 3):
      - ``.s7res``:           ``dicc_bloques``, encoding utf-8-sig.
      - ``.xml``:             ``dicc_xml``, encoding utf-8 (con
                              override de N_MAX si el XML contiene
                              PlcUserConstant).
      - ``.s7dcl``/``.scl``/``.awl``: ``dicc_bloques``, encoding utf-8.
      - Resto (binarios):     sin tocar (ya copiados por copytree).

    ``manifest.json`` se excluye via el ``ignore`` de copytree (lo
    regenera ``proc_process_escribir_manifest`` justo despues).

    Para los renames de folder, se procesan en orden de profundidad
    DESCENDENTE (mas profundo primero) para no romper paths de hijos
    cuando movemos el padre.
    """
    if ctx.dir_nuevo.exists():
        await asyncio.to_thread(shutil.rmtree, ctx.dir_nuevo)

    def _ignore_manifest(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n == "manifest.json"]

    await asyncio.to_thread(
        shutil.copytree,
        str(ctx.dir_plantilla_copia),
        str(ctx.dir_nuevo),
        ignore=_ignore_manifest,
    )

    def _rename_paths() -> None:
        renames: list[tuple[Path, Path]] = []
        for path in list(ctx.dir_nuevo.rglob("*")):
            if path == ctx.dir_nuevo:
                continue
            if path.is_file():
                suffix = path.suffix.lower()
                nuevo_stem = _aplicar_diccionario(
                    path.stem, ctx.dicc_bloques
                )
                new_name = f"{nuevo_stem}{suffix}"
            else:
                new_name = _aplicar_diccionario(
                    path.name, ctx.dicc_bloques
                )
            if path.name != new_name:
                renames.append((path, path.with_name(new_name)))

        renames.sort(key=lambda pair: -len(pair[0].parts))
        for old, new in renames:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)

    await asyncio.to_thread(_rename_paths)

    def _rewrite_contents() -> list[str]:
        generated: list[str] = []
        for path in ctx.dir_nuevo.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".s7res":
                enc = "utf-8-sig"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
                _escribir_texto(path, nuevo, enc)
            elif suffix == ".xml":
                enc = "utf-8"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_xml)
                if "PlcUserConstant" in nuevo and ctx.minimos_usuario:
                    nuevo = _reemplazar_nmax_en_xml(
                        nuevo, ctx.base_nueva, ctx.minimos_usuario
                    )
                _escribir_texto(path, nuevo, enc)
            elif suffix in (".s7dcl", ".scl", ".awl"):
                enc = "utf-8"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
                _escribir_texto(path, nuevo, enc)

            generated.append(str(path.relative_to(ctx.dir_nuevo)))
        return generated

    ctx.archivos_generados = await asyncio.to_thread(_rewrite_contents)


async def proc_process_escribir_manifest(ctx: ProcProcessGenContext) -> None:
    """Escribe ``<dir_nuevo>/manifest.json`` con los datos del
    proceso nuevo (usa la plantilla como base, override con
    ``base_nueva/codigo/nombre/minimos`` del ctx).
    """
    ctx.dir_nuevo.mkdir(parents=True, exist_ok=True)
    manifest_path = ctx.dir_nuevo / "manifest.json"
    payload = {
        "base": ctx.base_nueva,
        "codigo": ctx.codigo_nuevo,
        "nombre": ctx.nombre_nuevo,
        "minimos": dict(ctx.minimos_usuario),
    }

    def _write() -> None:
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )

    await asyncio.to_thread(_write)
    ctx.archivos_generados.append("manifest.json")


async def proc_process_done_summary(ctx: ProcProcessGenContext) -> dict[str, Any]:
    """Compone ``ctx.result`` con la shape que el FB vuelca a
    ``self.result``.

    Diferencia preview vs apply:
      - preview (``archivos_previstos`` poblado) -> vuelca la lista de
        previstos + el ``plantilla_copia_dir``.
      - apply (``archivos_generados`` poblado) -> vuelca la lista de
        generados + el ``nuevo_dir``.

    ``success=True`` solo si no hubo colisiones.
    """
    if ctx.archivos_generados:
        dir_salida = ctx.dir_nuevo
        archivos = list(ctx.archivos_generados)
        campo_archivos = "archivos_generados"
    else:
        dir_salida = ctx.dir_plantilla_copia
        archivos = list(ctx.archivos_previstos)
        campo_archivos = "archivos_previstos"

    success = len(ctx.colisiones) == 0
    ctx.result = {
        "manifest_plantilla": ctx.manifest_plantilla,
        campo_archivos: archivos,
        "colisiones": list(ctx.colisiones),
        (
            "plantilla_copia_dir"
            if campo_archivos == "archivos_previstos"
            else "nuevo_dir"
        ): str(dir_salida),
        "success": success,
    }
    return ctx.result


# ============================================================================
# Helpers internos (sync).
# ============================================================================


def _aplicar_diccionario(texto: str, dicc: dict[str, str]) -> str:
    """Aplica los reemplazos en cascada."""
    for viejo, nuevo in dicc.items():
        texto = texto.replace(viejo, nuevo)
    return texto


def _leer_texto(path: Path, encoding: str) -> str:
    """Lee texto con fallback latin-1 si utf-8 falla (caso TIA V21)."""
    try:
        with open(path, "r", encoding=encoding, newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1", newline="") as f:
            return f.read()


def _escribir_texto(path: Path, contenido: str, encoding: str) -> None:
    """Escribe texto preservando retornos de carro (``newline=""``)."""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(contenido)


def _reemplazar_nmax_en_xml(
    contenido: str,
    base_nueva: int,
    minimos_usuario: dict[str, int],
) -> str:
    """Sustituye los ``<Value>`` de las constantes N_MAX del proceso
    nuevo de forma segura, vinculandolos a su ``<Name>``.

    Asume que ``contenido`` ya paso por ``_aplicar_diccionario(contenido,
    dicc_xml)``, asi ``<Name>{base_nueva}_{N_MAX_KEY}</Name>`` esta
    presente en el XML destino.
    """
    for key in N_MAX_KEYS:
        val_usuario = minimos_usuario.get(key)
        if val_usuario is None:
            continue

        patron = rf"(<Name>{base_nueva}_{key}</Name>.*?<Value>)(\d+)(</Value>)"
        contenido = re.sub(
            patron,
            lambda m: f"{m.group(1)}{val_usuario}{m.group(3)}",
            contenido,
            flags=re.DOTALL,
        )
    return contenido


def _step_summary(fb: "FunctionProcCrearSincronizar", step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    ctx = fb._ctx  # noqa: SLF001 (mismo patron que FunctionProcSincronizar)
    if step_nombre == "leer_manifest":
        if ctx is None or ctx.manifest_plantilla is None:
            return f"{step_nombre}: sin manifest"
        return f"{step_nombre}: base={ctx.base_vieja} codigo={ctx.codigo_viejo}"
    if step_nombre == "validar_minimos":
        return f"{step_nombre}: N_MAX OK"
    if step_nombre == "copiar_a_preview":
        if ctx is None:
            return f"{step_nombre}: sin ctx"
        return f"{step_nombre}: plantilla copiada a {ctx.dir_plantilla_copia}"
    if step_nombre == "construir_diccionarios":
        if ctx is None:
            return f"{step_nombre}: sin ctx"
        return (
            f"{step_nombre}: "
            f"{len(ctx.dicc_bloques)} reglas bloques + "
            f"{len(ctx.dicc_xml)} reglas XML"
        )
    if step_nombre == "generar_proceso_nuevo":
        if ctx is None:
            return f"{step_nombre}: sin ctx"
        return (
            f"{step_nombre}: {len(ctx.archivos_generados)} archivos clonados"
        )
    if step_nombre == "escribir_manifest_modified":
        return f"{step_nombre}: manifest OK"
    if step_nombre == "importar_proceso":
        batch = fb._import_batch_result  # noqa: SLF001
        if not batch:
            return f"{step_nombre}: FAIL (sin respuesta del lote)"
        if not batch.get("ok"):
            err = batch.get("error") or "<sin detalle>"
            return f"{step_nombre}: FAIL ({err[:80]})"
        inner = batch.get("result") or {}
        ok = bool(inner.get("success"))
        n_ops = inner.get("operations_executed", "?")
        return f"{step_nombre}: {'OK' if ok else 'FAIL'} ({n_ops} ops)"
    if step_nombre == "compilar":
        ok = fb._compile_result is not None and fb._compile_result.get("ok")  # noqa: SLF001
        return f"{step_nombre}: {'OK' if ok else 'FAIL'}"
    if step_nombre == "done":
        return f"{step_nombre}: apply compuesto"
    return f"{step_nombre}: OK"


def _coerce_plc_blocks_cache(raw: Any) -> list[dict[str, Any]]:
    """Normaliza ``plc_blocks_cache`` a ``list[dict{nombre, numero}]``."""
    out: list[dict[str, Any]] = []
    if isinstance(raw, (list, tuple, set, frozenset)):
        for item in raw:
            if isinstance(item, dict):
                nombre = item.get("nombre") or item.get("name") or ""
                numero = item.get("numero")
                out.append({"nombre": str(nombre), "numero": numero})
            elif isinstance(item, str) and item:
                out.append({"nombre": item, "numero": None})
    elif isinstance(raw, str) and raw:
        out.append({"nombre": raw, "numero": None})
    return out


__all__ = [
    "EXTENSIONES_TEXTO",
    "ManifestInvalido",
    "N_MAX_KEYS",
    "PlantillaMinimosNoCumplidos",
    "ProcProcessGenContext",
    "TIA_CONSOLIDATION_SLEEP_S",
    "FunctionProcCrearSincronizar",
    "_coerce_plc_blocks_cache",
    "_step_summary",
    # Funciones puras absorbidas (F22-2).
    "proc_process_leer_manifest",
    "proc_process_validar_minimos",
    "proc_process_copiar_a_preview",
    "proc_process_construir_diccionarios",
    "proc_process_aplicar_clonacion",
    "proc_process_escribir_manifest",
    "proc_process_done_summary",
    # Helpers internos (puros).
    "_aplicar_diccionario",
    "_leer_texto",
    "_escribir_texto",
    "_reemplazar_nmax_en_xml",
]
