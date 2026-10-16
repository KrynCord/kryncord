"""Testes de `kryncord.gateway.reconnect` — a tabela que decide a vida.

A tabela inteira veio do ``WebSocketShard.onClose`` do discord.js, e os
testes abaixo a fixam linha a linha. Se um dia alguém "melhorar" uma
delas, o teste é o que avisa que a mudança tem custo real: 4008 virar
resume é um bot em loop de rate limit, 1000 virar resume é um
round-trip pago para levar ``invalid_session`` de volta.
"""

from __future__ import annotations

import pytest

from kryncord.gateway.reconnect import (
    RESUMING_CODE,
    ReconnectPolicy,
    Recovery,
    classify_close,
)

_FATAL = [4004, 4010, 4011, 4012, 4013, 4014]
_IDENTIFY = [1000, 4003, 4005, 4007, 4008]
_RESUME = [4000, 4001, 4002, 4009, RESUMING_CODE]


# --------------------------------------------------------------------------
# classify_close — a tabela
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", _FATAL)
def test_fatal_codes_stop_forever(code: int) -> None:
    """4004 e 4010–4014: reconectar é só queimar rate limit do Gateway."""
    decision = classify_close(code)
    assert decision.recovery is Recovery.FATAL
    assert decision.code == code
    assert decision.reason, "a decisão precisa virar mensagem de log legível"


@pytest.mark.parametrize("code", _IDENTIFY)
def test_identify_codes_kill_the_session(code: int) -> None:
    decision = classify_close(code)
    assert decision.recovery is Recovery.IDENTIFY


@pytest.mark.parametrize("code", _RESUME)
def test_resume_codes_keep_the_session(code: int) -> None:
    decision = classify_close(code)
    assert decision.recovery is Recovery.RESUME


def test_none_is_a_normal_close_and_needs_a_new_identify() -> None:
    """`None` = fechamento sem código. A sessão foi encerrada de propósito.

    Este é o caso que parece errado: "fechamento normal" soa como
    "retoma". Soa, mas é identify — tentar resume devolve
    ``invalid_session`` e paga um round-trip para descobrir o óbvio.
    """
    assert classify_close(None).recovery is Recovery.IDENTIFY


def test_1000_is_also_a_new_identify() -> None:
    assert classify_close(1000).recovery is Recovery.IDENTIFY


def test_unknown_code_resumes_by_default() -> None:
    """Código fora de tabela: errar para retomar perde eventos no pior caso."""
    decision = classify_close(4999)
    assert decision.recovery is Recovery.RESUME
    assert "4999" in decision.reason


def test_unknown_code_with_network_error_identifies() -> None:
    """Com erro de rede antes, a sessão estourou no caminho — resume é
    um round-trip que termina em `invalid_session`."""
    decision = classify_close(4999, network_error=True)
    assert decision.recovery is Recovery.IDENTIFY


@pytest.mark.parametrize("code", _FATAL)
def test_network_error_does_not_soften_a_fatal_code(code: int) -> None:
    """FATAL é sempre explícito. Uma falsa positiva aqui é bot que desiste."""
    assert classify_close(code, network_error=True).recovery is Recovery.FATAL


def test_resuming_code_is_4200() -> None:
    """É o código que nós mesmos mandamos ao detectar zumbi — precisa
    classificar como resume, ou a detecção de zumbi viraria perda de sessão."""
    assert RESUMING_CODE == 4200
    assert classify_close(RESUMING_CODE).recovery is Recovery.RESUME


def test_recovery_will_resume_property() -> None:
    assert Recovery.RESUME.will_resume is True
    assert Recovery.IDENTIFY.will_resume is False
    assert Recovery.FATAL.will_resume is False


# --------------------------------------------------------------------------
# ReconnectPolicy — backoff e teto
# --------------------------------------------------------------------------


def test_delay_grows_exponentially() -> None:
    policy = ReconnectPolicy(base_delay=1.0, jitter=0.0)
    assert policy.delay(1) == 1.0
    assert policy.delay(2) == 2.0
    assert policy.delay(3) == 4.0
    assert policy.delay(4) == 8.0


def test_delay_is_capped() -> None:
    policy = ReconnectPolicy(base_delay=1.0, max_delay=10.0, jitter=0.0)
    assert policy.delay(10) == 10.0
    assert policy.delay(50) == 10.0


def test_equal_jitter_guarantees_at_least_the_fixed_half() -> None:
    """Delay totalmente aleatório pode devolver 0 e não protege nada."""
    policy = ReconnectPolicy(base_delay=2.0, jitter=0.5, random=lambda: 0.0)
    assert policy.delay(1) == 1.0  # metade fixa, metade sorteada em 0

    policy = ReconnectPolicy(base_delay=2.0, jitter=0.5, random=lambda: 1.0)
    assert policy.delay(1) == 2.0  # topo da faixa


def test_zero_jitter_is_the_full_delay() -> None:
    policy = ReconnectPolicy(base_delay=3.0, jitter=0.0)
    assert policy.delay(1) == 3.0


def test_attempts_are_consecutive_not_total() -> None:
    policy = ReconnectPolicy(max_attempts=2)
    assert policy.should_retry(1) is True
    assert policy.should_retry(2) is True
    assert policy.should_retry(3) is False
    # Chegar ao READY zera a contagem — o chamador volta para a 1.


def test_max_attempts_zero_disables_the_feature() -> None:
    policy = ReconnectPolicy(max_attempts=0)
    assert policy.should_retry(1) is False


def test_max_attempts_none_means_forever() -> None:
    """É o que se quer com "manter o bot ligado": manutenção do Discord
    não pode matar o processo."""
    policy = ReconnectPolicy(max_attempts=None)
    assert policy.should_retry(1) is True
    assert policy.should_retry(10_000) is True


@pytest.mark.parametrize("attempt", [0, -1])
def test_delay_rejects_non_1_indexed(attempt: int) -> None:
    with pytest.raises(ValueError, match="1-indexed"):
        ReconnectPolicy().delay(attempt)


def test_invalid_configuration_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="base_delay"):
        ReconnectPolicy(base_delay=0.0)
    with pytest.raises(ValueError, match="max_delay"):
        ReconnectPolicy(base_delay=10.0, max_delay=5.0)
    with pytest.raises(ValueError, match="jitter"):
        ReconnectPolicy(jitter=1.5)
    with pytest.raises(ValueError, match="max_attempts"):
        ReconnectPolicy(max_attempts=-1)
