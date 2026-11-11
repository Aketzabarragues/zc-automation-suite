"""Comprueba que el nucleo habla el idioma de TIA, no el del area.

``tia_ops/`` y ``simatic/`` hablan de constantes de usuario, tablas de
tags, bloques, DB, arrays, comentarios, valores y nombres. Lo especifico
del area (N_MAX, alimentacion, Excel, UID, slots) se queda en
``areas/alimentacion``, que es quien decide QUE cambiar y lo traduce a
operaciones de TIA genericas.

La comprobacion mira el codigo y los literales de todos los ficheros de
``backend/zc_suite/``, menos ``areas/``.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NUCLEO = RAIZ / "backend" / "zc_suite"

#: Terminos del area y su patron. El patron se busca sin distinguir
#: mayusculas.
PATRONES: tuple[tuple[str, str], ...] = (
    (r"\bn[_\-]?max", "N_MAX"),
    (r"alimentaci[oó]n", "alimentacion"),
    (r"\bexcel", "Excel"),
    (r"\buid", "uid"),
    (r"\bslot", "slot"),
    (r"\bdisp_\w+", "disp_"),
    (r"\bproc_\w+", "proc_"),
)

#: Excepciones justificadas: ``(ruta relativa al repo, motivo)``.
EXCEPCIONES: tuple[tuple[str, str], ...] = (
    (
        "backend/zc_suite/main.py",
        "Es el unico sitio del nucleo que nombra las areas: las registra en la "
        "lista AREAS. Ningun otro modulo del nucleo las conoce.",
    ),
)


def _relativo(ruta: Path) -> str:
    try:
        return str(ruta.relative_to(RAIZ)).replace("\\", "/")
    except ValueError:
        return str(ruta).replace("\\", "/")


def _excepciones_de(ruta: Path, excepciones: tuple[tuple[str, str], ...]) -> list[str]:
    """Los motivos de excepcion que aplican a este fichero."""
    return [motivo for esperada, motivo in excepciones if esperada == _relativo(ruta)]


def _terminos_en(texto: str) -> list[str]:
    """Los terminos del area que aparecen en un texto."""
    encontrados: list[str] = []
    for patron, nombre in PATRONES:
        if re.search(patron, texto, re.IGNORECASE):
            encontrados.append(nombre)
    return encontrados


def _ficheros_del_nucleo() -> list[Path]:
    """Los ficheros de ``backend/zc_suite/``, menos ``areas/``."""
    return sorted(
        ruta
        for ruta in NUCLEO.rglob("*.py")
        if "areas" not in ruta.relative_to(NUCLEO).parts
        and "__pycache__" not in ruta.parts
    )


def _fallos_del_nucleo(
    excepciones: tuple[tuple[str, str], ...] = EXCEPCIONES,
) -> list[str]:
    """Los terminos del area encontrados en el nucleo."""
    fallos: list[str] = []
    for ruta in _ficheros_del_nucleo():
        if _excepciones_de(ruta, excepciones):
            continue
        for numero, linea in enumerate(
            ruta.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for termino in _terminos_en(linea):
                fallos.append(
                    f"{_relativo(ruta)}:{numero}: '{termino}' -> {linea.strip()}"
                )
    return fallos


def test_el_nucleo_no_habla_el_idioma_del_area() -> None:
    fallos = _fallos_del_nucleo()
    assert not fallos, (
        "El nucleo habla el idioma del area. Muevelo a areas/ o anade la "
        "excepcion en EXCEPCIONES:\n" + "\n".join(fallos)
    )


def test_la_excepcion_justificada_se_ignora(tmp_path: Path) -> None:
    """Un fichero con excepcion no falla aunque tenga un termino del area."""
    copia = tmp_path / "nucleo_de_prueba.py"
    copia.write_text("valor = n_max_dispositivo\n", encoding="utf-8")
    excepciones = ((str(copia).replace("\\", "/"), "motivo de prueba"),)

    assert _terminos_en(copia.read_text(encoding="utf-8")) == ["N_MAX"]
    assert _excepciones_de(copia, excepciones) == ["motivo de prueba"]


def test_el_comprobador_detecta_un_termino_del_area() -> None:
    """El comprobador detecta lo que tiene que detectar."""
    assert _terminos_en("valor = n_max_dispositivo") == ["N_MAX"]
    assert _terminos_en("nombre = 'Excel'") == ["Excel"]
    assert _terminos_en("uid_del_dispositivo") == ["uid"]
    assert _terminos_en("tabla = alimentacion") == ["alimentacion"]
    assert _terminos_en("slot_map = construir()") == ["slot"]
    assert _terminos_en("def disp_actualizar(): ...") == ["disp_"]
    assert _terminos_en("def proc_sincronizar(): ...") == ["proc_"]


def test_el_comprobador_no_se_confunde() -> None:
    """Ni 'guid' ni 'max' sueltos son terminos del area."""
    assert _terminos_en("get_type_guid()") == []
    assert _terminos_en("max_eventos = 100") == []
    assert _terminos_en("constante de usuario") == []
    assert _terminos_en("tabla de tags") == []


def test_las_excepciones_son_ficheros_que_existen() -> None:
    """Una excepcion que apunte a un fichero que no existe es un error."""
    for esperada, _motivo in EXCEPCIONES:
        assert (RAIZ / esperada).is_file(), f"La excepcion apunta a {esperada}, que no existe."
