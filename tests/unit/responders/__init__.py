"""Pacote de testes dos responders — `0013`, `0014`, `0023`."""

import pytest

from kryncord.responders.registry import ResponderRegistry


@pytest.fixture
def registry() -> ResponderRegistry:
    """Registry novo por teste — o global é contaminação de estado
    que vaza de um teste para o outro (K12)."""
    return ResponderRegistry()
