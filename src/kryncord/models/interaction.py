"""Interação — slash command, botão, select, modal.

A interação é o objeto que o Discord manda **para o bot responder**, e
ela tem uma regra que não é negociável: **3 segundos**. Se o bot não
mandar uma resposta (ou um defer) nesse intervalo, o Discord descarta
e mostra "A aplicação não respondeu" — e não adianta responder depois.

É por isso que `type` e `token` são obrigatórios aqui: sem os dois não
existe callback possível, e um objeto meio montado seria pior que não
ter objeto nenhum — o chamador mandaria um `POST` para uma URL incompleta
e receberia um 404 que não explica o problema real.

`data` fica cru. O payload de ``APPLICATION_COMMAND`` traz
``{id, name, type, options}``; o de ``MESSAGE_COMPONENT`` traz
``{custom_id, component_type}``; o de ``MODAL_SUBMIT`` traz
``{custom_id, components}``. Parser cada um seria três modelos para o
chamador desmembrar do mesmo jeito — e a segunda forma (componentes com
``values``) já é suficientemente irregular que tolerar vale mais que
modelar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.enums import ApplicationCommandType, ComponentType, InteractionType
from kryncord.models.base import integer, snowflake, string
from kryncord.models.member import Member
from kryncord.models.user import User


@dataclass(frozen=True, slots=True)
class Interaction:
    """O que o Discord manda quando algo invoca o bot."""

    id: int
    application_id: int
    type: int
    token: str
    """Token de resposta. Segredo — com ele se faz followup sem
    autenticação, igual ao token de webhook."""
    version: int = 1
    channel_id: int | None = None
    guild_id: int | None = None
    member: Member | None = None
    user: User | None = None
    data: Mapping[str, Any] | None = None
    locale: str | None = None
    guild_locale: str | None = None
    raw: Mapping[str, Any] | None = None
    """Payload inteiro, para quem precisa de um campo que não modelamos."""

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Interaction | None:
        """`None` se faltar ``id``, ``type`` ou ``token``.

        Os três são o mínimo para responder. Sem `token` não há URL de
        callback; sem `type` não se sabe qual endpoint; sem `id` a
        resposta aponta para nada.
        """
        interaction_id = snowflake(data, "id")
        interaction_type = integer(data, "type")
        token = string(data, "token")
        if interaction_id is None or interaction_type is None or token is None:
            return None

        member_raw = data.get("member")
        user_raw = data.get("user")
        inner_data = data.get("data")
        return cls(
            id=interaction_id,
            application_id=snowflake(data, "application_id") or 0,
            type=interaction_type,
            token=token,
            version=integer(data, "version") or 1,
            channel_id=snowflake(data, "channel_id"),
            guild_id=snowflake(data, "guild_id"),
            member=Member.from_payload(member_raw) if isinstance(member_raw, Mapping) else None,
            user=User.from_payload(user_raw) if isinstance(user_raw, Mapping) else None,
            data=inner_data if isinstance(inner_data, Mapping) else None,
            locale=string(data, "locale"),
            guild_locale=string(data, "guild_locale"),
            raw=dict(data),
        )

    @property
    def author(self) -> User | None:
        """Quem invocou — de dentro do `member` em guild, ou direto em DM.

        Em guild o Discord manda só ``member`` (com o `user` dentro);
        em DM manda só ``user``. São dois caminhos para a mesma
        informação, e quem escreve handler não deveria ter que lembrar
        qual.
        """
        if self.user is not None:
            return self.user
        if self.member is not None:
            return self.member.user
        return None

    @property
    def command_name(self) -> str | None:
        """Nome do comando invocado, ou `None` se não for comando."""
        if self.data is None:
            return None
        return string(self.data, "name")

    @property
    def custom_id(self) -> str | None:
        """``custom_id`` de botão/select/modal, ou `None` se não for componente."""
        if self.data is None:
            return None
        return string(self.data, "custom_id")

    @property
    def command_type(self) -> int | None:
        """``ApplicationCommandType`` de um comando, ou `None`."""
        if self.data is None:
            return None
        return integer(self.data, "type")

    @property
    def component_type(self) -> int | None:
        """``ComponentType`` de um botão/select, ou `None`."""
        if self.data is None:
            return None
        return integer(self.data, "component_type")

    # ------------------------------------------------------------------
    # Predicados de tipo
    # ------------------------------------------------------------------
    #
    # São funções puras do payload: `type` + `data.type` +
    # `data.component_type`. Vivem no modelo, e não num contexto, porque
    # quem só tem o payload (cache, teste, logger) também precisa
    # perguntar — contexto que os reexporta é convenância, não dono.
    #
    # São **métodos**, não propriedades: `if interaction.is_button()`
    # lê como pergunta, que é o que é. Antes eram três propriedades e o
    # resto nem existia — o `is_command` propriedade e um eventual
    # `is_chat_input_command` não respondiam a mesma pergunta pela mesma
    # forma (0023, R5).

    def is_autocomplete(self) -> bool:
        return self.type == InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE

    def is_command(self) -> bool:
        """Qualquer comando de aplicação — CHAT_INPUT, USER ou MESSAGE."""
        return self.type == InteractionType.APPLICATION_COMMAND

    def is_chat_input_command(self) -> bool:
        return self.is_command() and self.command_type == ApplicationCommandType.CHAT_INPUT

    def is_context_menu_command(self) -> bool:
        return self.is_command() and self.command_type in (
            ApplicationCommandType.USER,
            ApplicationCommandType.MESSAGE,
        )

    def is_user_context_menu(self) -> bool:
        return self.is_command() and self.command_type == ApplicationCommandType.USER

    def is_message_context_menu(self) -> bool:
        return self.is_command() and self.command_type == ApplicationCommandType.MESSAGE

    def is_message_component(self) -> bool:
        return self.type == InteractionType.MESSAGE_COMPONENT

    def is_modal_submit(self) -> bool:
        """Envio de modal. **Não existe `is_modal()`** — o `0012` baniu
        dois nomes para uma pergunta, e o `07` §3 tabela já diz que
        `MODAL` é só alias de `MODAL_SUBMIT`."""
        return self.type == InteractionType.MODAL_SUBMIT

    def is_button(self) -> bool:
        return self._componente_e(ComponentType.BUTTON)

    def is_select_menu(self) -> bool:
        """Qualquer menu de seleção — os cinco que o Discord tem hoje."""
        return self.is_message_component() and ComponentType(self.component_type or 0).is_select

    def is_string_select(self) -> bool:
        return self._componente_e(ComponentType.STRING_SELECT)

    def is_user_select(self) -> bool:
        return self._componente_e(ComponentType.USER_SELECT)

    def is_role_select(self) -> bool:
        return self._componente_e(ComponentType.ROLE_SELECT)

    def is_channel_select(self) -> bool:
        return self._componente_e(ComponentType.CHANNEL_SELECT)

    def is_mentionable_select(self) -> bool:
        return self._componente_e(ComponentType.MENTIONABLE_SELECT)

    def is_repliable(self) -> bool:
        """Se dá para responder com mensagem.

        `AUTOCOMPLETE` aceita **só** `respond(choices)`; `PING` é
        verificação de URL e não chega em handler nenhum.
        """
        return self.type not in (
            InteractionType.PING,
            InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE,
        )

    def in_guild(self) -> bool:
        """Se veio de uma guild — não de DM.

        Diferente de `guild_id is not None` só: uma interação pode trazer
        `guild_id` sem `member` em payloads truncados, e aí não há de
        onde tirar permissão do autor.
        """
        return self.guild_id is not None and self.member is not None

    def _componente_e(self, esperado: ComponentType) -> bool:
        """`component_type` bate com `esperado`.

        `component_type or 0` porque `None` não é `ComponentType` — e um
        payload sem `component_type` não é botão nem select, é payload
        quebrado. `0` não casa com nenhum, que é a resposta certa.
        """
        return self.is_message_component() and self.component_type == int(esperado)

    # Não há `responded`. O Discord não devolve se já respondemos, e
    # guardar isso num atributo aqui exigiria alguém chamar `.mark()` —
    # um estado que alguém esquece de marcar mente. Quem precisa saber
    # guarda na própria variável do handler. A máquina de estados de
    # resposta é do `InteractionContext` (0016), não deste modelo.
