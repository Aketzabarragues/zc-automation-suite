"""Tests unitarios para ``build_exe.py`` (orquestador PyInstaller).

Cubre la lógica pura de cada función del script sin invocar
PyInstaller de verdad (eso es smoke test, no unit test):

  - ``check_python_version`` valida 3.12 / 3.13 / 3.14.
  - ``ensure_pyinstaller`` falla con mensaje accionable.
  - ``resolve_siemens_pyd`` localiza el ``.pyd`` instalado.
  - ``collect_vendor_assets`` separa ``.dll`` / ``.xml``.
  - ``stage_vendor_assets`` usa tempdir (Cero Código Sucio).
  - ``write_generated_spec_file`` produce un ``.spec`` ejecutable
    con los ``upx_exclude`` y ``hiddenimports`` críticos.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

import pytest


# `sys.version_info` es un namedtuple sliceable. Para mockearlo
# correctamente sin liar la semántica, fabricamos uno equivalente.
_FakeVersionInfo = namedtuple("_FakeVersionInfo", ["major", "minor", "micro", "releaselevel", "serial"])

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import build_exe  # noqa: E402


# ── check_python_version ──────────────────────────────────────────


def test_check_python_version_accepts_3_12(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python 3.12.x no debe lanzar SystemExit."""
    fake = _FakeVersionInfo(3, 12, 0, "final", 0)
    with patch.object(sys, "version_info", fake):
        build_exe.check_python_version()  # no raise


