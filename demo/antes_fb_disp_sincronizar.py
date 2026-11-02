"""ANTES: el FB del sync de dispositivos (extracto literal del repo real).

Fichero real: areas/alimentacion/functions/function_disp_sincronizar.py
Lineas citadas: las del repo en el momento del analisis (commit a5be3d8).

Este fichero NO se importa ni se ejecuta: es material de analisis.

Lo que se ve aqui:
  1. Los steps se declaran DOS veces (STAGES + steps=).
  2. Cada FB reimplementa el dispatch (run_step).
  3. El detail que ve el HMI sale de un if/elif por nombre literal
     (_step_summary), con 29 ramas muertas en 4 de los 9 FBs del area.
"""
from __future__ import annotations

from typing import Any


class FunctionDispSincronizar:
    """Extracto: lo que hay HOY en el repo."""

    # ==================================================================
    # 1. PRIMERA DECLARACION: el mapa nombre -> metodo
    # real L104-116 (literal)
    # ==================================================================
    STAGES: list[tuple[int, str, str]] = [
        (1,  "Exportar etiquetas",                 "_stage_1_exportar_tags"),
        (2,  "Calcular diferencias de dispositivos", "_stage_2_compute_diff"),
        (3,  "Preparar operaciones",                "_stage_3_preparar_ops"),
        (4,  "Aplicar N_MAX y renombres",          "_stage_4_tx_a_nmax_renames"),
        (5,  "Esperar consolidación TIA",          "_stage_5_wait_consolidation"),
        (6,  "Re-exportar etiquetas",              "_stage_6_exportar_post_tx_a"),
        (7,  "Editar archivos XML",                "_stage_7_editar_xmls_offline"),
        (8,  "Aplicar dispositivos",               "_stage_8_tx_b_devices"),
        (9,  "Compilar bloques",                   "_stage_9_compilar_bloques"),
        (10, "Aplicar comentarios",                "_stage_10_aplicar_comentarios"),
        (11, "Generar preview post-sincronización", "_stage_11_disp_post_preview"),
    ]

    # real L100-103: el propio codigo avisa del peligro.
    #   - ``nombre_step`` debe coincidir con ``self.steps[idx]["nombre"]``
    #     (registrado en __init__). Si cambias uno, cambia el otro.

    # ==================================================================
    # 2. CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "disp_sincronizar",
        titulo: str = "Sincronizar dispositivos contra PLC",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        app_cache: Any = None,
    ) -> None:
        # real L135-152: la SEGUNDA declaracion, con los mismos nombres.
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Exportar etiquetas"},
                {"nombre": "Calcular diferencias de dispositivos"},
                {"nombre": "Preparar operaciones"},
                {"nombre": "Aplicar N_MAX y renombres"},
                {"nombre": "Esperar consolidación TIA"},
                {"nombre": "Re-exportar etiquetas"},
                {"nombre": "Editar archivos XML"},
                {"nombre": "Aplicar dispositivos"},
                {"nombre": "Compilar bloques"},
                {"nombre": "Aplicar comentarios"},
                {"nombre": "Generar preview post-sincronización"},
            ],
            tracker=tracker,
        )
        self._config = config_manager
        self._tia_client = tia_client
        self._ctx = None

    # ==================================================================
    # 3. DISPATCH: reimplementado en cada FB
    # real L222-257 (literal)
    # ==================================================================

    def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper (``exportar_tags``, ``compute_diff``, etc.)
        contra el ``DispSyncContext`` compartido.
        """
        if self._ctx is None:
            raise RuntimeError(
                "DispSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los 11 stages se declaran arriba de la clase.
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                handler()
                # Resumen legible del step que acaba de correr (aparece en la SPA).
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionDispSincronizar"
        )

    # ==================================================================
    # 4. LOS STEPS: metodos que NO devuelven el detail
    # real L362-409 (literal, recortado el final)
    # ==================================================================

    def _stage_1_exportar_tags(self) -> None:
        """Limpia sync/ y exporta las tablas selectivas al snapshot export."""
        self._ctx.tags_base = self._ctx.sync_variables_export
        self._ctx.selective_tables = ["2000_Disp_ED", "2000_Disp_EA", "..."]
        batch_result = self._ctx.tia_client.submit_and_wait(
            "execute_batch",
            {
                "operations": [
                    {
                        "command": "export_tables",
                        "args": {
                            "plc_name": self._ctx.plc_name,
                            "target_dir": str(self._ctx.tags_base),
                            "table_names": self._ctx.selective_tables,
                            # La jerarquia de carpetas del PLC es lo que
                            # permite a TIA hacer UPDATE al reimportar.
                            "keep_folder_structure": True,
                        },
                    }
                ],
            },
            timeout=60.0,
        )
        # ... validacion del resultado ...

    # El resto de stages (_stage_2 .. _stage_11) tienen la misma forma:
    # hacen su trabajo y NO devuelven nada. El detail lo pone el
    # _step_summary de abajo.


# ======================================================================
# 5. EL DETAIL: un if/elif por nombre literal, fuera de la clase
# real L1437-1493 (literal, recortado)
# ======================================================================

def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "Exportar etiquetas":
        return f"Exportar etiquetas: {len(ctx.selective_tables)} tablas exportadas"
    if step_nombre == "Calcular diferencias de dispositivos":
        adds = sum(len(v) for v in ctx.added_per_table.values())
        rems = sum(len(v) for v in ctx.removed_per_table.values())
        return (
            f"Calcular diferencias de dispositivos: {adds} adds, "
            f"{rems} removes, {len(ctx.renamed_per_table)} renames"
        )
    if step_nombre == "Preparar operaciones":
        return (
            f"Preparar operaciones: {len(ctx.nmax_ops)} N_MAX ops, "
            f"{len(ctx.device_changes)} tablas con cambios"
        )
    # ... 8 ramas mas ...
    # Y en los OTROS 4 FBs del area, estas claves comparan contra
    # nombres internos ("check_state_commit", "done"...) que NO existen
    # en steps=: el 100 % de sus ramas es codigo muerto y el operario
    # ve el fallback de abajo.
    return f"{step_nombre}: OK"
