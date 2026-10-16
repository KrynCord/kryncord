"""`ResponderContext` + a superfície nova da interação (0023).

O fio da R6: o contexto é o objeto entregue ao handler — resposta
delega ao dono do estado, predicados delegam ao modelo, e `values`/
`fields` são o que a ideia 07 §4 prometeu.
"""

from __future__ import annotations

import pytest

from kryncord.enums import ComponentType, InteractionType, ResponderType
from kryncord.interactions.component import ModalFields
from kryncord.interactions.response import InteractionContext
from kryncord.models.interaction import Interaction
from kryncord.responders.context import ResponderContext


class ApiFalsa:
    def __init__(self) -> None:
        self.chamadas: list[str] = []

    async def respond(self, interaction, content=None, **kwargs):
        self.chamadas.append(("respond", content, kwargs))

    async def defer(self, interaction, *, ephemeral=False):
        self.chamadas.append(("defer", ephemeral))

    async def defer_update(self, interaction):
        self.chamadas.append(("defer_update",))

    async def update_message(self, interaction, content=None, **kwargs):
        self.chamadas.append(("update_message", content))

    async def show_modal(self, interaction, modal):
        self.chamadas.append(("show_modal", modal))

    async def launch_activity(self, interaction):
        self.chamadas.append(("launch_activity",))

    async def edit_message(
        self, application_id, token, message_id="@original", content=None, **kwargs
    ):
        self.chamadas.append(("edit_message", message_id, content))

    async def delete_message(self, application_id, token, message_id="@original"):
        self.chamadas.append(("delete_message", message_id))

    async def fetch_message(self, application_id, token, message_id="@original"):
        self.chamadas.append(("fetch_message", message_id))
        return f"msg:{message_id}"

    async def followup(self, application_id, token, content=None, **kwargs):
        self.chamadas.append(("followup", content))
        return "followup"


def _interacao(tipo: int = 3, data: dict | None = None, raw: dict | None = None) -> Interaction:
    base = {
        "id": "1",
        "application_id": "1",
        "type": tipo,
        "token": "t",
        "guild_id": "42",
        "channel_id": "7",
    }
    if data is not None:
        base["data"] = data
    if raw is not None:
        base.update(raw)
    return Interaction.from_payload(base)


def _botao(custom_id: str = "/x", mensagem: dict | None = None) -> Interaction:
    return _interacao(
        3,
        data={"custom_id": custom_id, "component_type": 2},
        raw={"message": mensagem} if mensagem else None,
    )


def _ctx(
    interaction: Interaction, *, params: dict | None = None
) -> tuple[ResponderContext, ApiFalsa]:
    api = ApiFalsa()
    ctx = ResponderContext(InteractionContext(interaction, api), params=params)
    return ctx, api


# --------------------------------------------------------------------------
# Predicados no modelo — 0023 R5
# --------------------------------------------------------------------------


