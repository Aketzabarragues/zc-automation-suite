"""El apply de crear un proceso desde una plantilla.

El port de ``FunctionProcCrearSincronizar`` de ``main``: clona la plantilla
al workdir, la renombra, importa tablas y bloques en una unica transaccion y
compila fuera de ella. A diferencia de la prevision, **escribe en TIA**, asi
que el doble tiene que aceptar importaciones, registrar su orden, dejar fallar
cada import de forma programable y compilar los bloques.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import HECHO

from .conftest import (
    NOMBRE_PLC,
    PLANTILLA_NOMBRE,
    PROC_UID,
)


def _etapa(entorno: Any, nombre: str) -> dict[str, Any]:
    """El estado final de un paso del trabajo, desde el ultimo ``progress``.

    El evento ``job`` de fin no lleva las etapas: estas viajan en los
    eventos ``progress`` (``job.snapshot()``), el ``progress`` final se
    publica justo despues del ``job`` (de ahi el pequeño wait). El fixture
    es por test y el test lanza un solo trabajo, asi que el ultimo
    ``progress`` inactivo de la operacion es el final del trabajo.
    """
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in reversed(list(entorno.eventos)):
            if (
                tipo == "progress"
                and not carga["active"]
                and carga["operation"] == "crear"
            ):
                for etapa in carga["stages"]:
                    if etapa["id"] == nombre:
                        return etapa
        time.sleep(0.005)
    raise AssertionError(f"No se encontro la etapa {nombre!r}.")


def _transaccion_importar(resultado: dict[str, Any]) -> dict[str, Any]:
    """La transaccion de importar del resultado."""
    for transaccion in resultado["transacciones"]:
        if transaccion["nombre"] == "Importar proceso":
            return transaccion
    raise AssertionError("No hay ninguna transaccion 'Importar proceso'.")


def test_camino_happy(entorno_apply: Any, tmp_path: Path) -> None:
    """El apply completo: importa en una tx y compila fuera de ella."""
    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["success"] is True
    assert resultado["plc"] == NOMBRE_PLC
    assert resultado["proc_uid"] == PROC_UID

    # La transaccion de import se confirmo (no se revirtio).
    tx = _transaccion_importar(resultado)
    assert tx["estado"] == "confirmada"

    # Tablas ANTES que bloques, ambas en la MISMA transaccion (1 inicio + 1
    # fin, sin rollback).
    assert entorno_apply.plc.importaciones_tablas, "no se importaron tablas"
    assert entorno_apply.plc.importaciones_bloques, "no se importaron bloques"
    assert entorno_apply.orden.index("import_tablas") < entorno_apply.orden.index(
        "import_bloques"
    )
    inicios = [t for t in entorno_apply.proyecto.transacciones if "inicio" in t]
    fins = [t for t in entorno_apply.proyecto.transacciones if "rollback" in t]
    assert len(inicios) == 1
    assert len(fins) == 1
    assert fins[0]["rollback"] is False

    # Se compilaron los bloques nuevos (los stems .s7dcl generados).
    nombres = sorted(
        Path(f).stem for f in resultado["archivos_generados"] if f.endswith(".s7dcl")
    )
    assert "DB100_CPR_INTERFAZ" in nombres
    assert "FC101_CPR_ORDENES" in nombres
    # La compilacion no tumbo el apply (los cambios ya estan aplicados).
    assert resultado["compilacion"]["ok"] is True


def test_import_no_recibe_carpeta_destino(entorno_apply: Any) -> None:
    """Ni importar_tablas ni importar_bloques mandan ``carpeta_destino``.

    Con ``""`` TIA V21 no hace match UPDATE de los bloques pre-existentes:
    intenta CREATE y falla. Se omite el argumento (``None``).
    """
    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    for imp in entorno_apply.plc.importaciones_tablas:
        assert imp["carpeta_destino"] is None
    for imp in entorno_apply.plc.importaciones_bloques:
        assert imp["carpeta_destino"] is None


def test_el_import_no_contiene_manifest(entorno_apply: Any, tmp_path: Path) -> None:
    """El manifest.json no viaja ni en Bloques ni en Variables.

    El import recorre la carpeta raiz entera; si el manifest estuviera en la
    carpeta de bloques o de variables se importaria como si fuera un bloque
    o una tabla. Solo los ficheros de la plantilla importan.
    """
    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    dir_nuevo = tmp_path / "procesos_crear" / "Nuevo"
    ficheros_bloques = sorted(
        p.name for p in (dir_nuevo / "Bloques de programa").rglob("*") if p.is_file()
    )
    ficheros_variables = sorted(
        p.name for p in (dir_nuevo / "Variables PLC").rglob("*") if p.is_file()
    )
    assert "manifest.json" not in ficheros_bloques
    assert "manifest.json" not in ficheros_variables
    # El manifest del proceso nuevo se escribio en la raiz de ``Nuevo``.
    assert (dir_nuevo / "manifest.json").is_file()


def test_los_n_max_importados_son_los_del_excel(
    entorno_apply: Any, tmp_path: Path
) -> None:
    """El XML importado lleva los N_MAX del proceso del Excel, no los de la
    plantilla.

    El Excel del proceso CPR (uid 100) tiene preal=2, pint=1, alarmas=2 y
    alm_hmi=2. El XML de la plantilla llevaba los minimos (1,1,2,2). Tras la
    clonacion, el ``<Value>`` de cada ``<Name>100_N_MAX_*</Name>`` se fija al
    del operario.
    """
    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    xml_ruta = tmp_path / "procesos_crear" / "Nuevo" / "Variables PLC"
    xmls = [p for p in xml_ruta.rglob("*.xml") if p.is_file()]
    assert xmls, "no hay ningun XML de variables en el Nuevo"
    contenido = xmls[0].read_text(encoding="utf-8")
    # El nombre se renombro a la base nueva y el valor se fijo al del Excel.
    assert "<Name>100_N_MAX_PREAL</Name>" in contenido
    assert "<Name>100_N_MAX_PINT</Name>" in contenido
    assert "<Name>100_N_MAX_ALM</Name>" in contenido
    assert "<Name>100_N_MAX_ALM_HMI</Name>" in contenido
    # El valor del PREAL paso de 1 (plantilla) a 2 (Excel).
    assert "<Name>100_N_MAX_PREAL</Name><Value>2</Value>" in contenido
    assert "<Name>100_N_MAX_PINT</Name><Value>1</Value>" in contenido
    assert "<Name>100_N_MAX_ALM</Name><Value>2</Value>" in contenido
    assert "<Name>100_N_MAX_ALM_HMI</Name><Value>2</Value>" in contenido


def test_colision_aborta_sin_importar(entorno_apply: Any) -> None:
    """Un nombre post-rename ya en el PLC: colision, fallo, cero imports."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=[{"nombre": "DB1_SYS"}, {"nombre": "DB100_CPR_INTERFAZ"}],
        tablas=[{"nombre": "100_CPR"}],
        tipos=[],
    )

    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=sesion)

    assert evento["estado"] == "error"
    assert "colision" in evento["error"].lower()
    assert "DB100_CPR_INTERFAZ" in evento["error"]
    assert entorno_apply.plc.importaciones_tablas == []
    assert entorno_apply.plc.importaciones_bloques == []


