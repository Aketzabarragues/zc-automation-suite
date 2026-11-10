"""areas — areas de negocio.

Un area es un paquete en ``areas/<id>/`` que expone:

- ``ID``       identificador estable (minusculas, sin acentos).
- ``NOMBRE``   nombre legible para el menu.
- ``rutas``    ``Blueprint`` Flask con las rutas del area.
- ``catalogo(config)``  catalogo de datos del area (columnas, tipos, tablas).
- ``defaults(config)``  valores por defecto que el area aporta a la config.

El nucleo no importa este paquete. La unica excepcion es la lista ``AREAS`` de
``zc_suite.main``, que es el punto unico de registro.
"""