class TestPredicados:
    def test_is_button(self) -> None:
        assert _botao().is_button() is True
        assert _interacao(3, data={"custom_id": "/x", "component_type": 3}).is_button() is False

    def test_is_string_select(self) -> None:
        interacao = _interacao(3, data={"custom_id": "/x", "component_type": 3})
        assert interacao.is_string_select() is True
        assert interacao.is_select_menu() is True
        assert interacao.is_button() is False

    def test_todos_os_selects(self) -> None:
        for componente in (3, 5, 6, 7, 8):
            interacao = _interacao(3, data={"custom_id": "/x", "component_type": componente})
            assert interacao.is_select_menu() is True, componente

    def test_is_modal_submit(self) -> None:
        assert _interacao(5, data={"custom_id": "/form"}).is_modal_submit() is True
        assert _botao().is_modal_submit() is False

    def test_is_autocomplete(self) -> None:
        assert _interacao(4).is_autocomplete() is True

    def test_is_command_e_as_variacoes(self) -> None:
        chat = _interacao(2, data={"name": "ping", "type": 1})
        menu_user = _interacao(2, data={"name": "ping", "type": 2})
        menu_msg = _interacao(2, data={"name": "ping", "type": 3})

        assert chat.is_command() is True
        assert chat.is_chat_input_command() is True
        assert chat.is_context_menu_command() is False
        assert menu_user.is_user_context_menu() is True
        assert menu_msg.is_message_context_menu() is True

    def test_is_repliable(self) -> None:
        """Autocomplete aceita só `respond(choices)`; `PING` não chega
        em handler nenhum."""
        assert _botao().is_repliable() is True
        assert _interacao(4).is_repliable() is False
        assert _interacao(1).is_repliable() is False

    def test_in_guild(self) -> None:
        com_member = _interacao(
            3,
            data={"custom_id": "/x", "component_type": 2},
            raw={
                "member": {
                    "user": {"id": "5", "username": "a", "discriminator": "0001"},
                    "nick": None,
                }
            },
        )
        sem_member = _botao()

        assert com_member.in_guild() is True
        assert sem_member.in_guild() is False

    def test_responder_context_proxya_os_predicados(self) -> None:
        ctx, _ = _ctx(_botao())

        assert ctx.is_button() is True
        assert ctx.is_string_select() is False
        assert ctx.is_modal_submit() is False


# --------------------------------------------------------------------------
# Dados do componente — values, fields, params, message
# --------------------------------------------------------------------------


class TestDados:
    def test_values_de_select(self) -> None:
        interacao = _interacao(
            3, data={"custom_id": "/fruits", "component_type": 3, "values": ["apple", "melon"]}
        )
        ctx, _ = _ctx(interacao)

        assert ctx.values == ("apple", "melon")

    def test_values_vazio_fora_de_select(self) -> None:
        ctx, _ = _ctx(_botao())

        assert ctx.values == ()

    def test_fields_do_modal_v1(self) -> None:
        interacao = _interacao(
            5,
            data={
                "custom_id": "/register/form",
                "components": [
                    {"type": 1, "components": [{"type": 4, "custom_id": "name", "value": "Ana"}]},
                    {"type": 1, "components": [{"type": 4, "custom_id": "age", "value": "20"}]},
                ],
            },
        )
        ctx, _ = _ctx(interacao)

        assert ctx.fields.get_text_input("name") == "Ana"
        assert ctx.fields["age"] == "20"
        assert ctx.fields.keys == ("name", "age")
        assert "name" in ctx.fields

    def test_fields_do_modal_v2_com_label(self) -> None:
        """v2 envolve o componente num `Label` — a mesma leitura tem
        que andar as duas formas (ideias 14 e 15)."""
        interacao = _interacao(
            5,
            data={
                "custom_id": "/form",
                "components": [
                    {
                        "type": 10,
                        "id": 1,
                        "component": {"type": 4, "id": 2, "custom_id": "nome", "value": "Bia"},
                    }
                ],
            },
        )
        ctx, _ = _ctx(interacao)

        assert ctx.fields.get_text_input("nome") == "Bia"

    def test_fields_ausente_devolve_default(self) -> None:
        ctx, _ = _ctx(_interacao(5, data={"custom_id": "/form", "components": []}))

        assert ctx.fields.get_text_input("nome") is None
        assert ctx.fields.get_text_input("nome", "padrão") == "padrão"

    def test_params_cru_e_por_atributo(self) -> None:
        ctx, _ = _ctx(_botao("/manage/user/123/ban"), params={"user_id": "123", "action": "ban"})

        assert ctx.params["user_id"] == "123"
        assert ctx.params.user_id == "123"
        assert ctx.custom_id == "/manage/user/123/ban"

    def test_params_ausente_e_attribute_error(self) -> None:
        """`AttributeError`, não `KeyError`: quem escreveu o typo errou
        um **nome**."""
        ctx, _ = _ctx(_botao(), params={})

        with pytest.raises(AttributeError, match="user_ld"):
            _ = ctx.params.user_ld

    def test_message_do_componente(self) -> None:
        interacao = _botao(
            mensagem={
                "id": "555",
                "channel_id": "7",
                "author": {"id": "9", "username": "ana", "discriminator": "0001"},
            }
        )
        ctx, _ = _ctx(interacao)

        assert ctx.message is not None
        assert ctx.message.id == 555

    def test_message_none_em_modal_de_comando(self) -> None:
        ctx, _ = _ctx(_interacao(5, data={"custom_id": "/form"}))

        assert ctx.message is None