def test_dependencia_ausente_aborta_sin_importar(entorno_apply: Any) -> None:
    """Una dependencia declarada que no esta en el PLC: fallo, cero imports."""
    # La sesion por defecto del fixture lleva DB1_SYS; aqui la quita.
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=[{"nombre": "DB999_OTRO"}],
        tablas=[{"nombre": "100_CPR"}],
        tipos=[],
    )

    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=sesion)

    assert evento["estado"] == "error"
    assert "dependencia" in evento["error"].lower()
    assert "DB1_SYS" in evento["error"]
    assert entorno_apply.plc.importaciones_tablas == []
    assert entorno_apply.plc.importaciones_bloques == []


def test_tia_v18_aborta_antes_de_copiar(entorno_apply_v18: Any, tmp_path: Path) -> None:
    """TIA V18 no soporta SimaticSD: el apply aborta en validar, sin copiar."""
    evento = entorno_apply_v18.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "error"
    assert "V21" in evento["error"]
    # No se copio nada al workdir.
    assert not (tmp_path / "procesos_crear" / "Plantilla").exists()
    assert not (tmp_path / "procesos_crear" / "Nuevo").exists()
    assert entorno_apply_v18.plc.importaciones_tablas == []
    assert entorno_apply_v18.plc.importaciones_bloques == []


