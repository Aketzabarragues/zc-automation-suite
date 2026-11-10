"""tia_ops — operaciones contra TIA Portal.

Cada modulo expone funciones que reciben el portal (o el ``PlcSoftware``) como
primer argumento y devuelven solo tipos primitivos: ``dict``, ``list``, ``str``,
``int``, ``bool``. Ningun objeto .NET sale de este paquete; la conversion es
responsabilidad de la propia operacion.

Modulos:

- ``proyecto.py``  abrir, guardar y cerrar proyectos.
- ``exportar.py``  exportar bloques, tags y tablas a disco.
- ``importar.py``  importar bloques y tags desde disco.
- ``compilar.py``  compilar el software del PLC.
- ``constantes.py`` nombres de tablas y carpetas por defecto.
- ``bloques.py``   recorrido y clasificacion de bloques.
"""
