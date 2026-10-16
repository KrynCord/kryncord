"""Testes de `kryncord.http.routes` — generalização de rota em bucket."""

from __future__ import annotations

import pytest

from kryncord.http.routes import (
    BURST_MAJOR,
    DISCORD_EPOCH_MS,
    GLOBAL_MAJOR,
    generate_route_data,
    snowflake_timestamp_ms,
)

#: Timestamp fixo para os testes — nunca o relógio da máquina.
NOW = 1_700_000_000_000
DAY_MS = 24 * 60 * 60 * 1000


def snowflake(age_ms: int, *, now: int = NOW) -> int:
    """Monta um snowflake com `age_ms` de idade, a partir do epoch fixo."""
    return ((now - age_ms) - DISCORD_EPOCH_MS) << 22


CHANNEL_ID = str(snowflake(0))
MESSAGE_ID = str(snowflake(DAY_MS))


# --------------------------------------------------------------------------
# Major parameter
# --------------------------------------------------------------------------


def test_channel_id_is_major_parameter() -> None:
    data = generate_route_data("GET", f"/channels/{CHANNEL_ID}")
    assert data.major_parameter == CHANNEL_ID


def test_guild_id_is_major_parameter() -> None:
    data = generate_route_data("GET", f"/guilds/{CHANNEL_ID}/members")
    assert data.major_parameter == CHANNEL_ID


def test_route_without_major_falls_back_to_global() -> None:
    data = generate_route_data("GET", "/gateway/bot")
    assert data.major_parameter == GLOBAL_MAJOR


def test_webhook_id_and_token_together_are_major() -> None:
    """Webhook é identificado pelo par id/token — trocar só o id não basta."""
    data = generate_route_data("POST", f"/webhooks/{CHANNEL_ID}/somesecret")
    assert data.major_parameter == f"{CHANNEL_ID}/somesecret"


def test_two_channels_produce_different_majors() -> None:
    other = str(snowflake(0) + 1)
    first = generate_route_data("GET", f"/channels/{CHANNEL_ID}/messages")
    second = generate_route_data("GET", f"/channels/{other}/messages")
    assert first.major_parameter != second.major_parameter


def test_two_channels_share_the_same_bucket_route() -> None:
    """Major separa instâncias; a rota generalizada é a mesma."""
    other = str(snowflake(0) + 1)
    first = generate_route_data("GET", f"/channels/{CHANNEL_ID}/messages")
    second = generate_route_data("GET", f"/channels/{other}/messages")
    assert first.bucket_route == second.bucket_route == "/channels/:id/messages"


# --------------------------------------------------------------------------
# Generalização da rota
# --------------------------------------------------------------------------


def test_snowflakes_become_id() -> None:
    data = generate_route_data("GET", f"/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}")
    assert data.bucket_route == "/channels/:id/messages/:id"


def test_original_route_is_preserved() -> None:
    """A URL real não pode levar :id — só a chave do bucket."""
    data = generate_route_data("GET", f"/channels/{CHANNEL_ID}/messages")
    assert data.original == f"/channels/{CHANNEL_ID}/messages"
    assert data.bucket_route == "/channels/:id/messages"


def test_short_numbers_are_not_treated_as_snowflakes() -> None:
    """`/commands/1` tem 1 dígito — não é id do Discord, não vira :id."""
    data = generate_route_data("GET", "/commands/1")
    assert data.bucket_route == "/commands/1"


def test_reaction_under_seven_day_marker_is_still_generalized() -> None:
    """Fora do padrão snowflake, o segmento após /reactions/ vira :reaction."""
    # Um "id" de 3 dígitos não é snowflake, mas ainda assim é generalizado
    # pela regra de reactions — as duas regras são independentes.
    data = generate_route_data("GET", f"/channels/{CHANNEL_ID}/reactions/123")
    assert data.bucket_route == "/channels/:id/reactions/:reaction"