def test_sin_escaneo_aborta(entorno_apply: Any) -> None:
    """Sin escaneo fresco del PLC: el apply aborta (es un fallo duro)."""
    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=Sesion())

    assert evento["estado"] == "error"
    assert "escaneo" in evento["error"].lower()
    assert entorno_apply.plc.importaciones_tablas == []
    assert entorno_apply.plc.importaciones_bloques == []


def test_fallo_en_importar_tablas_revirtiendo(entorno_apply: Any) -> None:
    """importar_tablas falla: la tx se revierte, no se importan bloques ni se
    compila, y el job termina en error."""
    entorno_apply.plc._fallo_import_tablas = "fallo simulado de tablas"  # type: ignore[assignment]

    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "error"
    assert "revertida" in evento["error"].lower()
    # No se importaron bloques (el fallo fue en tablas, antes).
    assert entorno_apply.plc.importaciones_bloques == []
    # La transaccion se marco como revertida (rollback=True).
    rolls = [t for t in entorno_apply.proyecto.transacciones if t.get("rollback")]
    assert rolls, "la transaccion no se revirtio"


def test_fallo_en_importar_bloques_revirtiendo(entorno_apply: Any) -> None:
    """importar_bloques falla: la tx se revierte y no se compila."""
    entorno_apply.plc._fallo_import_bloques = "fallo simulado de bloques"  # type: ignore[assignment]

    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "error"
    assert "revertida" in evento["error"].lower()
    # Las tablas si llegaron a importarse (fallo en bloques, despues).
    assert entorno_apply.plc.importaciones_tablas, "las tablas no se importaron"
    rolls = [t for t in entorno_apply.proyecto.transacciones if t.get("rollback")]
    assert rolls, "la transaccion no se revirtio"


def test_compilacion_con_error_no_tumba(entorno_apply: Any) -> None:
    """Un error de compilacion NO tumba el apply: success True, ok False."""
    resultado_falso = {
        "compilados": [
            {
                "nombre": "DB100_CPR_INTERFAZ",
                "tiene_errores": True,
                "mensajes": [
                    "ZC_PLC_STD > Program blocks > DB100_CPR_INTERFAZ (DB100) "
                    "> Interface > Data type Boo is unknown."
                ],
                "avisos": [],
                "era_inconsistente": True,
            }
        ],
        "sin_cambios": ["FC101_CPR_ORDENES"],
        "no_encontrados": [],
        "errores": [],
        "con_errores": ["DB100_CPR_INTERFAZ"],
        "n_compilados_ok": 0,
        "n_compilados_error": 1,
        "n_sin_cambios": 1,
        "n_no_encontrados": 0,
        "n_errores": 0,
    }
    evento = _crear_con_compilador(entorno_apply, resultado_falso)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["success"] is True
    assert resultado["compilacion"]["ok"] is False
    assert resultado["compilacion"]["error"] is not None
    assert "DB100_CPR_INTERFAZ" in resultado["compilacion"]["error"]


def test_cancelacion_no_es_fallo(entorno_apply: Any) -> None:
    """La cancelacion del operario no es un fallo: el trabajo termina como
    cancelado (no como error).

    La cancelacion es cooperativa y se respeta entre pasos. El doble bloquea
    dentro del import (un TIA lento) y el test pide la cancelacion justo
    alli: el import termina (y la tx se confirma) y el siguiente paso
    (``compilar``) aborta con ``CanceladoError``.
    """
    plc = entorno_apply.plc
    plc.bloquea_import = True
    try:
        job_id = entorno_apply.lanzar(
            proc_uid=PROC_UID,
            plc=NOMBRE_PLC,
            dir_plantilla_nombre=PLANTILLA_NOMBRE,
        )
        # El import esta en curso (el doble se ha senalizado a si mismo).
        assert plc.esperando_import.wait(timeout=5.0)
        # Pide la cancelacion mientras el import sigue en curso.
        assert entorno_apply.servicio.cancelar(job_id)
        # Suelta el import: termina y la tx se confirma.
        plc.libera_import.set()
        evento = entorno_apply._esperar(job_id)
    finally:
        plc.bloquea_import = False
        plc.esperando_import.clear()
        plc.libera_import.clear()

    assert evento["estado"] == "cancelado"
    # El import se confirmo (la cancelacion llego despues de el, no revierte).
    confirmadas = [
        t for t in entorno_apply.proyecto.transacciones if t.get("rollback") is False
    ]
    assert confirmadas, "la transaccion de import no se confirmo"
    # No se compilo nada (la cancelacion llego antes del paso ``compilar``).
    assert "compilar" not in entorno_apply.orden


