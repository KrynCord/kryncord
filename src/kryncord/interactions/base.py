"""Interações tipadas — o objeto que o handler recebe como 1º argumento.

O `0031` decidiu: **não existe `ctx` genérico**. Cada handler recebe o
tipo da interação que o invocou — `CommandInteraction` para `/ping`,
`ButtonInteraction` para um clique, `ModalSubmitInteraction` para o
envio de um formulário. O tipo diz, no editor e no runtime, quais
operações são válidas: `update()` existe onde existe mensagem para
atualizar, e `autocomplete()` existe onde a única resposta é sugestão.

Hierarquia::

    InteractionBase           dados: payload, client, user, guild...
      ├── BaseInteraction     + ciclo de resposta (respond, defer...)
      │    ├── CommandInteraction (+ options; USER/MESSAGE/ENTRY_POINT)
      │    └── ComponentInteraction (+ custom_id, params, message...)
      │         ├── ButtonInteraction
      │         ├── String/User/Role/Mentionable/ChannelSelect...
      │         └── ModalSubmitInteraction (+ fields)
      └── AutocompleteInteraction (focused + autocomplete())

A máquina de estados continua no `InteractionContext` (compor, não
herdar — `0012`): um só dono do estado por dispatch significa que
`interaction.respond()` e `interaction.defer()` nunca discordam sobre o
que já foi mandado. A interação tipada é a **face pública** dele.
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, cast

from kryncord.interactions.response import InteractionContext, InteractionState
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.user import User

if TYPE_CHECKING:
    from kryncord.internal.tasks import TaskRegistry

#: Marcador de "ainda não resolvido". `None` seria "não existe", que é
#: uma resposta — e memoizar `None` como "nunca procure" perderia o
#: guild que ainda não chegou no cache.
_NAO = object()


class InteractionBase:
    """O que **toda** interação tem: quem, onde, e o payload.

    Sem ciclo de resposta — este objeto é dado. Quem responde é o
    `BaseInteraction`, que soma esta superfície com a máquina de estados.
    `AutocompleteInteraction` herda só isto, de propósito: autocomplete
    não tem `respond()`, e dar a ele um `BaseInteraction` inteiro seria
    entregar métodos que o Discord recusaria.
    """

    __slots__ = (
        "_channel",
        "_client",
        "_guild",
        "_interaction_ctx",
        "_member",
        "_state",
        "_tasks",
        "_user",
    )

    def __init__(
        self,
        interaction_ctx: InteractionContext,
        *,
        client: Any = None,
        tasks: TaskRegistry | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        self._interaction_ctx = interaction_ctx
        self._client = client
        self._tasks = tasks
        #: Por dispatch, compartilhado com middleware (0012). Nasce
        #: vazio quando o chamador não repassa — contexto montado à mão
        #: em teste.
        self._state: dict[str, Any] = state if state is not None else {}
        #: Resolvidos sob demanda a partir do cache do client. `None`
        #: explícito = "não procure de novo" (DM, ou cache inexistente).
        self._guild: Guild | object | None = _NAO
        self._channel: Channel | object | None = _NAO
        self._user: User | object | None = _NAO
        self._member: Member | object | None = _NAO

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    @property
    def interaction(self) -> Interaction:
        """O payload, dado puro — `id`, `token`, `data`, `raw`…"""
        return self._interaction_ctx.interaction

    @property
    def interaction_context(self) -> InteractionContext:
        """O dono do estado da resposta. Uso interno/teste — o handler
        usa os métodos da própria interação."""
        return self._interaction_ctx

    # ------------------------------------------------------------------
    # Quem e onde
    # ------------------------------------------------------------------

    @property
    def client(self) -> Any:
        """O `Client` que despachou. `None` em teste unitário."""
        return self._client

    @property
    def cache(self) -> Any:
        """O `ConnectionState` — `None` sem client."""
        return getattr(self._client, "cache", None)

    @property
    def guild(self) -> Guild | None:
        """Do cache local. `None` em interação de DM."""
        return cast(
            "Guild | None",
            self._resolve(self._guild, "get_guild", "_guild", self.interaction.guild_id),
        )

    @property
    def channel(self) -> Channel | None:
        return cast(
            "Channel | None",
            self._resolve(self._channel, "get_channel", "_channel", self.interaction.channel_id),
        )

    @property
    def user(self) -> User | None:
        """Quem invocou — do payload, não do cache: é o único dado que
        **sempre** vem, e ir ao cache por ele seria uma espera a mais."""
        if self._user is not _NAO:
            return cast("User | None", self._user)
        return self.interaction.author

    @property
    def member(self) -> Member | None:
        """`None` em DM — membros só existem em guild."""
        if self._member is not _NAO:
            return cast("Member | None", self._member)
        return self.interaction.member

    def _resolve(self, marcado: Any, metodo: str, atributo: str, identificador: Any) -> Any:
        """Busca no cache, uma vez, com memoização do resultado.

        `None` do cache é resposta final — procurar de novo a cada
        acesso transformaria um id desconhecido em N buscas por
        dispatch.
        """
        if marcado is not _NAO:
            return marcado
        valor = None
        cache = self.cache
        if cache is not None and identificador is not None:
            busca = getattr(cache, metodo, None)
            if busca is not None:
                valor = busca(identificador)
        setattr(self, atributo, valor)
        return valor

    @property
    def locale(self) -> str | None:
        """O locale do usuário que invocou."""
        return self.interaction.locale

    @property
    def guild_locale(self) -> str | None:
        return self.interaction.guild_locale

    @property
    def state(self) -> dict[str, Any]:
        """Espaço por dispatch, compartilhado com as middlewares.

        `interaction.state["chave"]` é a forma de uma middleware passar
        dado a um handler sem adicionar atributo. Não vaza entre
        dispatches — nasce vazio a cada um.
        """
        return self._state

    @property
    def tasks(self) -> TaskRegistry | None:
        """O `TaskRegistry` do client — plumbing do `spawn`/`emit`."""
        return self._tasks

    # ------------------------------------------------------------------
    # Predicados de tipo — delegação ao payload
    # ------------------------------------------------------------------

    def is_button(self) -> bool:
        return self.interaction.is_button()

    def is_message_component(self) -> bool:
        return self.interaction.is_message_component()

    def is_select_menu(self) -> bool:
        return self.interaction.is_select_menu()

    def is_string_select(self) -> bool:
        return self.interaction.is_string_select()

    def is_user_select(self) -> bool:
        return self.interaction.is_user_select()

    def is_role_select(self) -> bool:
        return self.interaction.is_role_select()

    def is_channel_select(self) -> bool:
        return self.interaction.is_channel_select()

    def is_mentionable_select(self) -> bool:
        return self.interaction.is_mentionable_select()

    def is_modal_submit(self) -> bool:
        return self.interaction.is_modal_submit()

    def is_autocomplete(self) -> bool:
        return self.interaction.is_autocomplete()

    def is_command(self) -> bool:
        return self.interaction.is_command()

    def in_guild(self) -> bool:
        return self.interaction.in_guild()

    # ------------------------------------------------------------------
    # Trabalho de fundo
    # ------------------------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], *, nome: str = "") -> Any:
        """Dispara corrotina em background **com dono**.

        A task entra no `TaskRegistry` do client — cancelada no
        shutdown, não órfã. Sem registry não há spawn: task sem dono
        sobrevive ao client, e é o oposto do que background promete
        (0012, parecer do 07).
        """
        tasks = self._tasks or getattr(self._client, "_tasks", None)
        if tasks is None:
            raise RuntimeError(
                "spawn() precisa de um TaskRegistry — o Client fornece um no boot. "
                "Interação montada à mão em teste: passe tasks=TaskRegistry()."
            )
        return tasks.spawn(coro, nome=nome)


class BaseInteraction(InteractionBase):
    """Uma interação com o ciclo de resposta completo.

    `respond()` é a resposta inicial; `defer()` compra tempo;
    `edit_original_response()`/`followup()` completam depois. A ordem é
    a máquina de estados do `InteractionContext` — violar é
    `InvalidInteractionState` **nosso**, com a saída na mensagem, e não o
    400 genérico do Discord.
    """

    __slots__ = ()

    @property
    def response_state(self) -> InteractionState:
        """Estado da máquina, para quem quer consultar sem perguntar."""
        return self._interaction_ctx.state

    def is_responded(self) -> bool:
        """Já houve qualquer resposta — defer inclusive."""
        return self._interaction_ctx.is_responded()

    def is_deferred(self) -> bool:
        return self._interaction_ctx.is_deferred()

    def is_answered(self) -> bool:
        return self._interaction_ctx.is_answered()

    # ------------------------------------------------------------------
    # Resposta inicial
    # ------------------------------------------------------------------

    async def respond(self, content: str | None = None, **kwargs: Any) -> None:
        """Envia a resposta inicial — conteúdo, embeds, components…"""
        await self._interaction_ctx.respond(content, **kwargs)

    async def defer(self, *, ephemeral: bool = False) -> None:
        """Reconhece a interação e completa a resposta depois."""
        await self._interaction_ctx.defer(ephemeral=ephemeral)

    async def open_modal(self, modal: Any) -> None:
        """Abre um modal como resposta inicial.

        Abrir modal **é** a resposta — depois dele não há `respond()`.
        E o envio do modal é uma **nova** interação, tratada por
        `@modal_submit`: editar a mensagem antiga a partir dali exige
        uma referência própria (docs/interaction-response-methods.md §10).
        """
        await self._interaction_ctx.open_modal(modal)

    async def launch_activity(self) -> None:
        """Abre a atividade do app no canal da interação."""
        await self._interaction_ctx.launch_activity()

    # ------------------------------------------------------------------
    # Depois da resposta
    # ------------------------------------------------------------------

    async def edit_original_response(
        self,
        content: str | None = None,
        *,
        message_id: str | int = "@original",
        **kwargs: Any,
    ) -> None:
        """Edita a **resposta original** desta interação.

        Caminho do `defer()` concluído. **Não** é editar a mensagem que
        originou o clique — essa é `client.api.messages.edit_message`,
        operação de canal com referência própria.
        """
        await self._interaction_ctx.edit_original_response(content, message_id=message_id, **kwargs)

    async def delete_original_response(self, *, message_id: str | int = "@original") -> None:
        """Apaga a resposta original, quando permitido."""
        await self._interaction_ctx.delete_original_response(message_id=message_id)

    async def fetch_original_response(self, *, message_id: str | int = "@original") -> Any:
        """Busca a resposta original — `None` se ainda não existe."""
        return await self._interaction_ctx.fetch_original_response(message_id=message_id)

    async def followup(self, content: str | None = None, **kwargs: Any) -> Any:
        """Envia mensagem adicional depois do reconhecimento inicial."""
        return await self._interaction_ctx.followup(content, **kwargs)

    async def ack(self) -> None:
        """Garante que a interação foi acknowledge — idempotente."""
        await self._interaction_ctx.ack()
