"""`CommandInteraction` e `OptionsAccessor` — `0012`, tipada no `0031`.

O fio: a interação tipada **compõe** o `InteractionContext`, não herda.
`interaction.respond()` é delegação — e a prova é que a máquina de
estados decide tudo, neste arquivo só se testa que a delegação chega lá.
"""

from __future__ import annotations

import pytest

from kryncord.errors import InvalidInteractionState
from kryncord.interactions import (
    CommandInteraction,
    InteractionContext,
    InteractionState,
    MessageCommandInteraction,
    UserCommandInteraction,
)
from kryncord.models.interaction import Interaction

APP = 111
TOKEN = "tok"


class ApiFalsa:
    def __init__(self) -> None:
        self.chamadas: list[str] = []

    async def respond(self, interaction, content=None, **kwargs):
        self.chamadas.append("respond")

    async def defer(self, interaction, *, ephemeral=False):
        self.chamadas.append("defer")

    async def defer_update(self, interaction):
        self.chamadas.append("defer_update")

    async def update_message(self, interaction, content=None, **kwargs):
        self.chamadas.append("update_message")

    async def show_modal(self, interaction, modal):
        self.chamadas.append("show_modal")

    async def launch_activity(self, interaction):
        self.chamadas.append("launch_activity")

    async def edit_message(
        self, application_id, token, message_id="@original", content=None, **kwargs
    ):
        self.chamadas.append("edit_message")

    async def delete_message(self, application_id, token, message_id="@original"):
        self.chamadas.append("delete_message")

    async def fetch_message(self, application_id, token, message_id="@original"):
        self.chamadas.append("fetch_message")
        return "mensagem"

    async def followup(self, application_id, token, content=None, **kwargs):
        self.chamadas.append("followup")
        return "ok"


def _interacao(opcoes: list[dict] | None = None, data_extra: dict | None = None) -> Interaction:
    data: dict = {"options": opcoes or []}
    if data_extra:
        data.update(data_extra)
    return Interaction(
        id=1,
        application_id=APP,
        type=2,
        token=TOKEN,
        guild_id=2,
        channel_id=3,
        data=data,
    )


def _contexto(
    opcoes: list[dict] | None = None,
    data_extra: dict | None = None,
    *,
    classe: type[CommandInteraction] = CommandInteraction,
) -> tuple[CommandInteraction, ApiFalsa]:
    """A interação tipada e o dublê de API — a classe vem do tipo de
    comando registrado (`0031`), nunca da anotação do handler."""
    api = ApiFalsa()
    ic = InteractionContext(_interacao(opcoes, data_extra), api)
    return classe(ic, client=None), api


# --------------------------------------------------------------------------
# Delegação — um só dono do estado
# --------------------------------------------------------------------------


class TestDelegacao:
    async def test_respond_chega_na_maquina(self) -> None:
        """A prova da composição: o estado muda porque o
        `InteractionContext` decidiu, não porque a interação tipada
        reimplementou."""
        ctx, api = _contexto()

        await ctx.respond("oi")

        assert ctx.is_responded() is True
        assert ctx.response_state is InteractionState.ANSWERED
        assert api.chamadas == ["respond"]

    async def test_defer_tambem(self) -> None:
        ctx, api = _contexto()

        await ctx.defer(ephemeral=True)

        assert ctx.is_deferred() is True
        assert api.chamadas == ["defer"]

    async def test_transicao_proibida_propaga(self) -> None:
        """Não é `except` e re-levar: o erro da máquina chega como está."""
        ctx, _ = _contexto()
        await ctx.respond("oi")

        with pytest.raises(InvalidInteractionState):
            await ctx.respond("de novo")

    async def test_edit_e_followup_chegam(self) -> None:
        ctx, api = _contexto()
        await ctx.defer()

        await ctx.edit_original_response("pronto")
        await ctx.followup("extra")

        assert api.chamadas == ["defer", "edit_message", "followup"]

    async def test_ack_de_unanswered_faz_defer(self) -> None:
        ctx, api = _contexto()

        await ctx.ack()

        assert ctx.is_deferred() is True
        assert api.chamadas == ["defer"]


# --------------------------------------------------------------------------
# Campos
# --------------------------------------------------------------------------


class TestCampos:
    def test_interaction_e_o_payload(self) -> None:
        ctx, _ = _contexto()

        assert ctx.interaction.token == TOKEN
        assert ctx.interaction_context.interaction is ctx.interaction

    def test_state_nasce_vazio_e_e_o_mesmo_dict(self) -> None:
        """`ctx.state` é o cano entre middleware e handler — devolver
        dict novo a cada acesso quebraria a passagem de dado."""
        ctx, _ = _contexto()

        ctx.state["chave"] = 1

        assert ctx.state["chave"] == 1
        assert ctx.state is ctx.state

    def test_guild_channel_member_podem_ser_none(self) -> None:
        """DM não tem guild nem membro — e não é erro, é o caso."""
        ctx, _ = _contexto()

        assert ctx.guild is None
        assert ctx.channel is None
        assert ctx.member is None
        assert ctx.user is None


