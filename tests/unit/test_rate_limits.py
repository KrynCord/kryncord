"""Testes de `kryncord.http.rate_limits` — headers, cota e 429."""

from __future__ import annotations

import pytest

from kryncord.http.rate_limits import (
    BucketState,
    GlobalRateLimit,
    RateLimitHeaders,
    normalize_offset,
    parse_429,
)
from kryncord.http.response import Response
from tests.conftest import FakeClock


def _response(*headers: tuple[str, str], status: int = 200, body: bytes = b"") -> Response:
    return Response.of(status, list(headers), body)


def _full_headers() -> Response:
    return _response(
        ("X-RateLimit-Limit", "5"),
        ("X-RateLimit-Remaining", "3"),
        ("X-RateLimit-Reset-After", "12.5"),
        ("X-RateLimit-Bucket", "abc123"),
        ("X-RateLimit-Scope", "user"),
    )


# --------------------------------------------------------------------------
# Leitura de headers
# --------------------------------------------------------------------------


def test_reads_all_rate_limit_headers() -> None:
    headers = RateLimitHeaders.from_response(_full_headers())
    assert headers.limit == 5
    assert headers.remaining == 3
    assert headers.reset_after == 12.5
    assert headers.bucket == "abc123"
    assert headers.scope == "user"


def test_header_lookup_is_case_insensitive() -> None:
    """O httpx preserva o caso original; o RFC manda comparar sem caixa."""
    response = _response(("x-ratelimit-limit", "5"), ("X-RATELIMIT-REMAINING", "1"))
    headers = RateLimitHeaders.from_response(response)
    assert headers.limit == 5
    assert headers.remaining == 1


def test_missing_headers_stay_none_not_zero() -> None:
    """Zero significaria 'cota esgotada'. Ausente significa 'sem info'."""
    headers = RateLimitHeaders.from_response(_response())
    assert headers.limit is None
    assert headers.remaining is None
    assert headers.reset_after is None
    assert headers.bucket is None


def test_scope_defaults_to_user() -> None:
    """`user` é o escopo comum; omitir o header não pode mudar a semântica."""
    assert RateLimitHeaders.from_response(_response()).scope == "user"


def test_malformed_number_does_not_raise() -> None:
    """Header corrompido por proxy não pode derrubar a requisição."""
    headers = RateLimitHeaders.from_response(_response(("X-RateLimit-Reset-After", "not-a-number")))
    assert headers.reset_after is None


def test_fractional_remaining_is_truncated() -> None:
    """Discord manda inteiro, mas 3.0 tem que virar 3, não 3.0."""
    headers = RateLimitHeaders.from_response(_response(("X-RateLimit-Remaining", "3.0")))
    assert headers.remaining == 3
    assert isinstance(headers.remaining, int)


def test_global_flag_is_presence_based() -> None:
    """Só a presença importa; o valor não é lido."""
    assert RateLimitHeaders.from_response(_response(("X-RateLimit-Global", "true"))).is_global
    assert not RateLimitHeaders.from_response(_response()).is_global


# --------------------------------------------------------------------------
# Estado do bucket
# --------------------------------------------------------------------------


def test_update_applies_only_present_fields() -> None:
    """Resposta sem headers não zera um bucket que estava bom."""
    clock = FakeClock()
    state = BucketState(clock=clock, limit=5, remaining=4, reset_at=clock() + 10)
    state.update(RateLimitHeaders.from_response(_response()))
    assert state.remaining == 4
    assert state.limit == 5


def test_update_sets_reset_relative_to_clock() -> None:
    clock = FakeClock(start=1000.0)
    state = BucketState(clock=clock)
    state.update(RateLimitHeaders.from_response(_full_headers()))
    assert state.reset_at == 1012.5
    assert state.seconds_until_reset == pytest.approx(12.5)


def test_exhausted_is_false_before_window_ends() -> None:
    clock = FakeClock()
    state = BucketState(clock=clock, remaining=0, reset_at=clock() + 5)
    assert state.exhausted is True


def test_exhausted_clears_after_reset() -> None:
    clock = FakeClock()
    state = BucketState(clock=clock, remaining=0, reset_at=clock() + 5)
    clock.advance(5.1)
    assert state.exhausted is False


def test_exhausted_is_false_when_remaining_positive() -> None:
    """Ter cota é o que importa, mesmo com a janela no fim."""
    clock = FakeClock()
    state = BucketState(clock=clock, remaining=1, reset_at=clock() - 1)
    assert state.exhausted is False


def test_seconds_until_reset_never_goes_negative() -> None:
    clock = FakeClock()
    state = BucketState(clock=clock, reset_at=clock() - 100)
    assert state.seconds_until_reset == 0.0


def test_force_limit_blocks_without_headers() -> None:
    clock = FakeClock()
    state = BucketState(clock=clock, remaining=5)
    state.force_limit(30.0)
    assert state.exhausted is True
    clock.advance(30.1)
    assert state.exhausted is False


def test_force_limit_ignores_negative_seconds() -> None:
    """Espera negativa dormiria com valor inválido."""
    clock = FakeClock()
    state = BucketState(clock=clock)
    state.force_limit(-10)
    assert state.reset_at == clock()


