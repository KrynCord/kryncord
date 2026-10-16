"""Testes de `kryncord.config`."""

from __future__ import annotations

import pytest

from kryncord import (
    CommandOptions,
    Config,
    EventOptions,
    GatewayConfig,
    HTTPConfig,
    Intents,
    ResponderOptions,
)


def _config(**kwargs: object) -> Config:
    return Config(intents=Intents.default(), **kwargs)  # type: ignore[arg-type]


def test_defaults_are_sane() -> None:
    config = _config()
    assert config.http.base_url == "https://discord.com/api"
    assert config.http.version == 10
    assert config.http.timeout == 30.0
    assert config.http.max_retries == 3
    assert config.gateway.max_reconnect_attempts == 5
    assert config.log_level == "INFO"


def test_config_is_immutable() -> None:
    config = _config()
    with pytest.raises(AttributeError):
        config.log_level = "DEBUG"  # type: ignore[misc]


def test_nested_configs_are_immutable() -> None:
    config = _config()
    with pytest.raises(AttributeError):
        config.http.timeout = 5.0  # type: ignore[misc]


def test_intents_are_required() -> None:
    with pytest.raises(TypeError):
        Config()  # type: ignore[call-arg]


def test_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match=r"http\.timeout precisa ser positivo"):
        _config(http=HTTPConfig(timeout=0))


def test_rejects_non_positive_timeout_negative() -> None:
    with pytest.raises(ValueError, match=r"http\.timeout precisa ser positivo"):
        _config(http=HTTPConfig(timeout=-1))


def test_rejects_negative_max_retries() -> None:
    with pytest.raises(ValueError, match=r"http\.max_retries não pode ser negativo"):
        _config(http=HTTPConfig(max_retries=-1))


def test_zero_max_retries_is_allowed() -> None:
    """Zero desliga a repetição — é escolha, não erro."""
    assert _config(http=HTTPConfig(max_retries=0)).http.max_retries == 0


def test_rejects_non_positive_connect_timeout() -> None:
    with pytest.raises(ValueError, match=r"gateway\.connect_timeout precisa ser positivo"):
        _config(gateway=GatewayConfig(connect_timeout=0))


def test_rejects_negative_max_reconnect_attempts() -> None:
    with pytest.raises(ValueError, match=r"gateway\.max_reconnect_attempts não pode ser negativo"):
        _config(gateway=GatewayConfig(max_reconnect_attempts=-1))


def test_zero_max_reconnect_attempts_is_allowed() -> None:
    """Zero = não reconectar. Extremo, mas é uma escolha."""
    assert (
        _config(gateway=GatewayConfig(max_reconnect_attempts=0)).gateway.max_reconnect_attempts == 0
    )


def test_rejects_keepalive_above_max_connections() -> None:
    with pytest.raises(ValueError, match="não pode ser maior que"):
        _config(http=HTTPConfig(max_connections=5, max_keepalive_connections=10))


def test_allows_keepalive_equal_to_max_connections() -> None:
    config = _config(http=HTTPConfig(max_connections=5, max_keepalive_connections=5))
    assert config.http.max_keepalive_connections == 5


def test_configs_are_distinct_instances() -> None:
    """Dois Config não compartilham o HTTPConfig — frozen não é sinônimo de singleton."""
    first = _config()
    second = _config()
    assert first.http is not second.http


# ---------------------------------------------------------------------------
# Options — 0010
# ---------------------------------------------------------------------------


def test_options_vivem_no_config() -> None:
    """Um caminho só: `Config(commands=...)`, não `Client(commands=...)`.
    Dois caminhos para o mesmo dado são duas fontes de verdade que
    precisam concordar para sempre."""
    config = _config(
        commands=CommandOptions(guilds=(1, 2)),
        responders=ResponderOptions(),
        events=EventOptions(dispatch_mode="concurrent"),
    )

    assert config.commands.guilds == (1, 2)
    assert config.responders.middleware is None
    assert config.events.dispatch_mode == "concurrent"


def test_options_tem_default_seguro() -> None:
    """Ninguém precisa saber o que é middleware para ligar um bot."""
    config = _config()

    assert config.commands.default_member_permissions_resolved is None
    assert config.commands.guilds == ()
    assert config.commands.verbose is False
    assert config.commands.middleware is None
    assert config.responders.on_error is None
    assert config.events.middleware is None
    assert config.events.dispatch_mode == "sequential"


def test_guilds_e_tupla_de_int() -> None:
    """Snowflake é `int` desde o 0006. Aceitar lista e virar tupla é
    convenção; aceitar `str` seria trazer de volta a confusão antiga."""
    config = _config(commands=CommandOptions(guilds=[123, 456]))  # type: ignore[arg-type]

    assert config.commands.guilds == (123, 456)
    assert all(isinstance(g, int) for g in config.commands.guilds)


def test_dispatch_mode_invalido_e_erro() -> None:
    """Atenção: `bool` é subclasse de `int`, mas aqui o campo é
    `Literal` — qualquer string fora das duas é erro na construção."""
    with pytest.raises(ValueError, match="dispatch_mode"):
        _config(events=EventOptions(dispatch_mode="paralelo"))  # type: ignore[arg-type]


def test_opcoes_sao_congeladas() -> None:
    """Congelado é o contrato da biblioteca inteira — Options não é a
    exceção. Mudar depois de construído seria mudar o que o Client já
    leu."""
    options = CommandOptions()

    with pytest.raises(AttributeError):
        options.verbose = True  # type: ignore[misc]


def test_dois_configs_nao_compartilham_options() -> None:
    """Mesmo motivo do HTTPConfig: default_factory não é singleton."""
    first = _config()
    second = _config()

    assert first.commands is not second.commands
    assert first.events is not second.events