def test_check_python_version_accepts_3_13(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python 3.13.x no debe lanzar SystemExit."""
    fake = _FakeVersionInfo(3, 13, 0, "final", 0)
    with patch.object(sys, "version_info", fake):
        build_exe.check_python_version()  # no raise


def test_check_python_version_accepts_3_14(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python 3.14.x no debe lanzar SystemExit."""
    fake = _FakeVersionInfo(3, 14, 0, "final", 0)
    with patch.object(sys, "version_info", fake):
        build_exe.check_python_version()  # no raise


def test_check_python_version_rejects_3_11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Python 3.11.x debe fallar con SystemExit(1) (TIA no soporta 3.11)."""
    fake = _FakeVersionInfo(3, 11, 0, "final", 0)
    with patch.object(sys, "version_info", fake):
        with pytest.raises(SystemExit) as exc:
            build_exe.check_python_version()
        assert exc.value.code == 1


def test_check_python_version_rejects_3_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Python 3.10.x debe fallar (regla del 3.12+)."""
    fake = _FakeVersionInfo(3, 10, 0, "final", 0)
    with patch.object(sys, "version_info", fake):
        with pytest.raises(SystemExit) as exc:
            build_exe.check_python_version()
        assert exc.value.code == 1


# ── ensure_pyinstaller ────────────────────────────────────────────


def test_ensure_pyinstaller_raises_clean_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si PyInstaller no está disponible, el mensaje dice cómo instalarlo."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError) as exc:
        build_exe.ensure_pyinstaller()
    msg = str(exc.value)
    assert "pip install pyinstaller" in msg
    assert "PyInstaller" in msg


# ── resolve_siemens_pyd ───────────────────────────────────────────


def test_resolve_siemens_pyd_finds_installed() -> None:
    """Si la wheel está instalada, retorna la ruta absoluta al .pyd."""
    # Asumimos que el venv de tests tiene la wheel (es requisito del proyecto).
    pyd_path = build_exe.resolve_siemens_pyd()
    assert pyd_path.is_file()
    assert pyd_path.suffix == ".pyd"
    # Debe empezar con 'siemens_tia_scripting' (puede tener ABI tag)
    assert pyd_path.name.startswith("siemens_tia_scripting")


def test_resolve_siemens_pyd_raises_clean_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la wheel no está, el error indica cómo instalarla."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(FileNotFoundError) as exc:
        build_exe.resolve_siemens_pyd()
    msg = str(exc.value)
    assert "siemens_tia_scripting" in msg
    assert "wheel" in msg.lower() or ".whl" in msg


# ── collect_vendor_assets ─────────────────────────────────────────


def test_collect_vendor_assets_separates_extensions(
    tmp_path: Path,
) -> None:
    """Crea un dir con .pyd + .dll + .xml mezclados y verifica la separación."""
    # Setup: un directorio de mentira con archivos de las 3 extensiones
    fake_pyd = tmp_path / "siemens_tia_scripting.pyd"
    fake_pyd.write_text("fake pyd")
    (tmp_path / "log4net.dll").write_text("fake dll")
    (tmp_path / "Siemens.TiaPortal.OpennessApi21.dll").write_text("fake")
    (tmp_path / "log4net.xml").write_text("<config/>")
    (tmp_path / "README.txt").write_text("should be ignored")  # extensión irrelevante
    (tmp_path / "siemens_tia_scripting.pyi").write_text("fake pyi")  # ignorado

    pyd, dlls, xmls = build_exe.collect_vendor_assets(fake_pyd)

    assert pyd == fake_pyd
    assert len(dlls) == 2
    assert all(d.suffix == ".dll" for d in dlls)
    assert all(d.parent == tmp_path for d in dlls)
    assert len(xmls) == 1
    assert xmls[0].suffix == ".xml"
    assert xmls[0].name == "log4net.xml"


def test_collect_vendor_assets_empty_dll_xml(tmp_path: Path) -> None:
    """Si la wheel no trae .dll/.xml, retorna listas vacías (warning, no error)."""
    fake_pyd = tmp_path / "siemens_tia_scripting.pyd"
    fake_pyd.write_text("pyd")
    # Solo el .pyd, nada más
    pyd, dlls, xmls = build_exe.collect_vendor_assets(fake_pyd)
    assert pyd == fake_pyd
    assert dlls == []
    assert xmls == []


# ── PROJECT_DATA_FILES (convención de PyInstaller) ───────────────


def test_project_data_files_use_directory_destinations() -> None:
    """Regression: ``PROJECT_DATA_FILES`` debe seguir la convención de
    PyInstaller: el segundo elemento de cada tuple es un DIRECTORIO
    dentro de ``_MEIPASS``, NO la ruta completa del archivo.

    Bug real visto en el .exe de producción: con
    ``("infrastructure/config.json", "infrastructure/config.json")``
    PyInstaller depositaba el fichero en
    ``_MEIPASS\\infrastructure\\config.json\\config.json`` (con
    sufijo extra). ``ConfigManager`` busca en
    ``_MEIPASS\\infrastructure\\config.json`` y falla con
    ``FileNotFoundError`` al arrancar el web. Mismo problema con
    el icono.
    """
    from pathlib import PurePosixPath

    assert len(build_exe.PROJECT_DATA_FILES) == 3

    # Aserciones explícitas para que el bug no se cuele de nuevo.
    assert ("launcher/icon.ico", "launcher") in build_exe.PROJECT_DATA_FILES
    assert ("infrastructure/config.json", "infrastructure") in build_exe.PROJECT_DATA_FILES
    assert (
        "interfaces/web_server/static",
        "interfaces/web_server/static",
    ) in build_exe.PROJECT_DATA_FILES

    # Regla general: si el source es un FICHERO (no directorio), el
    # destino debe ser su directorio padre — nunca la ruta completa
    # del archivo (eso crea un directorio anidado en el bundle).
    for src_rel, dst_rel in build_exe.PROJECT_DATA_FILES:
        src_path = PurePosixPath(src_rel)
        # El source es archivo si tiene sufijo y no termina en "/".
        if src_path.suffix:  # .ico, .json (no directorio)
            assert dst_rel != src_rel, (
                f"BUG REGRESIÓN: {src_rel!r} mapea a su propia ruta "
                f"{dst_rel!r} (debería mapear a un directorio padre)."
            )
            assert dst_rel == str(src_path.parent), (
                f"BUG REGRESIÓN: {src_rel!r} debería mapear a su "
                f"directorio padre ({src_path.parent!s}), no a "
                f"{dst_rel!r}."
            )


# ── stage_vendor_assets ───────────────────────────────────────────


def test_stage_vendor_assets_uses_tempdir_not_root(tmp_path: Path) -> None:
    """Cero Código Sucio: nada se copia a la raíz del repo."""
    # Crear archivos fake en tmp_path
    fake_pyd = tmp_path / "siemens_tia_scripting.pyd"
    fake_pyd.write_text("pyd")
    fake_dll = tmp_path / "log4net.dll"
    fake_dll.write_text("dll")
    fake_xml = tmp_path / "log4net.xml"
    fake_xml.write_text("xml")

    # Capturar el root del repo ANTES del staging
    repo_root = build_exe.ROOT
    files_before = set(repo_root.iterdir())

    staging_root, vendor_dir = build_exe.stage_vendor_assets(
        fake_pyd, [fake_dll], [fake_xml]
    )

    try:
        # El staging debe estar en tempdir, NO en el repo
        assert staging_root.exists()
        assert "zc_build_" in staging_root.name
        assert not str(staging_root).startswith(str(repo_root))

        # El .pyd stageado debe tener nombre canónico
        staged_pyd = vendor_dir / "siemens_tia_scripting.pyd"
        assert staged_pyd.exists()

        # Las DLLs y XMLs también se stagean
        assert (vendor_dir / "log4net.dll").exists()
        assert (vendor_dir / "log4net.xml").exists()

        # Cero Código Sucio: el root del repo NO debe tener nuevos
        # archivos vendor (.pyd/.dll/.xml/.spec).
        files_after = set(repo_root.iterdir())
        new_files = files_after - files_before
        new_vendor = [
            f for f in new_files
            if f.suffix in {".pyd", ".dll", ".xml", ".spec"}
        ]
        assert not new_vendor, f"Cero Código Sucio violado: {new_vendor}"
    finally:
        import shutil
        shutil.rmtree(staging_root, ignore_errors=True)


# ── write_generated_spec_file ─────────────────────────────────────


def test_write_generated_spec_contains_required_keys(tmp_path: Path) -> None:
    """El .spec generado contiene los flags críticos del plan."""
    # Setup: staging y vendor_dirs reales (tmp_path)
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "siemens_tia_scripting.pyd").write_text("pyd")
    fake_dll = vendor_dir / "log4net.dll"
    fake_dll.write_text("dll")
    fake_xml = vendor_dir / "log4net.xml"
    fake_xml.write_text("xml")

    spec_path = build_exe.write_generated_spec_file(
        staging_root=tmp_path,
        vendor_dir=vendor_dir,
        dlls=[fake_dll],
        xmls=[fake_xml],
    )

    assert spec_path.exists()
    content = spec_path.read_text(encoding="utf-8")

    # ── Binarios vendor: .pyd + DLLs a la raíz ────────────────────
    assert "siemens_tia_scripting.pyd" in content
    assert "log4net.dll" in content

    # ── UPX excluido: crítico, no debe comprimirse ──────────────────
    assert "upx_exclude" in content
    assert "siemens_tia_scripting.pyd" in content  # también en upx_exclude
    assert "*.dll" in content  # wildcard defensivo

    # ── Windowed: console=False ────────────────────────────────────
    assert "console=False" in content

    # ── Entry point = main_tray.py ─────────────────────────────────
    assert "main_tray.py" in content

    # ── Hidden imports críticos ────────────────────────────────────
    assert "pystray" in content
    assert "pystray._win32" in content
    assert "uvicorn" in content
    assert "fastapi" in content
    assert "siemens_tia_scripting" in content
    assert "pythonnet" in content
    assert "clr" in content

    # ── Excludes: MCP NO entra en el bundle ────────────────────────
    # (mcp y fastmcp aparecen dentro de comillas en la lista de excludes)
    assert "'mcp'" in content or "'mcp'," in content
    assert "'fastmcp'" in content or "'fastmcp'," in content
    # main.py NO se usa en frozen
    assert "'main'" in content or "'main'," in content

    # ── Datos del proyecto: SPA, icono, config.json ────────────────
    # El source (SPA) y los destinos (icon.ico → "launcher", config.json
    # → "infrastructure") deben aparecer en el spec generado. Tras
    # el fix del bug del directorio anidado, ``launcher/icon.ico`` y
    # ``infrastructure/config.json`` ya NO son los destinos (eran
    # rutas de archivo, no directorios).
    assert "interfaces/web_server/static" in content
    # El icono y el config.json se mapean a sus directorios padre.
    # En el spec el dest va como string entre comillas simples:
    # ``(r"...icon.ico", 'launcher')``. Buscamos ambos formatos.
    assert "'launcher'" in content or '"launcher"' in content
    assert "'infrastructure'" in content or '"infrastructure"' in content


