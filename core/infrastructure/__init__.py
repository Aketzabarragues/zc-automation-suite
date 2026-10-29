"""Adaptadores externos del nucleo.

Capa transversal que conecta el core con el mundo exterior: TIA Portal
(via tia/), config del proyecto (via config/) y el bridge de logs a la
SPA (via log/). NO sabe de areas concretas: expone interfaces comunes
que las areas extienden via AreaSpec.contributes_*.
"""
