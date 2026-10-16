"""Testes do pacote público: import, versão e hierarquia de erros."""

from __future__ import annotations

from importlib import metadata

import kryncord
from kryncord import (
    CommandDefinitionError,
    DefinitionError,
    DiscordAPIError,
    EventDefinitionError,
    GatewayError,
    HTTPError,
    KrynCordError,
    LifecycleError,
    RateLimitError,
    ResponderDefinitionError,
    SessionInvalidError,
)


def test_version_is_exposed() -> None:
    # `version.py` é a única fonte da versão, e o `pyproject.toml` tem que
    # dizer a mesma coisa — senão o `pip install kryncord` instalaria um
    # número diferente do que o código afirma ser. Este teste é o que pega
    # "atualizou um e esqueceu o outro" no bump de versão.
    assert kryncord.__version__ == metadata.version("kryncord")


def test_all_entries_are_exported() -> None:
    for name in kryncord.__all__:
        assert hasattr(kryncord, name), f"__all__ declara {name!r}, mas o atributo não existe"


def test_all_has_no_duplicates() -> None:
    assert len(kryncord.__all__) == len(set(kryncord.__all__))


def test_every_error_descends_from_kryncord_error() -> None:
    for cls in (
        DefinitionError,
        CommandDefinitionError,
        ResponderDefinitionError,
        EventDefinitionError,
        HTTPError,
        RateLimitError,
        DiscordAPIError,
        GatewayError,
        SessionInvalidError,
        LifecycleError,
    ):
        assert issubclass(cls, KrynCordError), f"{cls.__name__} não descende de KrynCordError"


def test_definition_errors_form_a_hierarchy() -> None:
    for cls in (CommandDefinitionError, ResponderDefinitionError, EventDefinitionError):
        assert issubclass(cls, DefinitionError)


def test_http_errors_form_a_hierarchy() -> None:
    for cls in (RateLimitError, DiscordAPIError):
        assert issubclass(cls, HTTPError)


def test_gateway_errors_form_a_hierarchy() -> None:
    assert issubclass(SessionInvalidError, GatewayError)


def test_rate_limit_error_keeps_its_fields() -> None:
    err = RateLimitError(
        "espera esgotada",
        retry_after=1.5,
        global_limit=True,
        bucket="interactions",
    )
    assert err.status == 429
    assert err.retry_after == 1.5
    assert err.global_limit is True
    assert err.bucket == "interactions"


def test_discord_api_error_keeps_its_fields() -> None:
    err = DiscordAPIError(
        "Missing Access",
        status=403,
        code=50001,
        errors={"access": ["denied"]},
    )
    assert err.status == 403
    assert err.code == 50001
    assert err.errors == {"access": ["denied"]}


def test_http_error_status_is_optional() -> None:
    err = HTTPError("conexao caiu")
    assert err.status is None
