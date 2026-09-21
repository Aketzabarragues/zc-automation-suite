"""FB de area: aplicar la clonacion de un proceso desde plantilla.

State machine sobre el helper ``proc_process_generator``
(``areas/alimentacion/helpers/proc/proc_process_generator.py``) + 5
dispatches al worker OT para importar la tabla de variables
modificada, los bloques ``.s7dcl`` clonados y compilar el PLC.

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
  - ``plc_blocks_cache`` (set[str] | None): nombres de bloques
    existentes en el PLC. Se cruza por NOMBRE unico. Si None, el
    helper emite warning y el FB aborta (no podemos asegurar UPDATE
    seguro).
  - ``build_cache_root`` (Path): raiz del BuildCache del area.

El ``self.result`` se popula con la shape esperada por la SPA::

    {
      "manifest_plantilla": dict | None,
      "archivos_generados": list[str],
      "colisiones":         list[str],
      "nuevo_dir":          str,
      "success":            bool,
      "import_result":      dict | None,
      "compile_result":      dict | None,
    }

Steps (13):
  - leer_manifest             -> helper.proc_process_leer_manifest
  - validar_minimos           -> helper.proc_process_validar_minimos
  - copiar_a_preview          -> helper.proc_process_copiar_a_preview
  - construir_diccionarios    -> helper.proc_process_construir_diccionarios
  - aplicar_clonacion_strict  -> helper.proc_process_aplicar_clonacion
  - escribir_manifest_modified-> helper.proc_process_escribir_manifest
  - import_tag_table          -> dispatch_async("import_plc_tags_xml")
  - wait_consolidation        -> sleep 2s para que TIA consolide
  - import_blocks_dbs         -> dispatch_async("import_blocks_sd")
  - import_blocks_logicos     -> dispatch_async("import_blocks_sd")
  - compile_plc               -> dispatch_async("compile_plc")
  - done                      -> vuelco ``ctx.result`` a ``self.result``
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async

logger = logging.getLogger(__name__)

# Mismo sleep que usan ``proc_sincronizar.wait_consolidation`` y
# ``disp_Sincronizar.wait_consolidation`` tras un import masivo. TIA
# necesita consolidar internamente antes de aceptar un compile.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


class FunctionProcProcessCrearAplicar(FunctionBase):
    """FB que clona un proceso desde plantilla TIA y lo importa al PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # 5 dispatches al worker OT (3 imports + 1 compile, mas un sleep
    # de consolidacion). En PLCs grandes el import masivo puede
    # tardar 1-3 min, el compile hasta 5 min. 600s cubre holgadamente.
    STEP_TIMEOUT_S: float = 600.0

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
                {"nombre": "leer_manifest"},
                {"nombre": "validar_minimos"},
                {"nombre": "copiar_a_preview"},
                {"nombre": "construir_diccionarios"},
                {"nombre": "aplicar_clonacion_strict"},
                {"nombre": "escribir_manifest_modified"},
                {"nombre": "import_tag_table"},
                {"nombre": "wait_consolidation"},
                {"nombre": "import_blocks_dbs"},
                {"nombre": "import_blocks_logicos"},
                {"nombre": "compile_plc"},
                {"nombre": "done"},
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
        # ZONA 3: estado entre ticks.
        self._plantillas_path: str = ""
        self._dir_plantilla_nombre: str = ""
        self._base_nueva: int = 0
        self._codigo_nuevo: str = ""
        self._nombre_nuevo: str = ""
        self._minimos_usuario: dict[str, int] = {}
        self._plc_name: str = ""
        self._plc_blocks_cache: set[str] | None = None
        # Resultados intermedios de los dispatches.
        self._import_tag_result: dict[str, Any] | None = None
        self._import_blocks_dbs_result: dict[str, Any] | None = None
        self._import_blocks_logicos_result: dict[str, Any] | None = None
        self._compile_result: dict[str, Any] | None = None
        # ProcProcessGenContext compartido entre los 13 ticks.
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
                "FunctionProcProcessCrearAplicar requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )

        plantillas_path = params.get("plantillas_path", "")
        if not plantillas_path:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(plantillas_path=...) "
                "es obligatorio"
            )
        dir_plantilla_nombre = params.get("dir_plantilla_nombre", "")
        if not dir_plantilla_nombre:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start("
                "dir_plantilla_nombre=...) es obligatorio"
            )
        base_nueva = params.get("base_nueva")
        if base_nueva is None or not isinstance(base_nueva, int):
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(base_nueva=int) "
                "es obligatorio"
            )
        codigo_nuevo = params.get("codigo_nuevo", "")
        if not codigo_nuevo:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(codigo_nuevo=...) "
                "es obligatorio"
            )
        nombre_nuevo = params.get("nombre_nuevo", "")
        if not nombre_nuevo:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(nombre_nuevo=...) "
                "es obligatorio"
            )
        minimos_usuario = params.get("minimos_usuario", {})
        if not isinstance(minimos_usuario, dict) or not minimos_usuario:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(minimos_usuario=dict) "
                "es obligatorio (N_MAX_PREAL/PINT/ALM/ALM_HMI)"
            )
        plc_name = params.get("plc_name", "")
        if not plc_name:
            raise ValueError(
                "FunctionProcProcessCrearAplicar.start(plc_name=...) "
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
            set(plc_blocks_cache) if plc_blocks_cache is not None else None
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
        from areas.alimentacion.helpers.proc.proc_process_generator import (
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
        from areas.alimentacion.helpers.proc import proc_process_generator

        if self._ctx is None:
            raise RuntimeError(
                "ProcProcessGenContext no inicializado. on_start() no se "
                "ejecuto (params invalidos o ausentes)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "leer_manifest":
                await proc_process_generator.proc_process_leer_manifest(
                    self._ctx
                )
            case "validar_minimos":
                await proc_process_generator.proc_process_validar_minimos(
                    self._ctx
                )
            case "copiar_a_preview":
                await proc_process_generator.proc_process_copiar_a_preview(
                    self._ctx
                )
            case "construir_diccionarios":
                await proc_process_generator.proc_process_construir_diccionarios(
                    self._ctx
                )
            case "aplicar_clonacion_strict":
                await proc_process_generator.proc_process_aplicar_clonacion(
                    self._ctx
                )
            case "escribir_manifest_modified":
                await proc_process_generator.proc_process_escribir_manifest(
                    self._ctx
                )
            case "import_tag_table":
                # REGLA CRITICA (sept-2026): pasamos ``target_folder=None``
                # (omitiendo el argumento). NUNCA ``""``. Ver
                # ``tia_handlers._h_import_block`` para el detalle del bug.
                self._import_tag_result = await dispatch_async(
                    self._tia_client,
                    "import_plc_tags_xml",
                    {
                        "plc_name": self._plc_name,
                        "import_dir": str(
                            self._ctx.dir_nuevo / "variables"
                        ),
                    },
                    timeout_s=600.0,
                )
            case "wait_consolidation":
                # Sleep 2s para que TIA consolide internamente antes
                # del compile. Patron paralelo a
                # ``proc_sincronizar.wait_consolidation``.
                await asyncio.sleep(TIA_CONSOLIDATION_SLEEP_S)
            case "import_blocks_dbs":
                self._import_blocks_dbs_result = await dispatch_async(
                    self._tia_client,
                    "import_blocks_sd",
                    {
                        "plc_name": self._plc_name,
                        "import_dir": str(
                            self._ctx.dir_nuevo / "bloques"
                        ),
                    },
                    timeout_s=600.0,
                )
            case "import_blocks_logicos":
                # Mismo handler ``import_blocks_sd`` que ``dbs``: TIA
                # escanea recursivamente ``bloques/`` y matchea UPDATE
                # por nombre de bloque preservando el subpath. No hace
                # falta distinguir "DB" vs "FC" en el handler; el
                # ``import_dir`` ya esta filtrado a ``bloques/``.
                self._import_blocks_logicos_result = await dispatch_async(
                    self._tia_client,
                    "import_blocks_sd",
                    {
                        "plc_name": self._plc_name,
                        "import_dir": str(
                            self._ctx.dir_nuevo / "bloques"
                        ),
                    },
                    timeout_s=600.0,
                )
            case "compile_plc":
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
            case "done":
                await proc_process_generator.proc_process_done_summary(self._ctx)
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        return _step_summary(self, step_nombre)

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que la SPA consume,
        incluyendo los resultados de los 4 dispatches al worker OT."""
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
                "import_result": None,
                "compile_result": None,
            }
            return

        base_result = self._ctx.result
        self.result = {
            **base_result,
            "import_result": {
                "tag_table": self._import_tag_result,
                "blocks_dbs": self._import_blocks_dbs_result,
                "blocks_logicos": self._import_blocks_logicos_result,
            },
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


def _step_summary(fb: FunctionProcProcessCrearAplicar, step_nombre: str) -> str:
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
    if step_nombre == "aplicar_clonacion_strict":
        if ctx is None:
            return f"{step_nombre}: sin ctx"
        return (
            f"{step_nombre}: {len(ctx.archivos_generados)} archivos clonados"
        )
    if step_nombre == "escribir_manifest_modified":
        return f"{step_nombre}: manifest OK"
    if step_nombre == "import_tag_table":
        ok = fb._import_tag_result is not None  # noqa: SLF001
        return (
            f"{step_nombre}: "
            f"{'OK' if ok else 'FAIL'} "
            f"({len(ctx.archivos_generados) if ctx else 0} prev.)"
        )
    if step_nombre == "wait_consolidation":
        return f"{step_nombre}: {TIA_CONSOLIDATION_SLEEP_S}s sleep OK"
    if step_nombre == "import_blocks_dbs":
        ok = fb._import_blocks_dbs_result is not None  # noqa: SLF001
        return f"{step_nombre}: {'OK' if ok else 'FAIL'}"
    if step_nombre == "import_blocks_logicos":
        ok = fb._import_blocks_logicos_result is not None  # noqa: SLF001
        return f"{step_nombre}: {'OK' if ok else 'FAIL'}"
    if step_nombre == "compile_plc":
        ok = fb._compile_result is not None and fb._compile_result.get("ok")  # noqa: SLF001
        return f"{step_nombre}: {'OK' if ok else 'FAIL'}"
    if step_nombre == "done":
        return f"{step_nombre}: apply compuesto"
    return f"{step_nombre}: OK"


__all__ = ["FunctionProcProcessCrearAplicar"]