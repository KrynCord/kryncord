"""Testes de `kryncord.logging` — namespace e redação de segredos."""

from __future__ import annotations

import logging

from kryncord import get_logger, redact, setup_logging
from kryncord.logging import SENSITIVE_KEYS


def test_get_logger_uses_kryncord_namespace() -> None:
    assert get_logger().name == "kryncord"


def test_get_logger_prefixes_child_names() -> None:
    assert get_logger("rest").name == "kryncord.rest"


def test_get_logger_does_not_double_prefix() -> None:
    """Chamar get_logger('kryncord.rest') não vira kryncord.kryncord.rest."""
    assert get_logger("kryncord.rest").name == "kryncord.rest"


def test_get_logger_bare_returns_root_of_namespace() -> None:
    assert get_logger("").name == "kryncord"


def test_setup_logging_sets_level() -> None:
    logger = setup_logging("DEBUG")
    assert logger.level == logging.DEBUG


def test_setup_logging_is_idempotent() -> None:
    """Chamar duas vezes substitui o handler, não acumula."""
    setup_logging("INFO")
    setup_logging("INFO")
    logger = get_logger()
    assert len(logger.handlers) == 1


def test_setup_logging_does_not_touch_root() -> None:
    """Configurar a biblioteca não pode bagunçar o logger da aplicação."""
    root_level = logging.getLogger().level
    setup_logging("DEBUG")
    assert logging.getLogger().level == root_level


def test_setup_logging_disables_propagation() -> None:
    logger = setup_logging()
    assert logger.propagate is False


# --------------------------------------------------------------------------
# redact
# --------------------------------------------------------------------------


def test_redact_masks_token() -> None:
    assert redact({"token": "abc123"}) == {"token": "***"}


def test_redact_masks_case_insensitively() -> None:
    assert redact({"Authorization": "Bearer x"}) == {"Authorization": "***"}
    assert redact({"TOKEN": "abc"}) == {"TOKEN": "***"}


def test_redact_masks_session_id() -> None:
    """session_id permite forjar um gateway — é segredo."""
    assert redact({"session_id": "s"}) == {"session_id": "***"}


def test_redact_masks_nested() -> None:
    data = {"outer": {"token": "abc", "safe": "visible"}}
    assert redact(data) == {"outer": {"token": "***", "safe": "visible"}}


def test_redact_handles_lists() -> None:
    assert redact([{"token": "a"}, {"ok": "b"}]) == [{"token": "***"}, {"ok": "b"}]


def test_redact_preserves_non_dict() -> None:
    assert redact("texto") == "texto"
    assert redact(42) == 42
    assert redact(None) is None


def test_redact_does_not_mutate_input() -> None:
    original = {"token": "abc"}
    redact(original)
    assert original == {"token": "abc"}


def test_redact_keeps_safe_keys() -> None:
    data = {"id": "123", "content": "olá", "bucket": "x"}
    assert redact(data) == data


def test_redact_preserves_tuple_type() -> None:
    result = redact(({"token": "a"}, "b"))
    assert isinstance(result, tuple)
    assert result == ({"token": "***"}, "b")


def test_redact_empty_dict() -> None:
    assert redact({}) == {}


def test_redact_always_masks_every_sensitive_key() -> None:
    for key in SENSITIVE_KEYS:
        assert redact({key: "valor"}) == {key: "***"}