def test_el_escaneo_de_sesion_se_actualiza(entorno_apply: Any) -> None:
    """Al terminar, el escaneo de la sesion incluye los bloques nuevos.

    El doble expone los bloques importados en ``get_program_blocks``;
    ``escanear_bloques`` los ve y ``actualizar_bloques`` los deja en la
    sesion.
    """
    from .conftest import BloqueCompilableFalso

    nuevos = [
        BloqueCompilableFalso("DB100_CPR_INTERFAZ"),
        BloqueCompilableFalso("FC101_CPR_ORDENES"),
    ]
    entorno_apply.plc._bloques = (  # type: ignore[assignment]
        list(entorno_apply.plc._bloques) + nuevos
    )

    sesion = entorno_apply.sesion
    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=sesion)

    assert evento["estado"] == "ok", evento.get("error")
    escaneo = sesion.escaneo(NOMBRE_PLC)
    assert escaneo is not None
    nombres = {b["nombre"] for b in escaneo.bloques}
    assert "DB100_CPR_INTERFAZ" in nombres
    assert "FC101_CPR_ORDENES" in nombres


def test_el_escaneo_de_sesion_incluye_la_tabla_nueva(
    entorno_apply: Any,
) -> None:
    """El apply importa la tabla ``<uid>_<codigo>`` del proceso; el refresco
    del escaneo la deja en la sesion (bloques nuevos incluidos).

    Sin esto, la prevision de la 4.5 diria "la tabla no existe".
    """
    from .conftest import BloqueCompilableFalso, TablaCrearFalso

    nuevos = [
        BloqueCompilableFalso("DB100_CPR_INTERFAZ"),
        BloqueCompilableFalso("FC101_CPR_ORDENES"),
    ]
    entorno_apply.plc._bloques = (  # type: ignore[assignment]
        list(entorno_apply.plc._bloques) + nuevos
    )
    entorno_apply.plc.tablas = (  # type: ignore[assignment]
        [TablaCrearFalso("100_CPR")]
    )

    sesion = entorno_apply.sesion
    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=sesion)

    assert evento["estado"] == "ok", evento.get("error")
    assert evento["resultado"]["escaneo_actualizado"] is True
    escaneo = sesion.escaneo(NOMBRE_PLC)
    assert escaneo is not None
    tablas = {t["nombre"] for t in escaneo.tablas}
    assert "100_CPR" in tablas
    bloques = {b["nombre"] for b in escaneo.bloques}
    assert "DB100_CPR_INTERFAZ" in bloques
    assert "FC101_CPR_ORDENES" in bloques


def test_compilar_dentro_de_su_paso(entorno_apply: Any) -> None:
    """La compilacion corre DENTRO del paso "compilar": el paso tiene estado
    y detalle (como el paso "manifest" de la prevision, no un paso vacio)."""
    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    etapa = _etapa(entorno_apply, "compilar")
    assert etapa["status"] == HECHO
    assert "compile=" in etapa["detail"]
    # La compilacion ocurrio (el paso no es un decorado): el doble la vio.
    nombres = sorted(
        Path(f).stem
        for f in evento["resultado"]["archivos_generados"]
        if f.endswith(".s7dcl")
    )
    assert "DB100_CPR_INTERFAZ" in nombres
    assert "FC101_CPR_ORDENES" in nombres


def test_el_refresco_del_escaneo_no_tumba_el_aplicar(
    entorno_apply: Any,
) -> None:
    """Si ``escanear_bloques`` falla, el trabajo termina en ok: el import ya
    esta confirmado en TIA y el refresco no puede revocarlo. El escaneo queda
    sin refrescar y el resultado lo dice (``escaneo_actualizado`` False)."""
    entorno_apply.plc.fallo_escaneo_bloques = "fallo simulado del escaneo"

    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["success"] is True
    assert resultado["escaneo_actualizado"] is False
    # La transaccion de import sigue confirmada.
    tx = _transaccion_importar(resultado)
    assert tx["estado"] == "confirmada"
    # El paso "escaneo" termino bien, con el detalle del aviso.
    etapa = _etapa(entorno_apply, "escaneo")
    assert etapa["status"] == HECHO
    assert etapa["detail"] == "no se pudo refrescar"
    # El aviso se logueo.
    logs = [c for t, c in entorno_apply.eventos if t == "log"]
    assert any(
        c["nivel"] == "warning"
        and "no se pudo refrescar el escaneo" in c["mensaje"]
        for c in logs
    )


