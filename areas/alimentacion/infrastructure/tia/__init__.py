"""Subpaquete `tia` del área de alimentación.

Aporta los comandos transaccionales adicionales al ``COMMAND_REGISTRY``
del worker OT (capa core). Son el punto de extensión que el motor OT
genérico expone a las áreas mediante
``AreaSpec.contributes_tia_commands``.

Restricción arquitectónica (``.clinerules`` §1): el worker es el ÚNICO
proceso que importa ``siemens_tia_scripting``. Los handlers definidos
aquí NO importan la DLL directamente: solo aportan ``Callable`` con
firma ``(portal, ts, args) -> Any`` que el worker invocará dentro de
su proceso, bajo la misma transacción atómica que cualquier otro
comando del lote.
"""
