/**
 * tailwind.config.js — Configuración del binario standalone.
 *
 * Sólo se usa cuando el desarrollador compila el CSS con la CLI
 * v2.x (que internamente usa Tailwind v3.x). Si se usa Tailwind
 * v4+, el binario leerá las directivas ``@source`` de
 * ``interfaces/web_server/static/src/input.css`` directamente.
 *
 * Paths ``content``:非常重要 — el motor de Tailwind purga
 * cualquier clase que no aparezca en estos archivos. Como el
 * frontend está modularizado en ESM, los templates viven en
 * strings dentro de los ``.js``. Sin los paths correctos, las
 * clases (``bg-cyan-700``, ``flex-shrink-0``...) se purgarían y
 * la UI quedaría sin estilos.
 *
 * Tras el PR 5 (bounded contexts), los componentes del área
 * ``alimentacion`` se han movido a
 * ``areas/alimentacion/frontend/components/``. Hay que incluirlos
 * en ``content`` para que Tailwind no purgue las clases que usan
 * sus templates. Cuando llegue un área nueva (``envasado``, etc.),
 * el glob ``./areas/**/frontend/**/*.js`` la recoge automáticamente
 * sin tocar este config.
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./interfaces/web_server/static/index.html",
        "./interfaces/web_server/static/js/**/*.js",
        "./areas/**/frontend/**/*.js",
    ],
    theme: {
        extend: {
            colors: {
                slate: {
                    700: "#334155",
                    800: "#1e293b",
                    900: "#0f172a",
                },
                cyan: {
                    500: "#06b6d4",
                    600: "#0891b2",
                    700: "#0e7490",
                },
            },
        },
    },
    plugins: [
        // daisyUI: si el desarrollador lo descarga, lo enchufa aquí.
        // require("daisyui"),
    ],
};
