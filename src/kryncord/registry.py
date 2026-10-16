"""`kryncord.registry` — os registries globais (K12).

`@command` num módulo precisa registrar em algum lugar sem que o
usuário aponte um client — é o que a arquitetura quer ao proibir cogs.
O global existe e é o default.

`Client(registry=...)` é o caminho de teste, e é **obrigatório** nele:
registry global compartilhado entre testes é contaminação de estado que
aparece como falha num outro teste qualquer.
"""

from __future__ import annotations

from kryncord.commands.registry import CommandRegistry
from kryncord.events.dispatcher import EventDispatcher
from kryncord.responders.registry import ResponderRegistry


class Registry:
    """Um por processo: comandos, eventos e responders do aplicativo inteiro."""

    __slots__ = ("commands", "events", "responders")

    def __init__(self) -> None:
        self.commands = CommandRegistry()
        #: O `@event` precisa de um lugar para registrar sem que o
        #: usuário aponte um client, pelo mesmo motivo do `@command`
        #: (`K12`). O `Client` usa este por default.
        self.events = EventDispatcher()
        self.responders = ResponderRegistry()

    def limpa(self) -> None:
        """Zera tudo. Existe para o teste, não para produção."""
        self.commands = CommandRegistry()
        self.events = EventDispatcher()
        self.responders = ResponderRegistry()


#: O registry global da aplicação — o default de todo `@responder`.
registry = Registry()
