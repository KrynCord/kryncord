"""Componentes interativos tipados — botão, selects e modal submetido.

Cada tipo de componente tem sua classe, e cada classe expõe o que **é
dado** naquele tipo: `ButtonInteraction` tem a mensagem de origem,
`StringSelectInteraction` tem os valores como texto,
`UserSelectInteraction` devolve `User` resolvido, e
`ModalSubmitInteraction` tem `fields`. Um objeto genérico com
`values: tuple[str, ...]` para os cinco selects obriga o handler a
adivinhar o tipo — e adivinhar é bug.

`update()`/`defer_update()` moram aqui e não no `BaseInteraction`: só
existe em componente, porque só em componente existe a mensagem a
confirmar ou substituir (`0031`, docs/interaction-response-methods.md
§5-6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from kryncord.enums import ResponderType
from kryncord.errors import InteractionTimeoutError
from kryncord.interactions.base import BaseInteraction
from kryncord.interactions.component import ModalFields, valores_de_select
from kryncord.models.channel import Channel
from kryncord.models.message import Message
from kryncord.models.role import Role
from kryncord.models.user import User

if TYPE_CHECKING:
    from kryncord.responders.params import Params


class ComponentInteraction(BaseInteraction):
    """Um componente interativo (botão/select) ou modal submetido."""

    __slots__ = ("_esperas", "_params")

    def __init__(
        self,
        interaction_ctx: Any,
        *,
        params: Mapping[str, str] | None = None,
        client: Any = None,
        tasks: Any = None,
        esperas: Any = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(interaction_ctx, client=client, tasks=tasks, state=state)
        self._params = dict(params) if params is not None else {}
        #: A lista de esperas do dispatcher — `await_responder` registra
        #: aqui. `None` em interação montada à mão, e `await_responder`
        #: reclama: sem dispatcher não há quem resolva a espera.
        self._esperas = esperas

    # ------------------------------------------------------------------
    # Dados do componente
    # ------------------------------------------------------------------

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
        from kryncord.responders.params import Params

        return Params(self._params)

    @property
    def esperas(self) -> Any:
        """A lista de esperas do dispatcher — plumbing do `emit`."""
        return self._esperas

    @property
    def values(self) -> tuple[str, ...]:
        """Valores escolhidos num select, crus. Vazio fora de select.

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
        botão checar `if interaction.message` mesmo assim, mentindo o
        tipo.
        """
        bruto = (self.interaction.raw or {}).get("message")
        if not isinstance(bruto, Mapping):
            return None
        return Message.from_payload(bruto)

    # ------------------------------------------------------------------
    # Resposta de componente
    # ------------------------------------------------------------------

    async def update(self, content: str | None = None, **kwargs: Any) -> None:
        """Atualiza a mensagem que continha o componente.

        Resposta inicial de componente: substitui a mensagem na hora.
        Só antes de qualquer outra resposta — um `defer()` já virou um
        "pensando…" na tela, e trocá-lo não é o que `update` faz.
        """
        await self._interaction_ctx.update(content, **kwargs)

    async def defer_update(self) -> None:
        """Reconhece o clique **sem** mudar a mensagem.

        Para o handler que sabe o que quer e precisa só de tempo —
        diferente do `defer()`, que mostra "pensando…". Depois disto,
        conclua com `edit_original_response()` ou mande um `followup()`.
        """
        await self._interaction_ctx.defer_update()

    # ------------------------------------------------------------------
    # Espera
    # ------------------------------------------------------------------

    async def await_responder(self, custom_id: str, *, timeout: float = 300.0) -> Any:
        """Espera o próximo dispatch deste `custom_id` e devolve o que
        o handler retornou.

        É o `awaitModalSubmit` do discord.js sem o collector: single-shot,
        observa sem consumir — o `@responder` correspondente roda
        normal, e o `on_not_found` não muda (0023, R3).

            await interaction.open_modal(form_modal())
            sub = await interaction.await_responder("register/form", timeout=300)

        O timeout é erro explícito (`InteractionTimeoutError`), não
        `asyncio.TimeoutError` cru: "o usuário não submeteu" é uma
        resposta, e o handler precisa distinguir.
        """
        if self._esperas is None:
            raise RuntimeError(
                "await_responder() precisa do dispatcher — o Client fornece. "
                "Interação montada à mão em teste: passe esperas=Esperas()."
            )
        futuro = self._esperas.registra(custom_id, timeout=timeout)
        try:
            return await asyncio.wait_for(futuro, timeout)
        except TimeoutError:
            raise InteractionTimeoutError(
                f"nenhum dispatch de {custom_id!r} em {timeout}s — o usuário "
                f"provavelmente fechou o modal sem enviar"
            ) from None


class ButtonInteraction(ComponentInteraction):
    """Um clique em botão — a mensagem de origem é `message`."""

    __slots__ = ()


class _SelectComResolvidos(ComponentInteraction):
    """Base dos selects que o Discord resolve para objetos.

    `resolved` vem em `data.resolved`, por tabela (`users`, `roles`,
    `channels`), com os ids que `data.values` trouxe. Sem tabela não há
    o que resolver — payload truncado, e devolver vazio é honesto.
    """

    __slots__ = ()
    _TABELA = ""

    def _tabela(self) -> Mapping[str, Any]:
        data = self.interaction.data or {}
        resolved = data.get("resolved")
        if not isinstance(resolved, Mapping):
            return {}
        bruto = resolved.get(self._TABELA)
        return bruto if isinstance(bruto, Mapping) else {}

    def _resolvidos(self, modelo: Any) -> tuple[Any, ...]:
        """Os ids de `values` virando objetos, na ordem escolhida."""
        tabela = self._tabela()
        saida: list[Any] = []
        for bruto_id in valores_de_select(self.interaction.data):
            item = tabela.get(bruto_id)
            if item is None:
                continue
            objeto = modelo.from_payload(dict(item))
            if objeto is not None:
                saida.append(objeto)
        return tuple(saida)


class StringSelectInteraction(_SelectComResolvidos):
    """Select de texto — `values` são as strings escolhidas."""

    __slots__ = ()

    @property
    def values(self) -> tuple[str, ...]:
        return valores_de_select(self.interaction.data)


class UserSelectInteraction(_SelectComResolvidos):
    """Select de usuários — `values` são `User` resolvidos."""

    __slots__ = ()
    _TABELA = "users"

    @property
    def values(self) -> tuple[User, ...]:  # type: ignore[override]
        # A base promete os ids crus (`tuple[str, ...]`); o select de
        # usuário estreita para o objeto resolvido — regra de design
        # (0031), não acidente: quem registra `@user_select` itera
        # `User`, não o id. O mypy reclama porque `User` não é `str`.
        return cast("tuple[User, ...]", self._resolvidos(User))


class RoleSelectInteraction(_SelectComResolvidos):
    """Select de funções — `values` são `Role` resolvidos."""

    __slots__ = ()
    _TABELA = "roles"

    @property
    def values(self) -> tuple[Role, ...]:  # type: ignore[override]
        return cast("tuple[Role, ...]", self._resolvidos(Role))


class ChannelSelectInteraction(_SelectComResolvidos):
    """Select de canais — `values` são `Channel` resolvidos."""

    __slots__ = ()
    _TABELA = "channels"

    @property
    def values(self) -> tuple[Channel, ...]:  # type: ignore[override]
        return cast("tuple[Channel, ...]", self._resolvidos(Channel))


class MentionableSelectInteraction(_SelectComResolvidos):
    """Select de menções — usuários **ou** cargos.

    Union porque a própria seleção é union: o Discord decide, pelo
    `resolved` onde o id aparece. Estreitar para um dos dois obrigatoria
    o handler a apostar.
    """

    __slots__ = ()

    @property
    def values(self) -> tuple[User | Role, ...]:  # type: ignore[override]
        data = self.interaction.data or {}
        resolved = data.get("resolved")
        if not isinstance(resolved, Mapping):
            return ()
        usuarios = resolved.get("users") or {}
        cargos = resolved.get("roles") or {}
        saida: list[User | Role] = []
        objeto: User | Role | None
        for bruto_id in valores_de_select(data):
            if bruto_id in usuarios:
                objeto = User.from_payload(dict(usuarios[bruto_id]))
            elif bruto_id in cargos:
                objeto = Role.from_payload(dict(cargos[bruto_id]))
            else:
                continue
            if objeto is not None:
                saida.append(objeto)
        return tuple(saida)


class ModalSubmitInteraction(ComponentInteraction):
    """Envio de modal — os campos estão em `fields`.

    O envio é uma **nova** interação: o modal aberto pelo botão gerou o
    id, e a mensagem antiga só é editável por uma referência própria
    (docs/interaction-response-methods.md §10).
    """

    __slots__ = ()


#: `ResponderType` → classe entregue ao handler. Determinístico, vindo
#: do tipo da interação que chegou — nunca de adivinhação pela anotação.
CLASSES: dict[ResponderType, type[ComponentInteraction]] = {
    ResponderType.BUTTON: ButtonInteraction,
    ResponderType.STRING_SELECT: StringSelectInteraction,
    ResponderType.USER_SELECT: UserSelectInteraction,
    ResponderType.ROLE_SELECT: RoleSelectInteraction,
    ResponderType.MENTIONABLE_SELECT: MentionableSelectInteraction,
    ResponderType.CHANNEL_SELECT: ChannelSelectInteraction,
    ResponderType.MODAL_SUBMIT: ModalSubmitInteraction,
}


def classe_para(tipo: ResponderType) -> type[ComponentInteraction]:
    """A classe de interação para um `ResponderType`.

    Tipo novo do Discord (ou `None`) cai em `ComponentInteraction` —
    a superfície comum existe justamente para o caso em que o Discord
    anda à frente da biblioteca.
    """
    return CLASSES.get(tipo, ComponentInteraction)


__all__ = [
    "CLASSES",
    "ButtonInteraction",
    "ChannelSelectInteraction",
    "ComponentInteraction",
    "MentionableSelectInteraction",
    "ModalSubmitInteraction",
    "RoleSelectInteraction",
    "StringSelectInteraction",
    "UserSelectInteraction",
    "classe_para",
]