# --------------------------------------------------------------------------
# OptionsAccessor
# --------------------------------------------------------------------------


class TestOptions:
    def test_le_os_valores_crus(self) -> None:
        ctx, _ = _contexto([{"name": "nome", "type": 3, "value": "gustavo"}])

        assert ctx.options["nome"] == "gustavo"
        assert ctx.options.nome == "gustavo"
        assert "nome" in ctx.options

    def test_varias_opcoes(self) -> None:
        ctx, _ = _contexto(
            [
                {"name": "nome", "type": 3, "value": "ana"},
                {"name": "pontos", "type": 4, "value": 10},
                {"name": "ativo", "type": 5, "value": True},
            ]
        )

        assert dict(ctx.options.valores) == {"nome": "ana", "pontos": 10, "ativo": True}

    def test_opcao_nao_declarada_e_attribute_error(self) -> None:
        """Duas exceções diferentes porque são dois erros diferentes:
        "digitou errado" e "essa opção não existe"."""
        ctx, _ = _contexto([{"name": "nome", "type": 3, "value": "x"}])

        with pytest.raises(AttributeError, match="nao_declarada"):
            _ = ctx.options.nao_declarada

    def test_attribute_error_menciona_o_nome_digitado(self) -> None:
        """Sem isto, o Python devolveria um `AttributeError` de
        `__slots__` que nem menciona o nome."""
        ctx, _ = _contexto([{"name": "nome", "type": 3, "value": "x"}])

        with pytest.raises(AttributeError) as info:
            _ = ctx.options.pontoss

        assert "pontoss" in str(info.value)
        assert "disponíveis" in str(info.value)

    def test_key_desconhecida_e_key_error_com_disponiveis(self) -> None:
        ctx, _ = _contexto([{"name": "nome", "type": 3, "value": "x"}])

        with pytest.raises(KeyError) as info:
            ctx.options["outro"]

        assert "disponíveis" in str(info.value)

    def test_sem_opcoes_nao_quebra(self) -> None:
        """Comando sem parâmetro é o caso mais comum."""
        ctx, _ = _contexto()

        assert dict(ctx.options.valores) == {}
        assert "nome" not in ctx.options

    def test_data_none_nao_quebra(self) -> None:
        """Interação sem `data` — o Discord manda assim em alguns casos."""
        ctx, _ = _contexto()

        assert dict(ctx.options.valores) == {}

    def test_entrada_mal_formada_e_ignorada(self) -> None:
        """Uma opção sem `name` não pode virar entrada com chave `None`
        — seria um `None` que some no `sorted()` e aparece no erro."""
        ctx, _ = _contexto([{"type": 3, "value": "x"}])

        assert dict(ctx.options.valores) == {}


class TestGettersTipados:
    def test_get_string_e_get_int(self) -> None:
        ctx, _ = _contexto(
            [
                {"name": "nome", "type": 3, "value": "ana"},
                {"name": "pontos", "type": 4, "value": 10},
            ]
        )

        assert ctx.options.get_string("nome") == "ana"
        assert ctx.options.get_int("pontos") == 10

    def test_get_bool(self) -> None:
        ctx, _ = _contexto([{"name": "ativo", "type": 5, "value": True}])

        assert ctx.options.get_bool("ativo") is True

    def test_ausente_devolve_none(self) -> None:
        ctx, _ = _contexto()

        assert ctx.options.get_string("nome") is None
        assert ctx.options.get_int("pontos") is None

    def test_ausente_devolve_o_default(self) -> None:
        ctx, _ = _contexto()

        assert ctx.options.get_int("pontos", default=0) == 0

    def test_tipo_errado_e_erro_nao_default(self) -> None:
        """Fundir os dois faria o `default` mascarar um tipo errado —
        que é quase sempre bug na declaração da opção, não dado
        faltando."""
        ctx, _ = _contexto([{"name": "pontos", "type": 3, "value": "dez"}])

        with pytest.raises(TypeError, match="OptionType"):
            ctx.options.get_int("pontos")

    def test_erro_de_tipo_menciona_o_recebido(self) -> None:
        ctx, _ = _contexto([{"name": "pontos", "type": 3, "value": "dez"}])

        with pytest.raises(TypeError) as info:
            ctx.options.get_int("pontos")

        texto = str(info.value)
        assert "str" in texto and "int" in texto