def test_write_generated_spec_is_valid_python(tmp_path: Path) -> None:
    """El .spec generado se compila como Python válido (import sanity)."""
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "siemens_tia_scripting.pyd").write_text("pyd")

    spec_path = build_exe.write_generated_spec_file(
        staging_root=tmp_path,
        vendor_dir=vendor_dir,
        dlls=[],
        xmls=[],
    )
    # Si el spec tiene un syntax error, esto fallaría.
    # NO ejecutamos el spec (eso invocaría PyInstaller), solo lo compilamos.
    compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec")


def test_write_generated_spec_with_empty_dll_xml(tmp_path: Path) -> None:
    """Con DLLs/AMLs vacíos, el spec no rompe (listas vacías en Python)."""
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "siemens_tia_scripting.pyd").write_text("pyd")

    spec_path = build_exe.write_generated_spec_file(
        staging_root=tmp_path,
        vendor_dir=vendor_dir,
        dlls=[],
        xmls=[],
    )
    content = spec_path.read_text(encoding="utf-8")
    # Las listas vacías deben renderizarse como "[]"
    assert "for _dll in []:" in content
    assert "for _xml in []:" in content
    # El spec sigue siendo Python válido
    compile(content, str(spec_path), "exec")


# ── EXE_ICON ─────────────────────────────────────────────────────