# --------------------------------------------------------------------------
# Resposta pelo contexto — delegação ao dono do estado
# --------------------------------------------------------------------------


class TestRespostaDelegada:
    async def test_update_aceita_vazio(self) -> None:
        """Diferente de `reply()`: "mantém como está" é o ack de botão
        mais comum que existe."""
        ctx, api = _ctx(_botao())

        await ctx.update()

        assert api.chamadas == [("update_message", None)]

    async def test_update_com_conteudo(self) -> None:
        ctx, api = _ctx(_botao())

        await ctx.update("Confirmado")

        assert api.chamadas == [("update_message", "Confirmado")]

    async def test_update_em_comando_e_erro(self) -> None:
        from kryncord.errors import InteractionStateError

        ctx, _ = _ctx(_interacao(2, data={"name": "ping", "type": 1}))

        with pytest.raises(InteractionStateError, match="só existe em interação de componente"):
            await ctx.update()

    async def test_defer_update_em_componente(self) -> None:
        ctx, api = _ctx(_botao())

        await ctx.defer_update()

        assert api.chamadas == [("defer_update",)]

    async def test_defer_update_em_comando_e_erro(self) -> None:
        from kryncord.errors import InteractionStateError

        ctx, _ = _ctx(_interacao(2, data={"name": "ping", "type": 1}))

        with pytest.raises(InteractionStateError, match="só existe em interação de componente"):
            await ctx.defer_update()

    async def test_defer_ephemeral_em_componente_e_erro(self) -> None:
        """O bug que o levantamento do 0023 achou: a flag era descartada
        em silêncio. Agora é erro com a saída na mensagem."""
        ctx, _ = _ctx(_botao())

        with pytest.raises(ValueError, match="DEFERRED_UPDATE_MESSAGE"):
            await ctx.defer(ephemeral=True)

    async def test_defer_ephemeral_em_comando_passa(self) -> None:
        ctx, api = _ctx(_interacao(2, data={"name": "ping", "type": 1}))

        await ctx.defer(ephemeral=True)

        assert api.chamadas == [("defer", True)]

    async def test_fetch_reply_alcancando_followup(self) -> None:
        ctx, api = _ctx(_botao())

        resultado = await ctx.fetch_reply(message_id=777)

        assert resultado == "msg:777"
        assert api.chamadas == [("fetch_message", 777)]

    async def test_delete_com_message_id(self) -> None:
        ctx, api = _ctx(_botao())
        await ctx.reply("oi")

        await ctx.delete(message_id=777)

        assert api.chamadas[-1] == ("delete_message", 777)

    async def test_launch_activity(self) -> None:
        ctx, api = _ctx(_botao())

        await ctx.launch_activity()

        assert api.chamadas == [("launch_activity",)]

    async def test_reply_ephemeral_kwarg(self) -> None:
        ctx, api = _ctx(_botao())

        await ctx.reply("só pra você", ephemeral=True)

        assert api.chamadas == [("respond", "só pra você", {"ephemeral": True})]


# --------------------------------------------------------------------------
# spawn e await_responder — os guardas
# --------------------------------------------------------------------------


