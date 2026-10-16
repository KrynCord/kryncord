"""Testes de `kryncord.enums`."""

from __future__ import annotations

from kryncord import (
    ApplicationCommandType,
    CloseCode,
    GatewayOpcode,
    InteractionResponseType,
    InteractionType,
    Permission,
    Permissions,
    permission_names,
)


def test_gateway_opcodes_have_official_values() -> None:
    assert GatewayOpcode.DISPATCH == 0
    assert GatewayOpcode.HEARTBEAT == 1
    assert GatewayOpcode.IDENTIFY == 2
    assert GatewayOpcode.RESUME == 6
    assert GatewayOpcode.INVALID_SESSION == 9
    assert GatewayOpcode.HELLO == 10
    assert GatewayOpcode.HEARTBEAT_ACK == 11


def test_interaction_types_have_official_values() -> None:
    assert InteractionType.PING == 1
    assert InteractionType.APPLICATION_COMMAND == 2
    assert InteractionType.MESSAGE_COMPONENT == 3
    assert InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE == 4
    assert InteractionType.MODAL_SUBMIT == 5


def test_interaction_response_types_have_official_values() -> None:
    assert InteractionResponseType.PONG == 1
    assert InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE == 4
    assert InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE == 5
    assert InteractionResponseType.DEFERRED_UPDATE_MESSAGE == 6
    assert InteractionResponseType.UPDATE_MESSAGE == 7
    assert InteractionResponseType.MODAL == 9


def test_application_command_types_have_official_values() -> None:
    assert ApplicationCommandType.CHAT_INPUT == 1
    assert ApplicationCommandType.USER == 2
    assert ApplicationCommandType.MESSAGE == 3


# --------------------------------------------------------------------------
# CloseCode
# --------------------------------------------------------------------------
#
# Não há teste de decisão de retomada aqui, e isso é de propósito: a
# pergunta "resume ou identify?" tem três respostas (não duas), e quem
# responde é `kryncord.gateway.reconnect.classify_close`. Ver
# `test_gateway_reconnect.py`.


def test_close_codes_have_official_values() -> None:
    assert CloseCode.UNKNOWN_ERROR == 4000
    assert CloseCode.AUTHENTICATION_FAILED == 4004
    assert CloseCode.SESSION_TIMEOUT == 4009
    assert CloseCode.DISALLOWED_INTENTS == 4014


# --------------------------------------------------------------------------
# Permission
# --------------------------------------------------------------------------


def test_permission_values_are_api_compatible() -> None:
    """O Discord aceita o nome em snake_case no payload de permissão."""
    assert Permission.SEND_MESSAGES == "send_messages"
    assert Permission.ADMINISTRATOR == "administrator"
    assert Permission.CONNECT == "connect"


def test_permission_names_returns_all_values() -> None:
    names = permission_names()
    assert len(names) == len(Permission)
    assert "send_messages" in names
    assert "administrator" in names


def test_permission_names_are_unique() -> None:
    names = permission_names()
    assert len(names) == len(set(names))


def test_every_permission_value_is_snake_case() -> None:
    for permission in Permission:
        assert permission.value == permission.value.lower(), permission.name
        assert " " not in permission.value
        assert permission.value.isidentifier() or "_" in permission.value


# --------------------------------------------------------------------------
# Paridade Permission x Permissions
# --------------------------------------------------------------------------


def test_as_duas_tabelas_tem_os_mesmos_membros() -> None:
    """`Permission` (StrEnum) é a visão de string da API; `Permissions`
    (IntFlag) é a de bitfield. Duas tabelas para o mesmo conceito
    derivam — este teste é o que impede a derivação acontecer.

    Sem ele, adicionar `SEND_FAX` num dos lados e esquecer o outro
    não quebra nada: só fica inacessível pela outra forma.
    """
    nomes_str = {p.name for p in Permission}
    nomes_bit = {p.name for p in Permissions}

    faltando_em_str = nomes_bit - nomes_str
    faltando_em_bit = nomes_str - nomes_bit

    assert not faltando_em_str, f"em Permission(StrEnum): {sorted(faltando_em_str)}"
    assert not faltando_em_bit, f"em Permissions(IntFlag): {sorted(faltando_em_bit)}"


def test_permutations_e_bits_combinam_sem_colisao() -> None:
    """Uma colisão de bit faria `A | B` virar um só, e o parse passaria
    errado sem nunca reclamar — exatamente o tipo de falha silenciosa
    que este módulo existe para evitar."""
    valores = [p.value for p in Permissions]
    assert len(valores) == len(set(valores))

    for p in Permissions:
        assert p.value > 0 and (p.value & (p.value - 1)) == 0, p.name


def test_parse_permissions_cobre_os_nomes_do_str_enum() -> None:
    """Todo nome que a `Permission` conhece tem que ser parseável pelo
    `Permissions` — senão `default_member_permissions="manage_guild"` e
    `Permission.MANAGE_GUILD` dariam errado por motivos diferentes."""
    from kryncord.permissions import parse_permissions

    for p in Permission:
        resultado = parse_permissions(p.name)
        assert resultado.name == p.name