def test_update_can_reenable_a_bucket() -> None:
    """Depois de novo header com cota, o bucket volta a servir."""
    clock = FakeClock()
    state = BucketState(clock=clock)
    state.force_limit(60)
    state.update(RateLimitHeaders.from_response(_full_headers()))
    assert state.remaining == 3
    assert state.exhausted is False


def test_snapshot_is_log_safe() -> None:
    clock = FakeClock()
    state = BucketState(clock=clock, limit=5, remaining=2, bucket_hash="abc")
    snap = state.snapshot()
    assert snap["bucket"] == "abc"
    assert snap["remaining"] == 2
    assert isinstance(snap["seconds_until_reset"], float)


# --------------------------------------------------------------------------
# Limite global
# --------------------------------------------------------------------------


def test_global_consumes_within_window() -> None:
    clock = FakeClock()
    limit = GlobalRateLimit(requests_per_second=3, clock=clock)
    limit.consume()
    limit.consume()
    assert limit.remaining == 1
    assert limit.exhausted is False


def test_global_exhausts_at_zero() -> None:
    clock = FakeClock()
    limit = GlobalRateLimit(requests_per_second=2, clock=clock)
    limit.consume()
    limit.consume()
    assert limit.exhausted is True


def test_global_window_resets_after_one_second() -> None:
    clock = FakeClock()
    limit = GlobalRateLimit(requests_per_second=2, clock=clock)
    limit.consume()
    limit.consume()
    assert limit.exhausted is True
    clock.advance(1.1)
    assert limit.exhausted is False
    assert limit.remaining == 2


def test_global_consume_reopens_window_when_expired() -> None:
    clock = FakeClock()
    limit = GlobalRateLimit(requests_per_second=5, clock=clock)
    limit.consume()
    clock.advance(1.1)
    limit.consume()
    assert limit.remaining == 4


def test_global_force_limit_sets_remaining_zero() -> None:
    clock = FakeClock()
    limit = GlobalRateLimit(requests_per_second=50, clock=clock)
    limit.force_limit(10.0)
    assert limit.exhausted is True
    assert limit.seconds_until_reset == pytest.approx(10.0)


# --------------------------------------------------------------------------
# parse_429
# --------------------------------------------------------------------------


def test_429_prefers_header_retry_after() -> None:
    response = _response(
        ("Retry-After", "2.5"), status=429, body=b'{"retry_after": 99.0, "global": false}'
    )
    retry_after, is_global = parse_429(response)
    assert retry_after == 2.5
    assert is_global is False


def test_429_falls_back_to_body_when_header_absent() -> None:
    response = _response(status=429, body=b'{"retry_after": 4.25, "global": false}')
    retry_after, is_global = parse_429(response)
    assert retry_after == 4.25
    assert is_global is False


def test_429_reads_global_from_body() -> None:
    """O header pode faltar num proxy; o corpo é o contrato da API."""
    response = _response(status=429, body=b'{"retry_after": 1.0, "global": true}')
    _, is_global = parse_429(response)
    assert is_global is True


def test_429_global_from_header_wins_even_if_body_says_false() -> None:
    response = _response(
        ("X-RateLimit-Global", "true"), status=429, body=b'{"retry_after": 1.0, "global": false}'
    )
    _, is_global = parse_429(response)
    assert is_global is True


def test_429_without_any_signal_defaults_to_one_second() -> None:
    """Sem tempo, reaproveitar em loop. Espera curta é a saída menos pior."""
    response = _response(status=429, body=b"not json")
    retry_after, _ = parse_429(response)
    assert retry_after == 1.0


def test_429_with_html_body_does_not_raise() -> None:
    """Proxy de erro devolve HTML. Tem que cair no default, não estourar."""
    response = _response(status=429, body=b"<html>502 Bad Gateway</html>")
    retry_after, _ = parse_429(response)
    assert retry_after == 1.0


def test_429_bool_retry_after_is_ignored() -> None:
    """`true` é subclasse de int em Python — pegaria como 1.0 por acidente."""
    response = _response(status=429, body=b'{"retry_after": true}')
    retry_after, _ = parse_429(response)
    assert retry_after == 1.0


def test_429_seconds_are_seconds_not_milliseconds() -> None:
    """A v6 mandava ms no corpo. Interpretar 64500 ms como s dormiria 18h."""
    response = _response(status=429, body=b'{"retry_after": 64.57}')
    retry_after, _ = parse_429(response)
    assert retry_after == pytest.approx(64.57)
    assert retry_after < 100


# --------------------------------------------------------------------------
# offset
# --------------------------------------------------------------------------


@pytest.mark.parametrize("offset_ms, expected", [(50, 0.05), (0, 0.0), (1000, 1.0)])
def test_offset_converts_ms_to_seconds(offset_ms: float, expected: float) -> None:
    assert normalize_offset(offset_ms) == pytest.approx(expected)


def test_negative_offset_clamps_to_zero() -> None:
    """Offset negativo adiantaria o reset — pior que não ter offset."""
    assert normalize_offset(-100) == 0.0
