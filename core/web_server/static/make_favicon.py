"""Genera ``core/web_server/static/favicon.ico`` (placeholder) si no existe.

Mismo patron que ``core/launcher/make_icon.py``: icono "ZC" sobre fondo
azul corporativo (Siemens-like), multi-resolucion (16/32/48/64/128/256).
El .ico resultante lo sirve Flask automaticamente desde
``/static/favicon.ico`` y el navegador lo consume al cargar cualquier
pagina de la SPA (antes salia 404 en consola).

No sobreescribe un favicon real ya presente. La idea es la misma que
para ``icon.ico``: el repo no arranca con un binario versionado; el
favicon se materializa al primer arranque o se incluye manualmente por
el dev.

Para distribuir un favicon corporativo real, coloca un ``favicon.ico``
valido en esta carpeta y este script lo respetara. Se acepta tamano
16x16, 32x32, 48x48, 64x64, 128x128 o 256x256 (estandar multi-res).

Uso:
    python core/web_server/static/make_favicon.py            # genera si falta
    python core/web_server/static/make_favicon.py --force    # regenera siempre

Vinculado desde ``core/web_server/static/index.html`` con
``<link rel="icon" href="/favicon.ico">`` (Flask sirve el archivo
desde static/ sin necesidad de ruta explicita).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


STATIC_DIR = Path(__file__).parent
FAVICON_PATH = STATIC_DIR / "favicon.ico"


def _make_placeholder_favicon() -> Image.Image:
    """Genera un favicon simple 'ZC' sobre fondo azul (256x256 RGBA)."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fondo: cuadrado azul con esquinas redondeadas.
    # Mismo color corporativo que ``make_icon.py``: (15, 76, 117).
    radius = 40
    fill = (15, 76, 117, 255)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=radius, fill=fill)

    # Texto "ZC" centrado (mismas dimensiones que ``make_icon.py``).
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
    parser = argparse.ArgumentParser(description="Genera el favicon placeholder.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobreescribe el favicon aunque ya exista.",
    )
    args = parser.parse_args()

    if FAVICON_PATH.is_file() and not args.force:
        print(f"[FAVICON] Ya existe {FAVICON_PATH} (--force para regenerar).")
        return 0

    img = _make_placeholder_favicon()
    img.save(
        FAVICON_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(
        f"[FAVICON] Generado {FAVICON_PATH} ({FAVICON_PATH.stat().st_size} bytes)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
