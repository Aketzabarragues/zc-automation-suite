"""zc_suite.nucleo.tia.job — el trabajo y sus pasos.

``Job`` describe el trabajo que se esta ejecutando: declara sus pasos, los va
marcando y expone ``job.tia.portal``, la unica via al portal.

El estado de un trabajo son **variables locales** de la funcion que lo
ejecuta: aqui solo vive lo que hace falta para el reporting (el faceplate y
el log).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from zc_suite.errores import ZCError
from zc_suite.nucleo.tia.errores import CanceladoError, texto_error

if TYPE_CHECKING:
    from zc_suite.nucleo.tia.servicio import ServicioTIA

logger = logging.getLogger(__name__)

#: Un paso del trabajo: su identificador, o su identificador y su etiqueta.
Paso = str | tuple[str, str]

#: Estados de un paso del trabajo.
PENDIENTE = "pending"
EN_CURSO = "running"
HECHO = "done"
ERROR = "error"

#: Estados de un trabajo completo.
OK = "ok"
CANCELADO = "cancelado"


# ── helpers ────────────────────────────────────────────────────────────────


def _ahora() -> str:
    """Marca de tiempo ISO con segundos."""
    return datetime.now().isoformat(timespec="seconds")


def _etiqueta(nombre: str) -> str:
    """Etiqueta legible de un paso a partir de su identificador."""
    return nombre.replace("_", " ").capitalize()


def _etapa_de(paso: Paso) -> tuple[str, str]:
    """Identificador y etiqueta de un paso declarado.

    Un paso puede declararse como ``"exportar"`` o como
    ``("exportar", "Exportar bloques")``.
    """
    if isinstance(paso, tuple):
        nombre, etiqueta = paso
        return nombre, etiqueta
    return paso, _etiqueta(paso)

# ── paso del trabajo ───────────────────────────────────────────────────────


class _Etapa(dict[str, Any]):
    """Registro de un paso del trabajo.

    Es un dict normal, de modo que el codigo del trabajo escribe el detalle
    con ``paso["detail"] = "..."``. Cada mutacion publica el progreso, para
    que el detalle se vea en el faceplate mientras el paso sigue en curso.
    """

    def __init__(self, datos: dict[str, Any], al_cambiar: Callable[[], None]) -> None:
        super().__init__(datos)
        self._al_cambiar = al_cambiar
        self._interno = False

    def __setitem__(self, clave: str, valor: Any) -> None:
        super().__setitem__(clave, valor)
        if not self._interno:
            self._al_cambiar()

    def _set_interno(self, **campos: Any) -> None:
        """Actualiza campos del nucleo en una sola publicacion."""
        self._interno = True
        try:
            for clave, valor in campos.items():
                super().__setitem__(clave, valor)
        finally:
            self._interno = False
        self._al_cambiar()

# ── trabajo ────────────────────────────────────────────────────────────────


class Job:
    """Un trabajo en ejecucion dentro del hilo de TIA.

    El trabajo declara sus pasos al inicio con ``empezar`` y los va marcando
    con ``paso``. El estado del trabajo son variables locales de la funcion
    que lo ejecuta: aqui solo vive lo que hace falta para reporting.
    """

    def __init__(self, job_id: str, operacion: str, servicio: ServicioTIA) -> None:
        self.id = job_id
        self.tia = servicio
        self._operacion = operacion
        self._titulo = operacion
        self._etapas: list[_Etapa] = []
        self._por_id: dict[str, _Etapa] = {}
        self._cancelado = threading.Event()
        self._empezado_at: str | None = None
        self._terminado_at: str | None = None
        self._error: str | None = None

    # ── consultas ───────────────────────────────────────────────────────

    @property
    def cancelado(self) -> bool:
        """``True`` si el operario ha pedido la cancelacion."""
        return self._cancelado.is_set()

    @property
    def operacion(self) -> str:
        """Nombre de la operacion que ejecuta este trabajo."""
        return self._operacion

    def cancelar(self) -> None:
        """Pide la cancelacion. Se respeta entre pasos."""
        self._cancelado.set()
        self.log("Cancelacion solicitada.", nivel="aviso")

    # ── ciclo de vida ────────────────────────────────────────────────────

    def empezar(self, titulo: str, pasos: list[Paso]) -> None:
        """Declara el trabajo y todos sus pasos.

        Args:
            titulo: texto que ve el operario.
            pasos: identificadores de los pasos, en orden de ejecucion. Cada
                uno puede ser un identificador (``"exportar"``) o una pareja
                ``(identificador, etiqueta)`` para poner una etiqueta propia.

        Raises:
            ValueError: si ``pasos`` esta vacio o repite un identificador.
        """
        if not pasos:
            raise ValueError("El trabajo debe declarar al menos un paso.")
        declarados = [_etapa_de(paso) for paso in pasos]
        nombres = [nombre for nombre, _etiqueta_ in declarados]
        if len(set(nombres)) != len(nombres):
            raise ValueError(f"Hay pasos repetidos en {nombres!r}.")
        self._titulo = titulo
        self._empezado_at = _ahora()
        self._etapas = [
            _Etapa(
                {
                    "id": nombre,
                    "label": etiqueta,
                    "status": PENDIENTE,
                    "detail": None,
                    "started_at": None,
                    "finished_at": None,
                },
                self._publicar_progreso,
            )
            for nombre, etiqueta in declarados
        ]
        self._por_id = {etapa["id"]: etapa for etapa in self._etapas}
        logger.info(
            "Trabajo '%s' (%s) iniciado. Pasos: %s",
            titulo,
            self._operacion,
            ", ".join(nombres),
        )
        self._publicar_progreso()

    @contextmanager
    def paso(self, nombre: str) -> Iterator[dict[str, Any]]:
        """Marca un paso como en curso y lo cierra al salir.

        El dict que entrega es el registro del paso: se escribe el detalle
        con ``paso["detail"] = "..."``.

        Raises:
            ValueError: si el paso no fue declarado en ``empezar``.
            CanceladoError: si el trabajo estaba cancelado antes de empezar.
        """
        if nombre not in self._por_id:
            declarados = list(self._por_id)
            raise ValueError(
                f"El paso '{nombre}' no fue declarado en job.empezar(). "
                f"Pasos declarados: {declarados}"
            )
        if self.cancelado:
            raise CanceladoError("El trabajo fue cancelado.")
        etapa = self._por_id[nombre]
        etapa._set_interno(status=EN_CURSO, started_at=_ahora())
        try:
            yield etapa
        except BaseException as exc:
            etapa._set_interno(
                status=ERROR,
                detail=texto_error(exc),
                finished_at=_ahora(),
            )
            nivel_paso = logging.WARNING if isinstance(exc, ZCError) else logging.ERROR
            logger.log(
                nivel_paso,
                "  Paso '%s' fallo: %s",
                etapa["label"],
                texto_error(exc),
            )
            raise
        else:
            etapa._set_interno(status=HECHO, finished_at=_ahora())
            logger.info("  Paso '%s': %s", etapa["label"], etapa["detail"] or "sin detalle")

    def finalizar(
        self,
        estado: str,
        error: str | None,
        traza: str | None = None,
        nivel: int = logging.ERROR,
    ) -> None:
        """Cierra el trabajo y publica el estado final.

        Args:
            estado: ``ok``, ``cancelado`` o ``error``.
            error: el mensaje del fallo, si lo hubo.
            traza: el traceback del fallo, si lo hubo. Sin traza, el fallo
                se registra en una linea: es un fallo esperado (TIA
                cerrado, sin proyecto, sin permiso).
            nivel: el nivel con el que se registra el fallo.
        """
        self._terminado_at = _ahora()
        self._error = error
        if estado == OK:
            logger.info("Trabajo '%s' (%s) terminado.", self._titulo, self._operacion)
        elif estado == CANCELADO:
            logger.warning(
                "Trabajo '%s' (%s) cancelado: %s",
                self._titulo,
                self._operacion,
                error or "",
            )
        else:
            logger.log(
                nivel,
                "Trabajo '%s' (%s) fallo: %s",
                self._titulo,
                self._operacion,
                error or "sin detalle",
            )
            if traza:
                logger.error("Traceback del trabajo '%s':\n%s", self._titulo, traza)
        if estado != OK:
            for etapa in self._etapas:
                if etapa["status"] == EN_CURSO:
                    etapa._set_interno(status=ERROR, finished_at=_ahora())

    def snapshot(self, activo: bool = True) -> dict[str, Any]:
        """Estado del trabajo con la forma que consume el faceplate."""
        etapas = [dict(etapa) for etapa in self._etapas]
        total = len(etapas)
        current = sum(1 for etapa in etapas if etapa["status"] in (HECHO, ERROR))
        return {
            "active": activo,
            "operation": self._operacion,
            "label": self._titulo,
            "current": current,
            "total": total,
            "percent": round(100.0 * current / total) if total else 0,
            "stages": etapas,
            "started_at": self._empezado_at,
            "finished_at": self._terminado_at,
            "error": self._error,
        }

    # ── publicacion ──────────────────────────────────────────────────────

    def log(self, mensaje: str, nivel: str = "info") -> None:
        """Publica una linea de log del trabajo."""
        self.tia.publicar("log", {"nivel": nivel, "mensaje": mensaje})

    def _publicar_progreso(self) -> None:
        self.tia.publicar("progress", self.snapshot())
