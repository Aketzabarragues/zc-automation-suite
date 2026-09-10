"""Core TIA infrastructure: worker OT genérico + command loader.

El worker (`worker_tia.py`) expone los comandos genéricos del
gateway TIA Portal. Los comandos específicos de cada área se
aÃ±aden en runtime mediante `command_loader.load_extra_commands`,
que itera el `AreaRegistry` y deja que cada área aporte los suyos.
"""
