"""zc_suite — backend de zc-automation-suite.

App de escritorio (Windows, un solo operario) que automatiza proyectos de
Siemens TIA Portal mediante el SDK oficial ``siemens_tia_scripting``.

Estructura del paquete:

- ``main.py``    arranque (hilo TIA + Flask + bandeja) y lista ``AREAS``.
- ``tia.py``     hilo unico; unico dueno del portal de TIA.
- ``eventos.py`` bus SSE con los eventos ``progress``, ``job``, ``log`` y ``tia``.
- ``web.py``     app Flask, estaticos y ``GET /api/eventos``.
- ``config.py``  ``config.json`` validado con Pydantic.
- ``workdir.py`` ``.build_cache/<area>/<contexto>/{exports,modified,preview}``.
- ``tia_ops/``   operaciones contra TIA Portal (reciben el portal).
- ``simatic/``   lectura y escritura de ficheros SimaticSD / SimaticML.
- ``comun/``     utilidades compartidas por todas las areas.
- ``rutas/``     rutas Flask genericas del nucleo.
- ``areas/``     areas de negocio; el nucleo no las importa.
"""

__version__ = "0.1.0"
