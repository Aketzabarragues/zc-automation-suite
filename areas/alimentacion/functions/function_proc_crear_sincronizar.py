"""FB de area: aplicar la clonacion de un proceso desde plantilla.

State machine sobre el helper ``proc_crear_process_generator``
(``areas/alimentacion/helpers/proc/proc_crear_process_generator.py``) +
un dispatch al worker OT (``execute_transactional_batch`` que
ejecuta 3 ops bajo una sola transaccion TIA: import tag table,
wait 2s, import bloques) y un compile del PLC.

Si el lote transaccional falla, TIA hace rollback atomico de las
3 ops juntas, dejando el PLC en el mismo estado previo al apply.

NOTA sobre el ``CommitOnDispose`` que vimos en sept-2026: tras
los fixes ``dde011d`` (target_folder="") y ``6bb0aec`` (subdir
especifico en lugar de raiz), re-introducimos el lote para tener
rollback atomico entre tags y blocks. Si TIA V21 sigue marcando
la transaccion como corrupta, se volveria a la version
secuencial (commit 3baad2b).

Hereda directo de ``FunctionBase``.

Restricciones CRITICAS del dispatch al worker OT (sept-2026):
  - ``import_plc_tags_xml`` / ``import_blocks_sd`` distinguen entre
    ``target_folder_path=None`` (default, NO pasar el argumento; TIA
    hace match UPDATE recursivo preservando el subpath del archivo
    dentro del ``import_dir``) y ``target_folder_path=""`` (string
    vacio explicito; TIA intenta CREATE y falla con "Import failed
    because an object with the name X already exists in the plc").
  - Por eso en este FB NUNCA pasamos ``target_folder`` — lo omitimos
    para que el handler use el default ``None`` y TIA haga UPDATE
    correcto. Ver ``tia_handlers._h_import_block`` para detalle.

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
    El helper cruza por NOMBRE O por NUMERO contra los bloques
    post-rename. Si es None, el helper emite warning y el FB aborta.
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
  - leer_manifest             -> helper.proc_process_leer_manifest
  - validar_minimos           -> helper.proc_process_validar_minimos
  - copiar_a_preview          -> helper.proc_process_copiar_a_preview
  - construir_diccionarios    -> helper.proc_process_construir_diccionarios
  - generar_proceso_nuevo     -> helper.proc_process_aplicar_clonacion
  - escribir_manifest_modified-> helper.proc_process_escribir_manifest
  - importar_proceso          -> dispatch_async("execute_transactional_batch")
                                con 3 ops bajo transaccion TIA:
                                (1) import_plc_tags_xml,
                                (2) _wait 2s (sub-comando que duerme
                                    localmente sin tocar TIA, dentro
                                    del handler transaccional),
                                (3) import_blocks_sd
                                Si cualquier op falla, TIA hace rollback
                                de las 3 juntas.
  - compilar                  -> dispatch_async("compile_plc") (fuera de
                                transaccion; TIA compila todos los
                                cambios pendientes del PLC).
  - done                      -> vuelco ``ctx.result`` a ``self.result``
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async
from areas.alimentacion.helpers.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)

# Mismo sleep que usan ``proc_sincronizar.wait_consolidation`` y
# ``disp_Sincronizar.wait_consolidation`` tras un import masivo. TIA
# necesita consolidar internamente antes de aceptar un segundo import.
# Aqui el sleep vive DENTRO del handler
# ``_h_execute_transactional_batch`` (sub-comando ``_wait``), no en el
# FB — el FB solo lo declara como op del lote.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


class FunctionProcCrearSincronizar(FunctionBase):
    """FB que clona un proceso desde plantilla TIA y lo importa al PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # 2 dispatches al worker OT (1 lote transaccional + 1 compile).
    # En PLCs grandes el import masivo puede tardar 1-3 min, el compile
    # hasta 5 min. 600s cubre holgadamente.
    STEP_TIMEOUT_S: float = 600.0

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
        (1, "Leer manifiesto",             "_stage_1_leer_manifest"),
        (2, "Validar mínimos",             "_stage_2_validar_minimos"),
        (3, "Copiar a vista previa",       "_stage_3_copiar_a_preview"),
        (4, "Construir diccionarios",      "_stage_4_construir_diccionarios"),
        (5, "Generar proceso nuevo",       "_stage_5_generar_proceso_nuevo"),
        (6, "Escribir manifiesto modificado", "_stage_6_escribir_manifest_modified"),
        (7, "Importar proceso",            "_stage_7_importar_proceso"),
        (8, "Compilar bloques",            "_stage_8_compilar"),
        (9, "Componer respuesta",          "_stage_9_build_response"),
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
        # Resultados intermedios de los dispatches (3 ops: tags + wait +
        # blocks, todas ejecutadas secuencialmente fuera de transaccion
        # TIA por el quirk CommitOnDispose del V21).
        # ``_import_batch_result``: shape legacy
        # (``ok`` bool, ``operations_executed`` int, ``details`` list)
        # poblado por compat con consumers que leen ``self.result``.
        self._import_batch_result: dict[str, Any] | None = None
        # ``_compile_result``: dict de ``compile_plc`` (con ``ok`` bool).
        self._compile_result: dict[str, Any] | None = None
        # ProcProcessGenContext compartido entre los 11 ticks.
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar params + construir ``ProcProcessGenContext``.

        A diferencia del preview, este FB NECESITA ``tia_client``
        (obligatorio, lanza RuntimeError si es None) y ``plc_name``.
        ``plc_blocks_cache`` es opcional pero recomendado: si es None,
        el helper emite warning; si hay colisiones, el FB aborta en
        ``detectar_colisiones`` (que SI se llama en este FB).
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
        # ``plc_blocks_cache``: shape preferida ``list[dict{nombre,
        # numero}]``. Defensivo: aceptar ``set[str]`` / ``list[str]``
        # legacy convirtiendolo a ``[{"nombre": s, "numero": None}]``.
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

        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc.proc_crear_process_generator import (
            ProcProcessGenContext,
        )
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
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper o al
        worker OT."""
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc import proc_crear_process_generator

        if self._ctx is None:
            raise RuntimeError(
                "ProcProcessGenContext no inicializado. on_start() no se "
                "ejecuto (params invalidos o ausentes)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los 9 stages se declaran arriba de la clase. Asi
        # el flujo del FB es visible de un vistazo (modo SFC) y los
        # tests pueden mockear ``fb._stage_N_<nombre>`` directamente sin
        # parchear el ``match`` interno.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 3/9").
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
        # "Proceso XXXX creado correctamente" despues del apply OK
        # (sept-2026: antes solo tenia ``props.procUid`` y el mensaje
        # era generico). Tambien sirve para logging trazable.
        process_label = (
            f"{self._base_nueva}_{self._codigo_nuevo}"
        )
        # ``import_result`` es el dict crudo de
        # ``execute_transactional_batch`` (``success``,
        # ``operations_executed``, ``details``). La SPA solo lo
        # muestra como badge, no inspecciona campos internos.
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
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien. Aqui viven como wrappers que delegan en las
    # funciones puras de ``proc_crear_process_generator`` o en dispatchs al
    # worker OT.
    # ==================================================================

    async def _stage_1_leer_manifest(self) -> None:
        """Stage 1: lee el ``manifest.json`` de la plantilla TIA."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_leer_manifest(self._ctx)

    async def _stage_2_validar_minimos(self) -> None:
        """Stage 2: valida los N_MIN del operario contra la plantilla."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_validar_minimos(self._ctx)

    async def _stage_3_copiar_a_preview(self) -> None:
        """Stage 3: copytree de la plantilla al workdir de preview."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_copiar_a_preview(self._ctx)

    async def _stage_4_construir_diccionarios(self) -> None:
        """Stage 4: parsea bloques + XMLs y construye los diccionarios base."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_construir_diccionarios(self._ctx)

    async def _stage_5_generar_proceso_nuevo(self) -> None:
        """Stage 5: aplica las reglas y materializa los archivos del proceso nuevo."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_aplicar_clonacion(self._ctx)

    async def _stage_6_escribir_manifest_modified(self) -> None:
        """Stage 6: escribe el manifest.json en el workdir ``modified/``."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_escribir_manifest(self._ctx)

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
        PlcUserConstant de la tag table fallan al compilar
        (``OpennessAccessException``).

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
                # al proceso concreto que se esta creando
                # (sept-2026: antes era generico "Generar proceso
                # desde plantilla" y no se podia saber a que proceso
                # correspondia).
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
        # reportaria exito falso. Ademas, si el PLC quedo en estado
        # "corrupto" por la transaccion TIA fallida, el compile puede
        # hangear o fallar de forma confusa.
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

    async def _stage_9_build_response(self) -> None:
        """Stage 9: compone ``ctx.result`` con la shape final del apply."""
        from areas.alimentacion.helpers.proc import proc_crear_process_generator
        await proc_crear_process_generator.proc_process_done_summary(self._ctx)


def _coerce_plc_blocks_cache(raw: Any) -> list[dict[str, Any]]:
    """Normaliza ``plc_blocks_cache`` a ``list[dict{nombre, numero}]``.

    Acepta las 3 shapes que pueden llegar al FB:
      - ``list[dict]`` (shape preferida; el dict tiene al menos
        ``nombre`` y opcionalmente ``numero``).
      - ``list[str]`` / ``set[str]`` (legacy: solo nombres). Se
        convierte a ``[{"nombre": s, "numero": None}]``.

    Items invalidos (None, tipos raros) se descartan silenciosamente.
    """
    out: list[dict[str, Any]] = []
    if isinstance(raw, (list, tuple, set, frozenset)):
        for item in raw:
            if isinstance(item, dict):
                # Aceptar tanto "nombre" como "name" (compat scanner).
                nombre = item.get("nombre") or item.get("name") or ""
                numero = item.get("numero")
                out.append({"nombre": str(nombre), "numero": numero})
            elif isinstance(item, str) and item:
                out.append({"nombre": item, "numero": None})
    elif isinstance(raw, str) and raw:
        out.append({"nombre": raw, "numero": None})
    return out


def _step_summary(fb: FunctionProcCrearSincronizar, step_nombre: str) -> str:
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
        # Dispatch async devuelve ``{ok: True, result: <batch>}`` o
        # ``{ok: False, error: str}``. El batch interno tiene
        # ``success`` / ``operations_executed`` / ``details``. Hay
        # que mirar las claves correctas (no las del dispatch wrapper)
        # para que el summary muestre OK en lugar de FAIL.
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


__all__ = ["FunctionProcCrearSincronizar", "_coerce_plc_blocks_cache"]