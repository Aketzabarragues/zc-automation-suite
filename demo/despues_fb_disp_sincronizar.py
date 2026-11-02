"""DESPUES (formato A): el FB del sync de dispositivos.

Propuesta sobre areas/alimentacion/functions/function_disp_sincronizar.py.
NO se aplica a la aplicacion: esto es la demo del diseno.

Cada paso es una caja de SFC: nombre, descripcion y codigo, todo junto.
El motor (demo/despues_function_base.py) hace el dispatch; el FB no
declara los pasos, no tiene tabla STAGES, ni run_step, ni _step_summary.

Lo que desaparece respecto al FB real:
  - la tabla STAGES (13 lineas)
  - la segunda declaracion steps=[...] (13 lineas)
  - el run_step con su dispatch (36 lineas)
  - el _step_summary con sus 11 ramas (57 lineas)

Lo que se queda: los 11 pasos y su logica, cada uno en su metodo, con
el detail que ve el operario.

Los nombres de los metodos (``_stage_N_<nombre>``) se conservan: 85
referencias de test y 2 documentos dependen de ellos. Los nombres
visibles de los pasos tambien: son las etiquetas que ve el operario en
la barra de progreso.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from demo.despues_function_base import FunctionBase, step


@dataclass
class DispSyncContext:
    """Estado compartido entre los 11 pasos del FB.

    Se mantiene tal cual: es el estado de negocio del sync, no
    boilerplate. Cada FB tiene el suyo porque divergen de verdad.
    """

    plc_name: str = ""
    tags_base: Any = None
    tags_modified: Any = None
    selective_tables: list[str] = field(default_factory=list)
    added_per_table: dict[str, list[str]] = field(default_factory=dict)
    removed_per_table: dict[str, list[str]] = field(default_factory=dict)
    renamed_per_table: dict[str, tuple[str, str]] = field(default_factory=dict)
    nmax_ops: list[dict[str, Any]] = field(default_factory=list)
    device_changes: list[dict[str, Any]] = field(default_factory=list)
    n_max_updates: int = 0
    compile_ok: bool = False
    compile_error: str | None = None


class FunctionDispSincronizar(FunctionBase):
    """Sincroniza las tablas de tags de dispositivos contra el PLC.

    11 pasos, en orden. El diagrama se genera desde esta misma
    declaracion: ``python demo/diagrama_sfc.py``.
    """

    STEP_TIMEOUT_S: float = 600.0

    def __init__(
        self,
        nombre: str = "disp_sincronizar",
        titulo: str = "Sincronizar dispositivos contra PLC",
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        app_cache: Any = None,
        tracker: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            tracker=tracker,
        )
        self._config = config_manager
        self._tia_client = tia_client
        self._ctx: DispSyncContext | None = None

    # ==================================================================
    # CICLO DE VIDA
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Valida los parametros y prepara el ctx."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError("plc_name es obligatorio")
        self._ctx = DispSyncContext(plc_name=str(plc_name))

    def on_finish(self, **params: Any) -> None:
        """Vuelca el resultado al HMI (lo que ve el operario)."""
        if self._ctx is None:
            self.result = {"success": False, "message": "FB no llego a ejecutar"}
            return
        self.result = {
            "success": True,
            "message": (
                f"Inyeccion completada: {self._ctx.n_max_updates} N_MAX "
                f"aplicados en TIA"
            ),
            "n_max_updates": self._ctx.n_max_updates,
            "compile_ok": self._ctx.compile_ok,
        }

    # ==================================================================
    # LOS 11 PASOS
    # Cada paso devuelve su detail: es lo que ve el operario.
    # ==================================================================

    @step(
        "Exportar etiquetas",
        descripcion="Exporta del PLC las tablas de tags de dispositivos",
    )
    def _stage_1_exportar_etiquetas(self) -> str:
        """Limpia sync/ y exporta las tablas selectivas al snapshot export."""
        # ... logica actual (46 lineas) ...
        return f"Exportar etiquetas: {len(self._ctx.selective_tables)} tablas exportadas"

    @step(
        "Calcular diferencias de dispositivos",
        descripcion="Compara los XML exportados con los dispositivos del Excel",
    )
    def _stage_2_calcular_diferencias_de_dispositivos(self) -> str:
        """Calcula el diff entre los XMLs exportados y el AppCache."""
        # ... logica actual (56 lineas) ...
        adds = sum(len(v) for v in self._ctx.added_per_table.values())
        rems = sum(len(v) for v in self._ctx.removed_per_table.values())
        return (
            f"Calcular diferencias de dispositivos: {adds} adds, "
            f"{rems} removes, {len(self._ctx.renamed_per_table)} renames"
        )

    @step(
        "Preparar operaciones",
        descripcion="Prepara las operaciones de N_MAX, renombres y tablas",
    )
    def _stage_3_preparar_operaciones(self) -> str:
        """Prepara las operaciones de N_MAX, renombres y device changes."""
        # ... logica actual ...
        return (
            f"Preparar operaciones: {len(self._ctx.nmax_ops)} N_MAX ops, "
            f"{len(self._ctx.device_changes)} tablas con cambios"
        )

    @step(
        "Aplicar N_MAX y renombres",
        descripcion="Tx A: transaccion online con N_MAX y renombres",
    )
    def _stage_4_aplicar_n_max_y_renombres(self) -> str:
        """Tx A: aplica N_MAX y renombres online (transaccion)."""
        # ... logica actual ...
        return (
            f"Aplicar N_MAX y renombres: {len(self._ctx.nmax_ops)} ops "
            f"aplicadas en TIA"
        )

    @step(
        "Esperar consolidación TIA",
        descripcion="Espera a que TIA consolide los cambios del Tx A",
    )
    def _stage_5_esperar_consolidacion_tia(self) -> str:
        """Espera a que TIA consolide los cambios del Tx A."""
        # ... logica actual ...
        return "Esperar consolidación TIA: TIA consolida (2s)"

    @step(
        "Re-exportar etiquetas",
        descripcion="Re-exporta las tablas tras el Tx A (estado ya aplicado)",
    )
    def _stage_6_re_exportar_etiquetas(self) -> str:
        """Re-exporta las tablas de dispositivos tras el Tx A."""
        # ... logica actual ...
        return "Re-exportar etiquetas: XMLs releidos post-Tx A"

    @step(
        "Editar archivos XML",
        descripcion="Aplica adds y removes de dispositivos en los XML offline",
    )
    def _stage_7_editar_archivos_xml(self) -> str:
        """Edita los XMLs offline (adds y removes por dispositivo)."""
        # ... logica actual ...
        return "Editar archivos XML: XMLs offline editados"

    @step(
        "Aplicar dispositivos",
        descripcion="Tx B: importa las tablas de dispositivos en TIA (transaccion)",
    )
    def _stage_8_aplicar_dispositivos(self) -> str:
        """Tx B: importa las tablas de dispositivos en TIA (transaccion)."""
        # ... logica actual ...
        return (
            f"Aplicar dispositivos: {len(self._ctx.device_changes)} tablas "
            f"importadas a TIA"
        )

    @step(
        "Compilar bloques",
        descripcion="Compila los DBs afectados por el sync",
    )
    def _stage_9_compilar_bloques(self) -> str:
        """Compila los DBs afectados."""
        # ... logica actual ...
        return "Compilar bloques: compile=OK"

    @step(
        "Aplicar comentarios",
        descripcion="Aplica los comentarios de los dispositivos en los DBs",
    )
    def _stage_10_aplicar_comentarios(self) -> str:
        """Aplica los comentarios de los dispositivos en los DBs."""
        # ... logica actual ...
        return "Aplicar comentarios: 0 reused + 120 inserted en 12 DBs"

    @step(
        "Generar preview post-sincronización",
        descripcion="Prepara el preview del estado final, para el HMI",
    )
    def _stage_11_generar_preview_post_sincronizacion(self) -> str:
        """Genera el preview post-sincronizacion."""
        # ... logica actual ...
        return "Generar preview post-sincronización: preview post-sync generado"