def test_reactions_generalize_to_a_single_bucket() -> None:
    """Todas as reações de uma mensagem caem no mesmo bucket."""
    emoji = "👍"
    data = generate_route_data(
        "GET", f"/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}/reactions/{emoji}/@me"
    )
    assert data.bucket_route.endswith("/reactions/:reaction")


def test_webhook_token_is_generalized() -> None:
    data = generate_route_data("POST", f"/webhooks/{CHANNEL_ID}/secrettoken")
    assert data.bucket_route == "/webhooks/:id/:token"


def test_route_with_multiple_ids_generalizes_all() -> None:
    data = generate_route_data("GET", f"/guilds/{CHANNEL_ID}/members/{MESSAGE_ID}")
    assert data.bucket_route == "/guilds/:id/members/:id"


# --------------------------------------------------------------------------
# Burst (callback de interação)
# --------------------------------------------------------------------------


def test_interaction_callback_is_burst() -> None:
    data = generate_route_data("POST", "/interactions/123456789012345678/abcdef/callback")
    assert data.major_parameter == BURST_MAJOR
    assert data.is_burst is True


def test_interaction_callback_has_canonical_bucket_route() -> None:
    data = generate_route_data("POST", "/interactions/123456789012345678/abcdef/callback")
    assert data.bucket_route == "/interactions/:id/:token/callback"


def test_regular_route_is_not_burst() -> None:
    data = generate_route_data("GET", f"/channels/{CHANNEL_ID}")
    assert data.is_burst is False


def test_interaction_callback_elsewhere_is_not_burst() -> None:
    """/interactions/... sem /callback no fim é rota comum."""
    data = generate_route_data("GET", "/interactions/123456789012345678")
    assert data.is_burst is False


# --------------------------------------------------------------------------
# Mensagem antiga (bucket separado)
# --------------------------------------------------------------------------


def _delete_url(message_age_ms: int) -> str:
    return f"/channels/{CHANNEL_ID}/messages/{snowflake(message_age_ms)}"


def test_old_message_delete_gets_its_own_bucket() -> None:
    data = generate_route_data("DELETE", _delete_url(15 * DAY_MS), now_ms=NOW)
    assert data.bucket_route == "/channels/:id/messages/:id/Delete Old Message"


def test_recent_message_delete_uses_normal_bucket() -> None:
    data = generate_route_data("DELETE", _delete_url(1 * DAY_MS), now_ms=NOW)
    assert data.bucket_route == "/channels/:id/messages/:id"


def test_boundary_exactly_fourteen_days_is_recent() -> None:
    """14 dias exatos ainda é 'recente': o corte é `>`."""
    data = generate_route_data("DELETE", _delete_url(14 * DAY_MS), now_ms=NOW)
    assert data.bucket_route == "/channels/:id/messages/:id"


def test_old_message_rule_only_applies_to_delete() -> None:
    """GET de mensagem antiga não ganha bucket separado."""
    url = f"/channels/{CHANNEL_ID}/messages/{snowflake(15 * DAY_MS)}"
    data = generate_route_data("GET", url, now_ms=NOW)
    assert data.bucket_route == "/channels/:id/messages/:id"


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------


def test_snowflake_timestamp_roundtrip() -> None:
    """Montar e ler um snowflake tem que devolver o mesmo instante."""
    built = snowflake(0)
    assert snowflake_timestamp_ms(built) == NOW


def test_route_data_is_frozen() -> None:
    data = generate_route_data("GET", "/gateway/bot")
    with pytest.raises(AttributeError):
        data.bucket_route = "/outro"  # type: ignore[misc]


def test_route_data_is_hashable() -> None:
    """É usada como chave de dict no gerenciador de buckets."""
    first = generate_route_data("GET", f"/channels/{CHANNEL_ID}")
    second = generate_route_data("GET", f"/channels/{CHANNEL_ID}")
    assert first == second
    assert len({first, second}) == 1
