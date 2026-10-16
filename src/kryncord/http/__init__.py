"""Mecânica HTTP transversal: rotas, autenticação, rate limits, retries.

Camada de baixo nível. Não conhece "canais" ou "mensagens" — conhece
método, caminho, query, headers e corpo. O `rest/` expõe a fachada; o
`api/` dá o vocabulário por recurso.

O rate limit segue o contrato oficial: headers ``X-RateLimit-*`` lidos de
**toda** resposta, e o corpo de um 429 com ``retry_after`` como fallback.
O bucket é identificado pela resposta, nunca deduzido do nome do
endpoint — deduzir daria um 429 antes de qualquer teste.
"""

from kryncord.http.authentication import DEFAULT_PREFIX, Token, build_auth_header
from kryncord.http.buckets import Bucket, BucketManager, HashEntry, synthetic_hash
from kryncord.http.client import HTTPClient
from kryncord.http.multipart import (
    FilePart,
    Multipart,
    MultipartError,
    encode,
    encode_payload_json,
    generate_boundary,
    total_size,
)
from kryncord.http.rate_limits import (
    BucketState,
    GlobalRateLimit,
    RateLimitHeaders,
    parse_429,
)
from kryncord.http.request import HTTPMethod, Request
from kryncord.http.response import Response
from kryncord.http.retries import FailureKind, RetryPolicy, classify_transport_error
from kryncord.http.routes import (
    BURST_MAJOR,
    GLOBAL_MAJOR,
    RouteData,
    generate_route_data,
    snowflake_timestamp_ms,
)

__all__ = [
    "BURST_MAJOR",
    "CRLF",
    "DEFAULT_PREFIX",
    "GLOBAL_MAJOR",
    "MAX_BOUNDARY_ATTEMPTS",
    "OCTET_STREAM",
    "Bucket",
    "BucketManager",
    "BucketState",
    "FailureKind",
    "FilePart",
    "GlobalRateLimit",
    "HTTPClient",
    "HTTPMethod",
    "HashEntry",
    "Multipart",
    "MultipartError",
    "RateLimitHeaders",
    "Request",
    "Response",
    "RetryPolicy",
    "RouteData",
    "Token",
    "build_auth_header",
    "classify_transport_error",
    "encode",
    "encode_payload_json",
    "generate_boundary",
    "generate_route_data",
    "parse_429",
    "snowflake_timestamp_ms",
    "synthetic_hash",
    "total_size",
]
