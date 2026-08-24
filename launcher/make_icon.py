"""Genera ``launcher/icon.ico`` (placeholder) si no existe.

No sobreescribe un icono real ya presente. La idea es que el repo no
arranque con un binario versionado: el icono se materializa al primer
build o se incluye manualmente por el dev.

Para distribuir un icono corporativo real, coloca un ``icon.ico`` válido
en esta carpeta y este script lo respetará. Se acepta tamaño 16x16,
32x32, 48x48, 64x64 o 256x256 (estándar Windows .ico multi-resolución).

Uso:
    python launcher/make_icon.py            # genera si falta
    python launcher/make_icon.py --force    # regenera siempre
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PACKAGING_DIR = Path(__file__).parent
ICON_PATH = PACKAGING_DIR / "icon.ico"


def _make_placeholder_icon() -> Image.Image:
    """Genera un icono simple 'ZC' sobre fondo azul (256x256 RGBA)."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fondo: cuadrado azul con esquinas redondeadas.
    radius = 40
    fill = (15, 76, 117, 255)  # azul corporativo (similar a Siemens)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=radius, fill=fill)

    # Texto "ZC" centrado.
    text = "ZC"
    try:
        font = ImageFont.truetype("seguisb.ttf", 130)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 4),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )

    return img


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el .ico placeholder.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobreescribe el icono aunque ya exista.",
    )
    args = parser.parse_args()

    if ICON_PATH.is_file() and not args.force:
        print(f"[ICON] Ya existe {ICON_PATH} (--force para regenerar).")
        return 0

    img = _make_placeholder_icon()
    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"[ICON] Generado {ICON_PATH} ({ICON_PATH.stat().st_size} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