def test_el_apply_borra_la_prevision_de_crear(entorno_apply: Any) -> None:
    """Tras crear el proceso, la prevision de crear deja de valer: se borra
    de la sesion (volver a ofrecer "crear" para un proceso ya creado seria
    un error)."""
    from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION_CREAR

    sesion = entorno_apply.sesion
    sesion.guardar_dato_area(
        "alimentacion",
        CLAVE_PREVISION_CREAR,
        {
            "plc": NOMBRE_PLC,
            "proc_uid": PROC_UID,
            "dir_plantilla_nombre": PLANTILLA_NOMBRE,
            "resultado": {},
        },
    )

    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    assert CLAVE_PREVISION_CREAR not in sesion.datos_area("alimentacion")


def test_el_apply_con_fallo_de_import_no_borra_la_prevision(
    entorno_apply: Any,
) -> None:
    """Si la transaccion de import se revierte, el proceso no existe: la
    prevision de crear sigue en la sesion (se puede reintentar)."""
    from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION_CREAR

    sesion = entorno_apply.sesion
    sesion.guardar_dato_area(
        "alimentacion",
        CLAVE_PREVISION_CREAR,
        {
            "plc": NOMBRE_PLC,
            "proc_uid": PROC_UID,
            "dir_plantilla_nombre": PLANTILLA_NOMBRE,
            "resultado": {},
        },
    )
    entorno_apply.plc._fallo_import_tablas = "fallo simulado de tablas"  # type: ignore[assignment]

    evento = entorno_apply.crear(proc_uid=PROC_UID)

    assert evento["estado"] == "error"
    assert "revertida" in evento["error"].lower()
    assert CLAVE_PREVISION_CREAR in sesion.datos_area("alimentacion")


def test_el_apply_sin_sesion_no_falla(entorno_apply: Any) -> None:
    """Sin sesion (``sesion=None``) el apply no falla al querer borrar la
    prevision: no hay nada que borrar."""
    evento = entorno_apply.crear(proc_uid=PROC_UID, sesion=None)

    assert evento["estado"] == "ok", evento.get("error")
    assert evento["resultado"]["success"] is True


def test_dir_plantilla_nombre_con_traversal(entorno_apply: Any) -> None:
    """Un nombre de carpeta con '/' o '..' es un fallo de operacion."""
    evento = entorno_apply.crear(
        proc_uid=PROC_UID,
        dir_plantilla=f"../{PLANTILLA_NOMBRE}",
    )

    assert evento["estado"] == "error"
    assert "separadores" in evento["error"]


# ── helpers de test ────────────────────────────────────────────────────────


class _CompiladorFalso:
    """Un compilar_bloques que devuelve el resultado dado, sin tocar TIA."""

    def __init__(self, resultado: dict[str, Any]) -> None:
        self._resultado = resultado

    def __call__(self, portal: Any, plc: str, nombres: list[str]) -> dict[str, Any]:
        return self._resultado


def _crear_con_compilador(
    entorno: Any,
    resultado_falso: dict[str, Any],
) -> dict[str, Any]:
    """Lanza el apply con ``compilar_bloques`` parcheado a un resultado fijo."""
    from zc_suite.areas.alimentacion.funciones.procesos import (
        crear as modulo_crear,
    )

    original = modulo_crear.compilar_bloques
    try:
        modulo_crear.compilar_bloques = _CompiladorFalso(  # type: ignore[assignment]
            resultado_falso
        )
        job_id = entorno.servicio.lanzar(
            modulo_crear.crear,
            proc_uid=PROC_UID,
            plc=NOMBRE_PLC,
            dir_plantilla_nombre=PLANTILLA_NOMBRE,
            almacen=entorno.almacen,
            config=entorno.modelo,
            sesion=entorno.sesion,
            plantillas_dir=entorno.plantillas,
        )
        return entorno._esperar(job_id)
    finally:
        modulo_crear.compilar_bloques = original  # type: ignore[assignment]
