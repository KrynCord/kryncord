"""`ResponderContext` — o que o handler de botão/select/modal recebe.

A ideia 07 chama o primeiro parâmetro de ``interaction``; o 0012
resolveu que ele é este contexto. São o mesmo objeto na prática — o
contexto **compõe** o modelo (``ctx.interaction``) e proxya o que o
código do handler escreve perto: resposta delega ao `InteractionContext`
(um só dono do estado), e os predicados de tipo delegam ao modelo
(predicados do payload, 0023 R5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from typing import TYPE_CHECKING, Any, cast

from kryncord.errors import InteractionTimeoutError
from kryncord.interactions.component import ModalFields, valores_de_select
from kryncord.interactions.response import InteractionContext, InteractionState
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.user import User
from kryncord.responders.params import Params

if TYPE_CHECKING:
    from kryncord.internal.tasks import TaskRegistry


class ResponderContext:
    """Contexto de um responder — um por dispatch."""

    __slots__ = (
        "_client",
        "_esperas",
        "_interaction_ctx",
        "_params",
        "_state",
        "_tasks",
    )

    def __init__(
        self,
        interaction_ctx: InteractionContext,
        *,
        params: Mapping[str, str] | None = None,
        client: Any = None,
        tasks: TaskRegistry | None = None,
        esperas: Any = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        self._interaction_ctx = interaction_ctx
        self._params = Params(params)
        self._client = client
        self._tasks = tasks
        #: A lista de esperas do dispatcher — `await_responder` registra
        #: aqui. `None` em contexto montado à mão, e `await_responder`
        #: reclama: sem dispatcher não há quem resolva a espera.
        self._esperas = esperas
        #: Por dispatch, compartilhado com middleware. Não vaza entre
        #: dois cliques — nasce vazio a cada um (0012).
        #:
        #: **Um só por dispatch** (`0026` §D6): o `CommandContext`, o
        #: `ResponderContext` e o `EventContext` do mesmo
        #: `INTERACTION_CREATE` recebem este mesmo dicionário. É o que
        #: faz middleware de comando e handler de
        #: `@event("interaction_create")` enxergarem a mesma chave sem
        #: serem o mesmo objeto — e sem isso, a etapa 4 e a etapa 5
        #: leriam dois estados paralelos que nunca se encontram.
        self._state: dict[str, Any] = state if state is not None else {}

    # ------------------------------------------------------------------
    # Dados da interação
    # ------------------------------------------------------------------

    @property
    def interaction(self) -> Interaction:
        """O payload, dado puro. `custom_id`, `token`, `data`…"""
        return self._interaction_ctx.interaction

    @property
    def interaction_context(self) -> InteractionContext:
        """O dono do estado da resposta. `ctx.reply()` já delega."""
        return self._interaction_ctx

    @property
    def custom_id(self) -> str | None:
        """O `custom_id` completo recebido — não é a rota.

        A rota é o padrão que casou; este é o id concreto, com os
        valores já dentro. Precisa dos dois é sinal de que o `params`
        resolve: `custom_id` é para log e para resposta, `params` é
        para ler.
        """
        return self.interaction.custom_id

    @property
    def params(self) -> Params:
        """Valores crus extraídos da rota, imutáveis.

        Os valores convertidos chegam como argumentos nomeados do
        handler; este é o cru, sempre string — quem quer o bruto,
        sem conversão, lê aqui.
        """
        return self._params

    @property
    def values(self) -> tuple[str, ...]:
        """Valores escolhidos num select. Vazio fora de select.

        Tupla porque já chegaram — append num valor entregue mudaria o
        que o handler itera no meio do loop.
        """
        return valores_de_select(self.interaction.data)

    @property
    def fields(self) -> ModalFields:
        """Campos do modal submetido. Vazio fora de modal."""
        return ModalFields(self.interaction.data)

    @property
    def message(self) -> Message | None:
        """A mensagem a que o componente estava preso.

        `None` quando não há mensagem — modal aberto por comando, por
        exemplo. Modelar como "sempre existe" faria todo handler de
        botão checar `if ctx.message` mesmo assim, mentindo o tipo.
        """
        bruto = (self.interaction.raw or {}).get("message")
        if not isinstance(bruto, Mapping):
            return None
        return Message.from_payload(bruto)

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
        if self.cache is None or self.interaction.guild_id is None:
            return None
        return cast("Guild | None", self.cache.get_guild(self.interaction.guild_id))

    @property
    def channel(self) -> Channel | None:
        if self.cache is None or self.interaction.channel_id is None:
            return None
        return cast("Channel | None", self.cache.get_channel(self.interaction.channel_id))

    @property
    def user(self) -> User | None:
        """Quem clicou — do payload, não do cache: é o único dado que
        **sempre** vem, e ir ao cache por ele seria uma espera a mais."""
        return self.interaction.author

    @property
    def member(self) -> Member | None:
        """`None` em DM — membros só existem em guild."""
        return self.interaction.member

    @property
    def state(self) -> dict[str, Any]:
        """Espaço por dispatch, compartilhado com as middlewares."""
        return self._state

    # ------------------------------------------------------------------
    # Predicados de tipo — delegação ao modelo
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
        """Não existe `is_modal()` — dois nomes para uma pergunta é o
        que o `0012` baniu (0023, correção registrada)."""
        return self.interaction.is_modal_submit()

    def is_autocomplete(self) -> bool:
        return self.interaction.is_autocomplete()

    def is_command(self) -> bool:
        return self.interaction.is_command()

    def in_guild(self) -> bool:
        return self.interaction.in_guild()

    # ------------------------------------------------------------------
    # Resposta — delegação pura ao dono do estado
    # ------------------------------------------------------------------

    def is_responded(self) -> bool:
        return self._interaction_ctx.is_responded()

    def is_deferred(self) -> bool:
        return self._interaction_ctx.is_deferred()

    def is_answered(self) -> bool:
        return self._interaction_ctx.is_answered()

    @property
    def state_resposta(self) -> InteractionState:
        return self._interaction_ctx.state

    async def reply(self, content: str | None = None, **kwargs: Any) -> None:
        await self._interaction_ctx.reply(content, **kwargs)

    async def defer(self, *, ephemeral: bool = False) -> None:
        await self._interaction_ctx.defer(ephemeral=ephemeral)

    async def defer_update(self) -> None:
        await self._interaction_ctx.defer_update()

    async def update(self, content: str | None = None, **kwargs: Any) -> None:
        await self._interaction_ctx.update(content, **kwargs)

    async def ack(self) -> None:
        await self._interaction_ctx.ack()

    async def edit(
        self,
        content: str | None = None,
        *,
        message_id: str | int = "@original",
        **kwargs: Any,
    ) -> None:
        await self._interaction_ctx.edit(content, message_id=message_id, **kwargs)

    async def delete(self, *, message_id: str | int = "@original") -> None:
        await self._interaction_ctx.delete(message_id=message_id)

    async def fetch_reply(self, *, message_id: str | int = "@original") -> Any:
        return await self._interaction_ctx.fetch_reply(message_id=message_id)

    async def follow_up(self, content: str | None = None, **kwargs: Any) -> Any:
        return await self._interaction_ctx.follow_up(content, **kwargs)

    async def send_modal(self, modal: Any) -> None:
        await self._interaction_ctx.send_modal(modal)

    async def launch_activity(self) -> None:
        await self._interaction_ctx.launch_activity()

    # ------------------------------------------------------------------
    # Trabalho de fundo e espera
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
                "Contexto montado à mão em teste: passe tasks=TaskRegistry()."
            )
        return tasks.spawn(coro, nome=nome)

    async def await_responder(self, custom_id: str, *, timeout: float = 300.0) -> Any:
        """Espera o próximo dispatch deste `custom_id` e devolve o que
        o handler retornou.

        É o `awaitModalSubmit` do discord.js sem o collector: single-shot,
        observa sem consumir — o `@responder` correspondente roda
        normal, e o `on_not_found` não muda (0023, R3).

            await ctx.send_modal(form_modal())
            sub = await ctx.await_responder("/register/form", timeout=300)

        O timeout é erro explícito (`InteractionTimeoutError`), não
        `asyncio.TimeoutError` cru: "o usuário não submeteu" é uma
        resposta, e o handler precisa distinguir.
        """
        if self._esperas is None:
            raise RuntimeError(
                "await_responder() precisa do dispatcher — o Client fornece. "
                "Contexto montado à mão em teste: passe esperas=Esperas()."
            )
        futuro = self._esperas.registra(custom_id, timeout=timeout)
        try:
            return await asyncio.wait_for(futuro, timeout)
        except TimeoutError:
            raise InteractionTimeoutError(
                f"nenhum dispatch de {custom_id!r} em {timeout}s — o usuário "
                f"provavelmente fechou o modal sem enviar"
            ) from None
