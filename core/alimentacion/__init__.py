"""Subdominio Alimentación.

Capa de dominio puro (sin dependencias OT) que modela los dispositivos
de hardware y la lógica de software específica del departamento de
alimentación.

Restricción arquitectónica: este paquete es ESTRICTAMENTE PURO.
- Prohibido importar ``siemens_tia_scripting``.
- Prohibido el uso de ``Any`` en los modelos de dominio.
- Prohibido depender de librerías de infraestructura (openpyxl, etc.).
"""