class TestSpawn:
    async def test_spawn_sem_registry_e_erro_claro(self) -> None:
        """Task órfã sobrevive ao client — o oposto do que background
        promete (0012, parecer do 07)."""
        ctx, _ = _ctx(_botao())
        coro = _dorme()

        with pytest.raises(RuntimeError, match="TaskRegistry"):
            ctx.spawn(coro)

        #: A coroutine foi criada e não consumida — fechar evita o
        #: warning de "never awaited", que não é o que se testa aqui.
        coro.close()

    async def test_spawn_com_registry_roda(self) -> None:
        from kryncord.internal.tasks import TaskRegistry

        api = ApiFalsa()
        ic = InteractionContext(_botao(), api)
        tasks = TaskRegistry()
        ctx = ResponderContext(ic, tasks=tasks)

        task = ctx.spawn(_dorme())

        await task
        assert tasks.vivas == 0


async def _dorme() -> None:
    return None


class TestAwaitResponder:
    async def test_sem_esperas_e_erro_claro(self) -> None:
        ctx, _ = _ctx(_botao())

        with pytest.raises(RuntimeError, match="Esperas"):
            await ctx.await_responder("/x")

    async def test_timeout_levanta_interaction_timeout_error(self) -> None:
        """ "O usuário não submeteu" é uma resposta — o handler precisa
        distinguir de um `TimeoutError` genérico."""
        import asyncio

        from kryncord.errors import InteractionTimeoutError
        from kryncord.responders.dispatch import Esperas

        ctx, _ = _ctx(_botao())
        esperas = Esperas()
        ctx._esperas = esperas

        with pytest.raises(InteractionTimeoutError, match="fechou o modal"):
            await asyncio.wait_for(ctx.await_responder("/x", timeout=0.05), 2)


# --------------------------------------------------------------------------
# ModalFields direto
# --------------------------------------------------------------------------


class TestModalFields:
    def test_getitem_ausente_key_error_com_presentes(self) -> None:
        campos = ModalFields(
            {
                "components": [
                    {"type": 1, "components": [{"type": 4, "custom_id": "a", "value": "1"}]}
                ]
            }
        )

        with pytest.raises(KeyError, match="presentes"):
            campos["zzz"]

    def test_len_e_iter(self) -> None:
        campos = ModalFields(
            {
                "components": [
                    {"type": 1, "components": [{"type": 4, "custom_id": "a", "value": "1"}]},
                    {"type": 1, "components": [{"type": 4, "custom_id": "b", "value": "2"}]},
                ]
            }
        )

        assert len(campos) == 2
        assert list(campos) == ["a", "b"]

    def test_payload_nao_mapping_e_vazio(self) -> None:
        assert len(ModalFields(None)) == 0


class TestResponderType:
    """R4: `StrEnum` porque os dois namespaces do Discord colidem."""

    def test_colisao_dos_numeros_existe(self) -> None:
        assert int(ComponentType.USER_SELECT) == int(InteractionType.MODAL_SUBMIT) == 5
        assert (
            int(ComponentType.TEXT_INPUT)
            == int(InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE)
            == 4
        )

    def test_de_interacao_componente(self) -> None:
        assert ResponderType.de_interacao(3, 2) is ResponderType.BUTTON
        assert ResponderType.de_interacao(3, 3) is ResponderType.STRING_SELECT

    def test_de_interacao_modal_e_autocomplete(self) -> None:
        assert ResponderType.de_interacao(5) is ResponderType.MODAL_SUBMIT
        assert ResponderType.de_interacao(4) is ResponderType.AUTOCOMPLETE

    def test_de_interacao_sem_component_type_e_erro(self) -> None:
        with pytest.raises(ValueError, match="component_type"):
            ResponderType.de_interacao(3, None)

    def test_selects_lista_os_cinco(self) -> None:
        assert len(ResponderType.selects()) == 5

    def test_modal_alias(self) -> None:
        """A ideia 07 escreve `ResponderType.MODAL`; um alias de classe
        não pode ser membro duplicado do StrEnum (R4)."""
        assert ResponderType.modal() is ResponderType.MODAL_SUBMIT