def test_exe_icon_path_points_to_existing_file() -> None:
    """``EXE_ICON`` debe apuntar a un .ico real (multi-resolución).

    Si falla, ejecutar ``python launcher/make_icon.py`` o colocar
    un .ico válido en la ruta esperada.
    """
    icon = build_exe.EXE_ICON
    assert icon.is_file(), (
        f"EXE_ICON apunta a {icon} que no existe. "
        f"Ejecuta: python launcher/make_icon.py"
    )
    # El .ico debe tener al menos 1 KB (los iconos placeholder son ~18 KB).
    assert icon.stat().st_size > 1024, (
        f"EXE_ICON parece demasiado pequeño: {icon.stat().st_size} bytes"
    )


def test_write_generated_spec_contains_exe_icon(tmp_path: Path) -> None:
    """El .spec generado referencia la ruta del icono (no ``icon=None``)."""
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "siemens_tia_scripting.pyd").write_text("pyd")

    spec_path = build_exe.write_generated_spec_file(
        staging_root=tmp_path,
        vendor_dir=vendor_dir,
        dlls=[],
        xmls=[],
    )
    content = spec_path.read_text(encoding="utf-8")

    # El spec debe contener ``icon=r"..."`` apuntando a EXE_ICON.
    # No debe ser ``icon=None`` (eso era el comportamiento previo).
    assert "icon=None" not in content, (
        "El spec aún tiene icon=None; build_exe.py no inyecta la "
        "constante EXE_ICON correctamente."
    )
    # La ruta del icono (con backslashes escapados en el raw string)
    # debe aparecer en el spec.
    icon_backslashes = str(build_exe.EXE_ICON).replace("\\", "\\\\")
    assert icon_backslashes in content, (
        f"La ruta {build_exe.EXE_ICON} no aparece en el spec"
    )
