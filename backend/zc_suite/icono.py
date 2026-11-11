"""zc_suite.icono — el icono de la app.

Dos cosas:

- El **placeholder "ZC"** en memoria, que es lo que se ve en la bandeja.
- El **``.ico``** multi-resolucion, que es lo que se embebe en el ``.exe``.

Porta ``core/launcher/make_icon.py`` y el placeholder de
``core/launcher/tray_app.py`` de la app anterior. El repo no lleva el
``.ico`` en binario: el build lo genera, y la bandeja lo dibuja en memoria.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

#: El azul corporativo del icono.
COLOR_FONDO = (15, 76, 117, 255)

#: El texto del icono.
TEXTO = "ZC"

#: Las medidas que lleva el ``.ico``.
MEDIDAS_ICO: tuple[tuple[int, int], ...] = (
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)


def _fuente(medida: int) -> ImageFont.ImageFont:
    """La fuente del texto, o la de por defecto si no hay Segoe."""
    try:
        return ImageFont.truetype("seguisb.ttf", medida)
    except OSError:
        return ImageFont.load_default()


def _centrar(
    dibujo: ImageDraw.ImageDraw,
    texto: str,
    fuente: ImageFont.ImageFont,
    ancho: int,
    alto: int,
    desplazamiento_y: int = 0,
) -> None:
    """Escribe el texto centrado en el lienzo."""
    caja = dibujo.textbbox((0, 0), texto, font=fuente)
    ancho_texto = caja[2] - caja[0]
    alto_texto = caja[3] - caja[1]
    dibujo.text(
        ((ancho - ancho_texto) / 2 - caja[0], (alto - alto_texto) / 2 - caja[1] + desplazamiento_y),
        texto,
        fill=(255, 255, 255, 255),
        font=fuente,
    )


def imagen_del_icono() -> Image.Image:
    """El icono "ZC" de la bandeja, en memoria.

    Returns:
        Una imagen RGBA de 64x64.
    """
    tamano = 64
    imagen = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    # Fondo cuadrado: a 64 px las esquinas redondeadas quedan pixeladas.
    dibujo.rectangle((0, 0, tamano, tamano), fill=COLOR_FONDO)
    _centrar(dibujo, TEXTO, _fuente(32), tamano, tamano)
    return imagen


def generar_ico(destino: Path) -> Path:
    """Escribe el ``.ico`` multi-resolucion del ejecutable.

    Args:
        destino: el fichero ``.ico`` a escribir.

    Returns:
        La ruta del ``.ico`` escrito.
    """
    tamano = 256
    imagen = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    radio = 40
    dibujo.rounded_rectangle(
        (8, 8, tamano - 8, tamano - 8),
        radius=radio,
        fill=COLOR_FONDO,
    )
    _centrar(dibujo, TEXTO, _fuente(130), tamano, tamano, desplazamiento_y=-4)

    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino, format="ICO", sizes=list(MEDIDAS_ICO))
    logger.info("Icono generado: %s", destino)
    return destino
