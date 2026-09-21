"""FB de area: preview (read-only) de generar un proceso desde plantilla.

State machine sobre el helper ``proc_process_generator``
(``areas/alimentacion/helpers/proc/proc_process_generator.py``). El
helper expone funciones independientes que reciben un
``ProcProcessGenContext`` y mutan sus campos. Aqui en el FB vive la
state machine: el orden de las llamadas, el mapping step -> funcion del
helper, y la instanciacion del ctx.

Hereda directo de ``FunctionBase``.

Runtime params via ``start(**kwargs)``:
  - ``plantillas_path`` (str): ruta base donde viven las subcarpetas de
    plantillas TIA. Obligatorio.
  - ``dir_plantilla_nombre`` (str): nombre de la subcarpeta de la
    plantilla concreta. Obligatorio.
  - ``base_nueva`` (int): UID base del proceso nuevo (p. ej. 60010).
    Obligatorio.
  - ``codigo_nuevo`` (str): codigo corto del proceso (p. ej. "EXP").
    Obligatorio.
  - ``nombre_nuevo`` (str): nombre humano del proceso. Obligatorio.
  - ``minimos_usuario`` (dict[str, int]): 4 N_MAX del operario (claves:
    ``N_MAX_PREAL``, ``N_MAX_PINT``, ``N_MAX_ALM``, ``N_MAX_ALM_HMI``).
    Obligatorio.
  - ``plc_blocks_cache`` (set[str] | None): nombres de bloques que ya
    existen en el PLC destino. Se cruza por NOMBRE. Si es None, el
    FB sigue (warning).
  - ``build_cache_root`` (Path): raiz del BuildCache del area. Si es
    None, usa ``<cwd>/.build_cache``.

El ``self.result`` se popula con la shape esperada por la SPA::

    {
      "manifest_plantilla": dict | None,
      "archivos_previstos": list[dict],
      "colisiones":         list[str],
      "plantilla_copia_dir": str,
      "success":            bool,
    }

Steps (8):
  - leer_manifest         -> helper.proc_process_leer_manifest
  - validar_minimos       -> helper.proc_process_validar_minimos
  - copiar_a_preview      -> helper.proc_process_copiar_a_preview
  - construir_diccionarios-> helper.proc_process_construir_diccionarios
  - detectar_colisiones   -> helper.proc_process_detectar_colisiones
  - generar_previstos     -> helper.proc_process_generar_previstos
  - done                  -> (interno: vuelco ``ctx.result`` a
                              ``self.result``)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase

logger = logging.getLogger(__name__)


class FunctionProcProcessCrearPreview(FunctionBase):
    """FB que genera un preview (read-only) de la clonacion de un
    proceso desde una plantilla TIA."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # El preview solo toca disco local (copytree + regex). En PLCs
    # grandes con muchas plantillas puede tardar ~30s. 120s cubre
    # holgadamente el peor caso esperado.
    STEP_TIMEOUT_S: float = 120.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_process_crear_preview",
        titulo: str = "Preview: crear proceso desde plantilla",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        # El preview NO toca TIA: ``tia_client`` puede ser None. Se
        # mantiene la firma alineada con el resto de FBs para que el
        # ``register()`` del area sea homogeneo.
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
                {"nombre": "detectar_colisiones"},
                {"nombre": "generar_previstos"},
                {"nombre": "done"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas. ``config_manager`` y ``tia_client``
        # NO son obligatorios para este FB; se mantienen en la firma
        # por homogeneidad pero no se usan.
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
        self._plc_blocks_cache: set[str] | None = None
        # ProcProcessGenContext compartido entre los 8 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar params + construir ``ProcProcessGenContext``.

        Todos los params son obligatorios. ``plc_blocks_cache`` puede
        ser None (cache nunca populado) — el helper emite warning y el
        preview sigue (``colisiones`` queda con un mensaje accionable).
        """
        plantillas_path = params.get("plantillas_path", "")
        if not plantillas_path:
            raise ValueError(
                "FunctionProcProcessCrearPreview.start(plantillas_path=...) "
                "es obligatorio"
            )
        dir_plantilla_nombre = params.get("dir_plantilla_nombre", "")
        if not dir_plantilla_nombre:
            raise ValueError(
                "FunctionProcProcessCrearPreview.start("
                "dir_plantilla_nombre=...) es obligatorio"
            )
        base_nueva = params.get("base_nueva")
        if base_nueva is None or not isinstance(base_nueva, int):
            raise ValueError(
                "FunctionProcProcessCrearPreview.start(base_nueva=int) "
                "es obligatorio"
            )
        codigo_nuevo = params.get("codigo_nuevo", "")
        if not codigo_nuevo:
            raise ValueError(
                "FunctionProcProcessCrearPreview.start(codigo_nuevo=...) "
                "es obligatorio"
            )
        nombre_nuevo = params.get("nombre_nuevo", "")
        if not nombre_nuevo:
            raise ValueError(
                "FunctionProcProcessCrearPreview.start(nombre_nuevo=...) "
                "es obligatorio"
            )
        minimos_usuario = params.get("minimos_usuario", {})
        if not isinstance(minimos_usuario, dict) or not minimos_usuario:
            raise ValueError(
                "FunctionProcProcessCrearPreview.start(minimos_usuario=dict) "
                "es obligatorio (N_MAX_PREAL/PINT/ALM/ALM_HMI)"
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
            f"[{self.nombre}] Preview crear proceso "
            f"{self._base_nueva}/{self._codigo_nuevo} desde "
            f"{dir_plantilla}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper."""
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
                await proc_process_generator.proc_process_leer_manifest(self._ctx)
            case "validar_minimos":
                # Si falla, lanza PlantillaMinimosNoCumplidos y el base
                # va a n_error con error_stage.
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
            case "detectar_colisiones":
                await proc_process_generator.proc_process_detectar_colisiones(
                    self._ctx
                )
            case "generar_previstos":
                await proc_process_generator.proc_process_generar_previstos(
                    self._ctx
                )
            case "done":
                await proc_process_generator.proc_process_done_summary(self._ctx)
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        return _step_summary(self._ctx, step_nombre)

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que la SPA consume."""
        if self._ctx is None:
            self.result = {
                "success": False,
                "archivos_previstos": [],
                "colisiones": [
                    "ProcProcessGenContext no inicializado. "
                    "Verifica los parametros del start()."
                ],
                "plantilla_copia_dir": "",
                "manifest_plantilla": None,
            }
            return

        self.result = self._ctx.result

        n_previstos = len(self._ctx.result.get("archivos_previstos", []))
        n_colisiones = len(self._ctx.result.get("colisiones", []))
        logger.debug(
            f"[{self.nombre}] Preview crear proceso "
            f"{self._base_nueva}/{self._codigo_nuevo}: "
            f"{n_previstos} archivos previstos, "
            f"{n_colisiones} colision(es)."
        )


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "leer_manifest":
        if ctx.manifest_plantilla is None:
            return f"{step_nombre}: sin manifest"
        return (
            f"{step_nombre}: base={ctx.base_vieja} "
            f"codigo={ctx.codigo_viejo}"
        )
    if step_nombre == "validar_minimos":
        return f"{step_nombre}: N_MAX OK"
    if step_nombre == "copiar_a_preview":
        return f"{step_nombre}: plantilla copiada a {ctx.dir_plantilla_copia}"
    if step_nombre == "construir_diccionarios":
        return (
            f"{step_nombre}: "
            f"{len(ctx.dicc_bloques)} reglas bloques + "
            f"{len(ctx.dicc_xml)} reglas XML"
        )
    if step_nombre == "detectar_colisiones":
        return f"{step_nombre}: {len(ctx.colisiones)} colision(es)"
    if step_nombre == "generar_previstos":
        return f"{step_nombre}: {len(ctx.archivos_previstos)} archivos"
    if step_nombre == "done":
        return f"{step_nombre}: preview compuesto"
    return f"{step_nombre}: OK"


__all__ = ["FunctionProcProcessCrearPreview"]