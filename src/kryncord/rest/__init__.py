"""Fachada REST de uso.

A camada `http/` cuida dos detalhes transversais. Este módulo oferece a
interface que `api/` consome — o caminho completo de uma requisição:
fila do bucket, espera de cota, repetição, e a resposta já interpretada.
"""

from kryncord.rest.client import MAX_RATE_LIMIT_WAITS, RESTClient

__all__ = ["MAX_RATE_LIMIT_WAITS", "RESTClient"]
