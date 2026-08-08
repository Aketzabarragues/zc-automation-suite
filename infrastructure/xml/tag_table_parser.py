"""Parser SimaticML para extraer ``PlcUserConstant`` de un .xml exportado.

⚠️ SCAFFOLDING — Portar la lógica real desde ``_legacy_reference/``.
Restricción: este módulo es OFFLINE (no invoca la API de TIA).
"""
from __future__ import annotations

from pathlib import Path


class SimaticMLTagParser:
    """Stub. La implementación real debe portarse desde el repositorio legacy.

    Methods:
        parse_user_constants(xml_file_path): Lee un ``.xml`` SimaticML y
            devuelve ``dict[str, str]`` con pares ``{valor_int: nombre}``.
    """

    @staticmethod
    def parse_user_constants(xml_file_path: str | Path) -> dict[str, str]:
        """Lee un ``.xml`` SimaticML y devuelve ``{valor_int: nombre_constante}``.

        Raises:
            NotImplementedError: Hasta que se porten los modelos reales
                desde ``_legacy_reference/``.
        """
        raise NotImplementedError(
            "SimaticMLTagParser.parse_user_constants es un stub. "
            "Portar la lógica desde _legacy_reference/. "
            f"Ruta solicitada: {xml_file_path}"
        )