class TestSubcommands:
    def test_opcoes_de_subcommand_sao_achatadas(self) -> None:
        """Com `/grupo sub op:1`, `ctx.options["op"]` funciona — sem o
        `getSubcommand()` do discord.js para chegar até ela."""
        ctx, _ = _contexto(
            [
                {
                    "name": "papel",
                    "type": 1,
                    "options": [{"name": "nome", "type": 3, "value": "admin"}],
                }
            ]
        )

        assert ctx.options["nome"] == "admin"
        assert ctx.options.get_subcommand() == "papel"
        assert ctx.options.get_subcommand_group() is None

    def test_grupo_de_dois_niveis(self) -> None:
        ctx, _ = _contexto(
            [
                {
                    "name": "config",
                    "type": 2,
                    "options": [
                        {
                            "name": "canal",
                            "type": 1,
                            "options": [{"name": "alvo", "type": 7, "value": "99"}],
                        }
                    ],
                }
            ]
        )

        assert ctx.options.get_subcommand_group() == "config"
        assert ctx.options.get_subcommand() == "canal"
        assert ctx.options["alvo"] == "99"

    def test_comando_simples_nao_tem_subcommand(self) -> None:
        ctx, _ = _contexto([{"name": "nome", "type": 3, "value": "ana"}])

        assert ctx.options.get_subcommand() is None


class TestGettersDeEntidade:
    """Opções USER/ROLE/CHANNEL/MENTIONABLE resolvem por `resolved` —
    o id vem em `value`, o objeto em `data.resolved` (0023 R8)."""

    def _ctx_resolved(self, opcoes: list, resolved: dict):
        return _contexto(opcoes, data_extra={"resolved": resolved})

    def test_get_user(self) -> None:
        from kryncord.models.user import User

        ctx, _ = self._ctx_resolved(
            [{"name": "alvo", "type": 6, "value": "42"}],
            {"users": {"42": {"id": "42", "username": "ana", "discriminator": "0001"}}},
        )

        usuario = ctx.options.get_user("alvo")

        assert isinstance(usuario, User)
        assert usuario.id == 42

    def test_get_member_funde_o_user(self) -> None:
        """Em `resolved`, `members[id]` vem **sem** `user` — fundir é o
        que evita que todo `member.user` seja `None` longe da causa."""
        ctx, _ = self._ctx_resolved(
            [{"name": "alvo", "type": 6, "value": "42"}],
            {
                "users": {"42": {"id": "42", "username": "ana", "discriminator": "0001"}},
                "members": {"42": {"nick": "aninha"}},
            },
        )

        membro = ctx.options.get_member("alvo")

        assert membro is not None
        assert membro.nick == "aninha"
        assert membro.user is not None
        assert membro.user.username == "ana"

    def test_get_role(self) -> None:
        from kryncord.models.role import Role

        ctx, _ = self._ctx_resolved(
            [{"name": "cargo", "type": 8, "value": "7"}],
            {
                "roles": {
                    "7": {
                        "id": "7",
                        "name": "admin",
                        "color": 0,
                        "hoist": False,
                        "position": 1,
                        "permissions": "8",
                        "managed": False,
                        "mentionable": False,
                    }
                }
            },
        )

        cargo = ctx.options.get_role("cargo")

        assert isinstance(cargo, Role)
        assert cargo.name == "admin"

    def test_get_mentionable_usuario(self) -> None:
        ctx, _ = self._ctx_resolved(
            [{"name": "alvo", "type": 9, "value": "42"}],
            {"users": {"42": {"id": "42", "username": "ana", "discriminator": "0001"}}},
        )

        assert ctx.options.get_mentionable("alvo") is not None

    def test_sem_resolved_devolve_none(self) -> None:
        ctx, _ = _contexto([{"name": "alvo", "type": 6, "value": "42"}])

        assert ctx.options.get_user("alvo") is None
        assert ctx.options.get_member("alvo") is None
        assert ctx.options.get_channel("alvo") is None
        assert ctx.options.get_attachment("alvo") is None


# --------------------------------------------------------------------------
# Context menu — 0022
# --------------------------------------------------------------------------


class TestAlvoDeMenu:
    def test_target_user_vem_do_resolved(self) -> None:
        ctx, _ = _contexto(
            data_extra={"resolved": {"users": {"42": {"id": "42", "username": "ana"}}}},
            classe=UserCommandInteraction,
        )

        assert ctx.target_user.id == 42
        assert ctx.target_user.username == "ana"

    def test_target_message_vem_do_resolved(self) -> None:
        ctx, _ = _contexto(
            data_extra={"resolved": {"messages": {"7": {"id": "7", "content": "oi"}}}},
            classe=MessageCommandInteraction,
        )

        assert ctx.target_message.id == 7
        assert ctx.target_message.content == "oi"

    def test_em_slash_e_attribute_error(self) -> None:
        """O alvo vem do clique — em `/comando` a classe de CHAT_INPUT
        nem expõe `target_user`, e o `AttributeError` aponta para o
        campo faltante."""
        ctx, _ = _contexto()

        with pytest.raises(AttributeError, match="target_user"):
            _ = ctx.target_user

    def test_target_member_sem_cache_e_none(self) -> None:
        """Sem `members` no resolved — o cache pode não ter guardado, e
        aí o alvo é `None`."""
        ctx, _ = _contexto(
            data_extra={"resolved": {"users": {"42": {}}}},
            classe=UserCommandInteraction,
        )

        assert ctx.target_member is None
