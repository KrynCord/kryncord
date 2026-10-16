"""Testes de `kryncord.intents`."""

from __future__ import annotations

import pytest

from kryncord import Intents


def test_default_excludes_privileged() -> None:
    default = Intents.default()
    assert default & Intents.GUILDS
    assert not default & Intents.GUILD_MEMBERS
    assert not default & Intents.GUILD_PRESENCES
    assert not default & Intents.MESSAGE_CONTENT


def test_privileged_is_exactly_three() -> None:
    privileged = Intents.privileged()
    assert privileged == (Intents.GUILD_MEMBERS | Intents.GUILD_PRESENCES | Intents.MESSAGE_CONTENT)


def test_all_non_privileged_has_no_privileged() -> None:
    all_free = Intents.all_non_privileged()
    assert all_free & Intents.privileged() == 0


def test_all_non_privileged_includes_guilds() -> None:
    assert Intents.all_non_privileged() & Intents.GUILDS


def test_missing_privileged_empty_when_granted() -> None:
    requested = Intents.GUILD_MEMBERS | Intents.GUILDS
    enabled = Intents.GUILD_MEMBERS | Intents.GUILDS
    assert requested.missing_privileged(enabled) == []


def test_missing_privileged_lists_names() -> None:
    requested = Intents.GUILD_MEMBERS | Intents.MESSAGE_CONTENT | Intents.GUILDS
    enabled = Intents.GUILDS
    missing = requested.missing_privileged(enabled)
    assert sorted(missing) == ["GUILD_MEMBERS", "MESSAGE_CONTENT"]


def test_missing_privileged_ignores_non_privileged() -> None:
    """Pedir GUILD_MESSAGES sem conceder não é erro — não é privileged."""
    assert Intents.GUILD_MESSAGES.missing_privileged(Intents(0)) == []


def test_validate_passes_when_enabled() -> None:
    Intents.GUILD_MEMBERS.validate(Intents.GUILD_MEMBERS)


def test_validate_raises_when_disabled() -> None:
    with pytest.raises(ValueError, match="Privileged Gateway Intents"):
        Intents.GUILD_MEMBERS.validate(Intents(0))


def test_validate_message_names_the_intent() -> None:
    with pytest.raises(ValueError, match="GUILD_MEMBERS"):
        Intents.GUILD_MEMBERS.validate(Intents(0))


def test_validate_passes_when_enabled_is_none() -> None:
    """Sem o conjunto habilitado, não temos como checar — não levanta."""
    Intents.GUILD_MEMBERS.validate(None)


def test_to_payload_is_int() -> None:
    assert Intents.GUILDS.to_payload() == 1
    assert isinstance(Intents.GUILDS.to_payload(), int)


def test_to_payload_combines_bits() -> None:
    combined = Intents.GUILDS | Intents.GUILD_MESSAGES
    assert combined.to_payload() == (1 << 0) | (1 << 9)


def test_official_bit_values() -> None:
    """Os bits são contrato de protocolo — regressão aqui quebra o bot em silêncio."""
    assert Intents.GUILDS == 1 << 0
    assert Intents.GUILD_MEMBERS == 1 << 1
    assert Intents.GUILD_MODERATION == 1 << 2
    assert Intents.GUILD_EMOJIS_AND_STICKERS == 1 << 3
    assert Intents.GUILD_VOICE_STATES == 1 << 7
    assert Intents.GUILD_PRESENCES == 1 << 8
    assert Intents.GUILD_MESSAGES == 1 << 9
    assert Intents.MESSAGE_CONTENT == 1 << 15
    assert Intents.GUILD_SCHEDULED_EVENTS == 1 << 16


def test_no_two_intents_share_a_bit() -> None:
    """Alias silencioso: dois membros com o mesmo valor viram um só no Enum."""
    values = [intent.value for intent in Intents]
    assert len(values) == len(set(values)), "bit duplicado — haveria alias no Enum"


def test_guild_emojis_and_guild_members_are_distinct() -> None:
    """Regressão específica: ambos eram 1 << 1 na versão original."""
    assert Intents.GUILD_EMOJIS_AND_STICKERS != Intents.GUILD_MEMBERS
    assert Intents.GUILD_EMOJIS_AND_STICKERS & Intents.GUILD_MEMBERS == 0
