"""Testes de `kryncord.http.retries` — quando repetir, e quanto esperar.

O ponto central é a matriz: `POST` não repete em falha ambígua, porque
pode ter criado a mensagem já.
"""

from __future__ import annotations

import httpx
import pytest

from kryncord.http.request import HTTPMethod, Request
from kryncord.http.retries import (
    FailureKind,
    RetryPolicy,
    classify_transport_error,
)

_AMBIGUOUS = [
    FailureKind.AMBIGUOUS,
    FailureKind.SERVER_ERROR,
]


def _request(method: HTTPMethod, route: str = "/channels/1/messages") -> Request:
    return Request(method=method, route=route)


# --------------------------------------------------------------------------
# Matriz de decisão
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method", [HTTPMethod.GET, HTTPMethod.PUT, HTTPMethod.DELETE, HTTPMethod.PATCH]
)
@pytest.mark.parametrize("kind", _AMBIGUOUS)
def test_idempotent_methods_retry_on_ambiguous(method: HTTPMethod, kind: FailureKind) -> None:
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(_request(method), kind, 0) is True


@pytest.mark.parametrize("kind", _AMBIGUOUS)
def test_post_refuses_ambiguous_and_server_error(kind: FailureKind) -> None:
    """Timeout num POST pode ter criado a mensagem. Repetir duplica."""
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(_request(HTTPMethod.POST), kind, 0) is False


@pytest.mark.parametrize(
    "kind",
    [FailureKind.NOT_SENT, FailureKind.AMBIGUOUS, FailureKind.SERVER_ERROR],
)
def test_post_retries_only_when_never_sent(kind: FailureKind) -> None:
    """Conexão recusada: o pedido não saiu. Repetir é seguro até pra POST."""
    expected = kind is FailureKind.NOT_SENT
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(_request(HTTPMethod.POST), kind, 0) is expected


# --------------------------------------------------------------------------
# Recusas
# --------------------------------------------------------------------------


@pytest.mark.parametrize("method", list(HTTPMethod))
def test_client_error_never_retries(method: HTTPMethod) -> None:
    """400/403/404: repetir só repete o mesmo erro, com atraso."""
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(_request(method), FailureKind.CLIENT_ERROR, 0) is False


@pytest.mark.parametrize("method", list(HTTPMethod))
def test_rate_limit_is_not_retried_by_policy(method: HTTPMethod) -> None:
    """429 é do rate limiter. Repetir cedo ignora a espera pedida."""
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(_request(method), FailureKind.RATE_LIMITED, 0) is False


@pytest.mark.parametrize("method", list(HTTPMethod))
def test_stops_at_max_retries(method: HTTPMethod) -> None:
    policy = RetryPolicy(max_retries=2)
    request = _request(method)
    kind = FailureKind.NOT_SENT
    assert policy.should_retry(request, kind, 0) is True
    assert policy.should_retry(request, kind, 1) is True
    assert policy.should_retry(request, kind, 2) is False


def test_zero_retries_never_retries() -> None:
    policy = RetryPolicy.none()
    assert policy.should_retry(_request(HTTPMethod.GET), FailureKind.NOT_SENT, 0) is False


# --------------------------------------------------------------------------
# Backoff
# --------------------------------------------------------------------------


def test_backoff_zero_base_is_immediate() -> None:
    policy = RetryPolicy(backoff_base=0.0)
    assert policy.backoff(0) == 0.0
    assert policy.backoff(5) == 0.0


def test_backoff_grows_exponentially() -> None:
    policy = RetryPolicy(backoff_base=1.0, backoff_factor=2.0, jitter=0.0)
    assert policy.backoff(0) == 1.0
    assert policy.backoff(1) == 2.0
    assert policy.backoff(2) == 4.0


def test_backoff_is_capped() -> None:
    """Sem teto, um servidor caído segura o cliente por minutos."""
    policy = RetryPolicy(backoff_base=10.0, backoff_factor=2.0, backoff_max=30.0, jitter=0.0)
    assert policy.backoff(10) == 30.0


def test_backoff_jitter_stays_within_bounds() -> None:
    """±10% de jitter espalha clientes que falharam no mesmo instante."""
    policy = RetryPolicy(backoff_base=10.0, backoff_factor=1.0, jitter=0.1)
    samples = [policy.backoff(0) for _ in range(200)]
    assert all(9.0 <= value <= 11.0 for value in samples)
    assert len(set(samples)) > 1, "jitter zerou — todos voltariam juntos"


def test_backoff_never_negative() -> None:
    """Jitter para baixo não pode virar espera negativa."""
    policy = RetryPolicy(backoff_base=0.1, backoff_factor=1.0, jitter=1.0)
    assert all(policy.backoff(0) >= 0.0 for _ in range(500))


# --------------------------------------------------------------------------
# Classificação de transporte
# --------------------------------------------------------------------------


def _req() -> httpx.Request:
    return httpx.Request("GET", "https://discord.com/api/v10/gateway/bot")


def test_connect_error_means_not_sent() -> None:
    exc = httpx.ConnectError("connection refused", request=_req())
    assert classify_transport_error(exc) is FailureKind.NOT_SENT


def test_connect_timeout_means_not_sent() -> None:
    """Conexão nunca estabelecida — nada chegou ao servidor."""
    exc = httpx.ConnectTimeout("timed out", request=_req())
    assert classify_transport_error(exc) is FailureKind.NOT_SENT


def test_read_timeout_is_ambiguous() -> None:
    """Enviado, resposta não veu. O servidor pode ter processado."""
    exc = httpx.ReadTimeout("timed out", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS


def test_write_timeout_is_ambiguous() -> None:
    exc = httpx.WriteTimeout("timed out", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS


def test_pool_timeout_is_ambiguous() -> None:
    exc = httpx.PoolTimeout("pool exhausted", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS


def test_read_error_is_ambiguous() -> None:
    exc = httpx.ReadError("connection broken", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS


def test_remote_protocol_error_is_ambiguous() -> None:
    """Servidor fechou no meio da troca — requisição já tinha saído."""
    exc = httpx.RemoteProtocolError("server closed", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS


def test_connect_timeout_is_not_confused_with_network_error() -> None:
    """Regressão: ConnectTimeout é subclasse de TimeoutException, e
    ConnectError é subclasse de NetworkError. Ordem errada no isinstance
    daria a classificação errada — e um POST receberia retry indevido."""
    assert classify_transport_error(httpx.ConnectTimeout("t", request=_req())) is (
        FailureKind.NOT_SENT
    )
    assert classify_transport_error(httpx.ConnectError("e", request=_req())) is (
        FailureKind.NOT_SENT
    )


def test_non_transport_error_returns_none() -> None:
    """Não é falha de trânsito: não tentar de novo."""
    assert classify_transport_error(ValueError("algo de outro")) is None


def test_http_status_error_returns_none() -> None:
    """`raise_for_status()` não é falha de transporte."""
    request = _req()
    response = httpx.Response(500, request=request)
    assert (
        classify_transport_error(httpx.HTTPStatusError("x", request=request, response=response))
        is None
    )


def test_unknown_request_error_defaults_to_ambiguous() -> None:
    """Qualquer RequestError é falha de trânsito. Padrão honesto."""
    exc = httpx.RequestError("qualquer coisa", request=_req())
    assert classify_transport_error(exc) is FailureKind.AMBIGUOUS
