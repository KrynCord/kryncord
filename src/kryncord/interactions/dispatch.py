"""Roteia `INTERACTION_CREATE` — um módulo, quatro ramos (`0026` §4).

A ideia 07 §7 escreveu a árvore; este arquivo é a árvore em código:

```text
INTERACTION_CREATE
 ├─ APPLICATION_COMMAND              -> commands/dispatch.py
 ├─ APPLICATION_COMMAND_AUTOCOMPLETE -> commands/autocomplete.py
 ├─ MESSAGE_COMPONENT                -> responders/dispatch.py
 ├─ MODAL_SUBMIT                     -> responders/dispatch.py
 └─ (sem handler no tipo)            -> on_not_found do tipo correspondente
```

Um módulo só, e não um por ramo: quatro chamadores seriam quatro
lugares para a mesma ordem mudar. E a ordem **é** o contrato —
`MESSAGE_COMPONENT` e `MODAL_SUBMIT` caem no mesmo despacho de
responder porque a diferença entre os dois já está no `ResponderType`
que o registro guarda.

O `on_not_found` é o do `Options` correspondente: o de comandos para
`APPLICATION_COMMAND`, o de responders para os outros dois (`0026` §4).
São duas funções diferentes por serem duas superfícies diferentes — um
comando que não existe e um botão que ninguém registrou são perguntas
distintas para quem escreve o bot.

## Roteamento antes dos `@event`

A etapa 4 roda **antes** dos handlers de `@event("interaction_create")`
(`0026` §5). É a mesma razão do "cache antes dos handlers" (`0008`):
o roteamento é o que responde dentro de 3 segundos, e um observador
rodando primeiro consumiria essa janela.

A alternativa daria ao observador a chance de responder **e** ao
roteamento a de responder de novo — duas respostas para uma interação,
que o Discord recusa com 400 e o usuário vê "algo deu errado".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kryncord.commands.autocomplete import dispatch_autocomplete
from kryncord.commands.dispatch import dispatch_application_command, instancia_de
from kryncord.enums import InteractionType
from kryncord.logging import get_logger
from kryncord.models.interaction import Interaction
from kryncord.responders.dispatch import dispatch_responder

_log = get_logger("interactions")


async def dispatch_interaction(
    payload: Mapping[str, Any],
    api: Any,
    *,
    registry: Any,
    client: Any = None,
    state: dict[str, Any] | None = None,
    cache: Any = None,
    tasks: Any = None,
    esperas: Any = None,
    command_options: Any = None,
    responder_options: Any = None,
) -> bool:
    """Entrega uma interação ao ramo certo. `True` se alguém atendeu.

    Payload malformado devolve `False` sem logar erro: o Discord manda
    o que manda, e punir a conexão inteira por um `name` ausente seria
    perder os próximos eventos por causa do anterior.
    """
    interaction = Interaction.from_payload(payload)
    if interaction is None:
        _log.debug("INTERACTION_CREATE sem campo essencial — ignorando")
        return False

    tipo = _tipo_de(interaction)
    if tipo is InteractionType.APPLICATION_COMMAND:
        return await dispatch_application_command(
            interaction,
            api,
            registry=registry.commands,
            client=client,
            state=state,
            middleware=_cadeia(command_options),
            on_error=_get(command_options, "on_error"),
            on_not_found=_get(command_options, "on_not_found"),
        )

    if tipo is InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE:
        return await dispatch_autocomplete(
            interaction,
            api,
            instancia_de(registry.commands, interaction),
            client=client,
        )

    if tipo in (InteractionType.MESSAGE_COMPONENT, InteractionType.MODAL_SUBMIT):
        return await dispatch_responder(
            interaction,
            api,
            registry=registry.responders,
            client=client,
            tasks=tasks,
            esperas=esperas,
            middleware=_cadeia(responder_options),
            on_error=_get(responder_options, "on_error"),
            on_not_found=_get(responder_options, "on_not_found"),
            state=state,
        )

    # `PING` chega pelo endpoint HTTP, não pelo Gateway, e um tipo novo
    # do Discord não é razão para logar exceção — é razão para não
    # processar.
    _log.debug("INTERACTION_CREATE tipo %s sem ramo — ignorando", tipo.name)
    return False


def _tipo_de(interaction: Interaction) -> InteractionType:
    """O tipo, tolerante a valor fora da enumeração.

    `IntEnum(bruto)` levanta para tipo novo do Discord — e um tipo que
    não conhecemos ainda não é uma falha nossa, é o Discord sendo mais
    novo que a biblioteca. Vira `0`, que não casa com nenhum ramo.
    """
    bruto = interaction.type
    try:
        return InteractionType(bruto)
    except ValueError:
        return InteractionType(0)


def _cadeia(opcoes: Any) -> tuple[Any, ...]:
    """A middleware global do `Options` como cadeia de um elemento.

    Uma só porque o `Options` aceita **uma** função por tipo (`0017`);
    para várias, o usuário usa `compose` — é para isso que ele existe.
    """
    if opcoes is None:
        return ()
    middleware = getattr(opcoes, "middleware", None)
    return (middleware,) if middleware is not None else ()


def _get(opcoes: Any, campo: str) -> Any:
    """Um campo do `Options`, ou `None` se não há `Options` nenhum."""
    return getattr(opcoes, campo, None) if opcoes is not None else None
