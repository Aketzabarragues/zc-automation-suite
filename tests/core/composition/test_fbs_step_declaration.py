"""Guard de la declaracion de steps con ``@step``.

El motor (``core/composition/plc_function_base.py``) puede tomar los
steps de dos sitios:

  1. de los metodos marcados con ``@step`` (forma actual): los recoge
     en **orden de definicion** y hace el dispatch.
  2. de la lista ``steps=`` del constructor (forma antigua): el
     dispatch lo hace el ``run_step`` del propio FB.

Este modulo fija el contrato de la forma 1 y comprueba que las dos no
se pueden mixing (una migracion a medias dejaria pasos sin ejecutar o
ejecutados dos veces).
"""
from __future__ import annotations

import pytest

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker


class FbDeclarado(FunctionBase):
    """FB de prueba: dos steps declarados, en orden de flujo."""

    def __init__(self, tracker=None) -> None:
        super().__init__(nombre="fb_declarado", titulo="FB declarado", tracker=tracker)
        self.llamadas: list[str] = []

    @step("Zeta", descripcion="El primero en el flujo")
    def _stage_1_zeta(self) -> str:
        self.llamadas.append("zeta")
        return "zeta hecha"

    @step("Alfa", descripcion="El segundo en el flujo")
    def _stage_2_alfa(self) -> str:
        self.llamadas.append("alfa")
        return "alfa hecha"


class FbAntiguo(FunctionBase):
    """FB de prueba con la forma antigua: ``steps=`` + ``run_step``."""

    def __init__(self, tracker=None) -> None:
        super().__init__(
            nombre="fb_antiguo",
            titulo="FB antiguo",
            steps=[{"nombre": "Uno"}, {"nombre": "Dos"}],
            tracker=tracker,
        )

    def run_step(self, idx: int, **params) -> str:
        return f"paso {idx} hecho"


def test_los_pasos_se_declaran_en_orden_de_definicion() -> None:
    """El orden de los metodos es el orden del flujo, no el alfabetico.

    ``dir()`` ordenaria "Alfa" antes que "Zeta": el flujo se leeria al
    reves.
    """
    specs = FbDeclarado.pasos_declarados()
    assert [s.nombre for s in specs] == ["Zeta", "Alfa"]
    assert [s.metodo for s in specs] == ["_stage_1_zeta", "_stage_2_alfa"]
    assert [s.descripcion for s in specs] == [
        "El primero en el flujo",
        "El segundo en el flujo",
    ]


def test_el_motor_usa_la_declaracion_como_steps() -> None:
    """``fb.steps`` sale de la declaracion, con su handler."""
    fb = FbDeclarado()
    assert [s["nombre"] for s in fb.steps] == ["Zeta", "Alfa"]
    assert [s["handler"] for s in fb.steps] == ["_stage_1_zeta", "_stage_2_alfa"]
    assert fb.steps[0]["descripcion"] == "El primero en el flujo"


def test_el_fb_antiguo_conserva_su_forma() -> None:
    """Sin ``@step``, el FB sigue usando la lista ``steps=``."""
    fb = FbAntiguo()
    assert [s["nombre"] for s in fb.steps] == ["Uno", "Dos"]
    assert "handler" not in fb.steps[0]


def test_no_se_pueden_mixing_las_dos_formas() -> None:
    """Declarar pasos y pasar ``steps=`` a la vez es un error de codigo.

    Una migracion a medias dejaria pasos sin ejecutar o ejecutados dos
    veces. El fallo tiene que verse al construir el FB, no tres minutos
    despues contra el PLC.
    """

    class FbMezclado(FunctionBase):
        @step("Uno", descripcion="declara un paso")
        def _stage_1_uno(self) -> str:
            return "uno"

    with pytest.raises(ValueError, match="Migra el FB entero o nada"):
        FbMezclado(nombre="mixto", titulo="mixto", steps=[{"nombre": "Otro"}])


def test_nombre_de_step_duplicado_falla_al_construir() -> None:
    """Dos steps con la misma etiqueta visible son un error."""

    class FbDuplicado(FunctionBase):
        @step("Repetido", descripcion="primero")
        def _stage_1_uno(self) -> str:
            return "uno"

        @step("Repetido", descripcion="segundo")
        def _stage_2_otro(self) -> str:
            return "otro"

    with pytest.raises(ValueError, match="nombre de paso duplicado"):
        FbDuplicado(nombre="dup", titulo="dup")


def test_el_handler_se_invoca_y_su_detail_llega_al_tracker() -> None:
    """Cada step se ejecuta y su detail va al tracker."""
    tracker = ProgressTracker()
    fb = FbDeclarado(tracker=tracker)
    fb.execute()

    assert fb.nStep == FunctionBase.n_done, fb.error_msg
    assert fb.llamadas == ["zeta", "alfa"]

    stages = {s["id"]: s for s in tracker.snapshot().stages}
    assert stages["Zeta"]["status"] == "done"
    assert stages["Zeta"]["detail"] == "zeta hecha"
    assert stages["Alfa"]["detail"] == "alfa hecha"


def test_el_fallback_a_run_step_sigue_funcionando() -> None:
    """Los FBs que aun no han migrado ejecutan su ``run_step``."""
    tracker = ProgressTracker()
    fb = FbAntiguo(tracker=tracker)
    fb.execute()

    assert fb.nStep == FunctionBase.n_done, fb.error_msg
    stages = {s["id"]: s for s in tracker.snapshot().stages}
    assert stages["Uno"]["detail"] == "paso 0 hecho"
    assert stages["Dos"]["detail"] == "paso 1 hecho"


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_un_handler_async_es_error_de_programacion() -> None:
    """Un handler async no se puede ejecutar en el hilo del dispatcher.

    El base rechaza la corrutina sin esperarla: el warning de "never
    awaited" es la consecuencia esperada del rechazo.
    """

    class FbAsync(FunctionBase):
        @step("Async", descripcion="handler async")
        async def _stage_1_async(self) -> str:
            return "nunca"

    fb = FbAsync(nombre="async", titulo="async")
    fb.execute()
    assert "corrutina" in (fb.error_msg or ""), fb.error_msg
