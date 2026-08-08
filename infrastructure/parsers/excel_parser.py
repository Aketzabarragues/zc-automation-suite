"""Parser de Excel para extraer el estado *deseado* de las dimensiones.

⚠️ SCAFFOLDING — Portar la lógica real desde ``_legacy_reference/``.
Restricción: **prohibido** importar ``siemens_tia_scripting``.

Este parser es **offline** (lee el .xlsx ya generado por el equipo de
ingeniería y devuelve un mapeo ``{nombre_constante: valor}``). Una vez
portada la implementación legacy, este stub será reemplazado.
"""
from __future__ import annotations

from pathlib import Path


class ExcelParser:
    """Stub. La implementación real debe portarse desde el repositorio legacy.

    Methods:
        extraer_dimensiones(excel_path): Lee el .xlsx y devuelve
            ``dict[str, int]`` con pares ``{nombre_constante: valor}``.
    """

    def extraer_dimensiones(self, excel_path: str | Path) -> dict[str, int]:
        """Devuelve ``{nombre_constante: valor}`` desde el Excel.

        Raises:
            NotImplementedError: Hasta que se porten los modelos reales
                desde ``_legacy_reference/``.
        """
        raise NotImplementedError(
            "ExcelParser.extraer_dimensiones es un stub. "
            "Portar la lógica desde _legacy_reference/. "
            f"Ruta solicitada: {excel_path}"
        )
