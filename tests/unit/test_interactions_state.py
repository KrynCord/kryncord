"""Máquina de estados da resposta a interação — `0016`.

O ponto todo: violar a ordem é **nosso** erro, com a ação e o estado
na mensagem — não um 400 genérico do Discord que não diz qual chamada
saiu fora de hora.

Nenhum teste aqui toca na rede: o `InteractionsAPI` é um dublê que
registra chamadas.
"""

from __future__ import annotations

import pytest

from kryncord.errors import InteractionStateError
from kryncord.interactions import InteractionContext, InteractionState
from kryncord.interactions.response import _TRANSICOES
from kryncord.models.interaction import Interaction

APP = 111
TOKEN = "tok"


class ApiFalsa:
    """Dublê do `InteractionsAPI` — registra, não manda."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, tuple, dict]] = []
        self.quebra: Exception | None = None

    def _registra(self, nome: str, args: tuple, kwargs: dict) -> None:
        if self.quebra is not None:
            raise self.quebra
        self.chamadas.append((nome, args, kwargs))

    async def respond(self, interaction, content=None, **kwargs):
        self._registra("respond", (interaction, content), kwargs)

    async def defer(self, interaction, *, ephemeral=False):
        self._registra("defer", (interaction,), {"ephemeral": ephemeral})

    async def defer_update(self, interaction):
        self._registra("defer_update", (interaction,), {})

    async def update_message(self, interaction, content=None, **kwargs):
        self._registra("update_message", (interaction, content), kwargs)

    async def show_modal(self, interaction, modal):
        self._registra("show_modal", (interaction, modal), {})

    async def launch_activity(self, interaction):
        self._registra("launch_activity", (interaction,), {})

    async def edit_message(
        self, application_id, token, message_id="@original", content=None, **kwargs
    ):
        self._registra("edit_message", (application_id, token, message_id, content), kwargs)

    async def delete_message(self, application_id, token, message_id="@original"):
        self._registra("delete_message", (application_id, token, message_id), {})

    async def fetch_message(self, application_id, token, message_id="@original"):
        self._registra("fetch_message", (application_id, token, message_id), {})
        return "mensagem"

    async def followup(self, application_id, token, content=None, **kwargs):
        self._registra("followup", (application_id, token, content), kwargs)
        return "mensagem"

    @property
    def nomes(self) -> list[str]:
        return [c[0] for c in self.chamadas]


def _interacao() -> Interaction:
    return Interaction(id=1, application_id=APP, type=2, token=TOKEN, guild_id=2, channel_id=3)


def _contexto() -> tuple[InteractionContext, ApiFalsa]:
    api = ApiFalsa()
    return InteractionContext(_interacao(), api), api


# --------------------------------------------------------------------------
# Estados e transições
# --------------------------------------------------------------------------


class TestEstados:
    def test_nasce_nao_respondido(self) -> None:
        ctx, _ = _contexto()

        assert ctx.state is InteractionState.UNANSWERED
        assert ctx.is_responded() is False
        assert ctx.is_deferred() is False
        assert ctx.is_answered() is False

    async def test_reply_vai_para_respondido(self) -> None:
        ctx, api = _contexto()

        await ctx.reply("oi")

        assert ctx.state is InteractionState.ANSWERED
        assert ctx.is_responded() is True
        assert api.nomes == ["respond"]

    async def test_defer_vai_para_deferido(self) -> None:
        ctx, api = _contexto()

        await ctx.defer()

        assert ctx.state is InteractionState.DEFERRED
        # Um defer já respondeu — é por isso que o nome é `responded`.
        assert ctx.is_responded() is True
        assert ctx.is_deferred() is True
        assert api.nomes == ["defer"]

    async def test_edit_de_deferred_finaliza(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        await ctx.edit("pronto")

        assert ctx.state is InteractionState.ANSWERED

    async def test_edit_de_answered_e_idempotente(self) -> None:
        """Responder e depois editar é o fluxo normal — não é erro."""
        ctx, api = _contexto()
        await ctx.reply("oi")

        await ctx.edit("outra")

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond", "edit_message"]

    async def test_send_modal_de_unanswered_e_terminal(self) -> None:
        """O Discord aceita modal como resposta inicial — não é erro."""
        ctx, api = _contexto()

        await ctx.send_modal({"title": "x"})

        assert ctx.state is InteractionState.MODAL
        assert ctx.is_responded() is True
        assert api.nomes == ["show_modal"]

    async def test_send_modal_de_deferred_tambem(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        await ctx.send_modal({"title": "x"})

        assert ctx.state is InteractionState.MODAL


# --------------------------------------------------------------------------
# Transições proibidas
# --------------------------------------------------------------------------


class TestTransicoesProibidas:
    async def test_reply_depois_de_reply_e_erro(self) -> None:
        """Resposta dupla é o erro que mais aparece em bot — e o do
        Discord é um 400 sem dizer qual chamada."""
        ctx, api = _contexto()
        await ctx.reply("oi")

        with pytest.raises(InteractionStateError) as info:
            await ctx.reply("de novo")

        texto = str(info.value)
        assert "reply()" in texto
        assert "ANSWERED" in texto
        assert "edit()" in texto  # diz a saída
        assert api.nomes == ["respond"]  # a segunda não foi mandada

    async def test_reply_depois_de_defer_e_erro(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        with pytest.raises(InteractionStateError, match="DEFERRED"):
            await ctx.reply("oi")

    async def test_defer_depois_de_reply_e_erro(self) -> None:
        ctx, _ = _contexto()
        await ctx.reply("oi")

        with pytest.raises(InteractionStateError):
            await ctx.defer()

    async def test_reply_depois_de_modal_e_erro(self) -> None:
        """Modal é terminal — não há mais resposta nesta interação."""
        ctx, _ = _contexto()
        await ctx.send_modal({"title": "x"})

        with pytest.raises(InteractionStateError, match="terminal"):
            await ctx.reply("oi")

    async def test_edit_de_unanswered_e_erro(self) -> None:
        """Não há resposta original para editar."""
        ctx, _ = _contexto()

        with pytest.raises(InteractionStateError):
            await ctx.edit("x")

    async def test_mensagem_de_erro_nao_quebra_no_unanswered(self) -> None:
        """Regressão: o mapa da saída não tinha entrada para
        `UNANSWERED`, então a própria mensagem de erro virava
        `KeyError` — mascarando o problema real com um erro que não
        diz nada."""
        ctx, _ = _contexto()

        with pytest.raises(InteractionStateError) as info:
            await ctx.edit("x")

        assert "UNANSWERED" in str(info.value)
        assert "reply()" in str(info.value)

    async def test_mensagem_de_erro_nomeia_o_estado_em_todos(self) -> None:
        """Cada estado tem que ter saída nomeada — sem entrada, o
        lookup da mensagem falha no lugar do erro."""
        ctx, _ = _contexto()
        await ctx.send_modal({"title": "x"})

        with pytest.raises(InteractionStateError, match="MODAL"):
            await ctx.reply("x")

    async def test_delete_de_unanswered_e_erro(self) -> None:
        ctx, _ = _contexto()

        with pytest.raises(InteractionStateError):
            await ctx.delete()

    async def test_follow_up_de_unanswered_e_erro(self) -> None:
        """O follow-up referencia a resposta original — que ainda não
        existe. O Discord recusa, e a mensagem dele não diz por quê."""
        ctx, _ = _contexto()

        with pytest.raises(InteractionStateError, match="resposta inicial"):
            await ctx.follow_up("x")

    async def test_follow_up_depois_de_defer_funciona(self) -> None:
        ctx, api = _contexto()
        await ctx.defer()

        await ctx.follow_up("extra")

        assert api.nomes == ["defer", "followup"]


# --------------------------------------------------------------------------
# ack idempotente
# --------------------------------------------------------------------------


class TestAck:
    async def test_ack_de_unanswered_faz_defer(self) -> None:
        ctx, api = _contexto()

        await ctx.ack()

        assert ctx.state is InteractionState.DEFERRED
        assert api.nomes == ["defer"]

    async def test_ack_de_deferred_e_noop(self) -> None:
        """Reclamar que já foi acknowledge seria dizer que o chamador
        errou por ter atingido o objetivo."""
        ctx, api = _contexto()
        await ctx.defer()

        await ctx.ack()

        assert ctx.state is InteractionState.DEFERRED
        assert api.nomes == ["defer"]

    async def test_ack_de_answered_e_noop(self) -> None:
        ctx, api = _contexto()
        await ctx.reply("oi")

        await ctx.ack()

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond"]

    async def test_ack_de_modal_e_noop(self) -> None:
        ctx, api = _contexto()
        await ctx.send_modal({"title": "x"})

        await ctx.ack()

        assert ctx.state is InteractionState.MODAL
        assert api.nomes == ["show_modal"]


# --------------------------------------------------------------------------
# Ephemeral
# --------------------------------------------------------------------------


class TestEphemeral:
    async def test_ephemeral_na_primeira_resposta_funciona(self) -> None:
        ctx, api = _contexto()

        await ctx.defer(ephemeral=True)

        assert api.chamadas[0][2]["ephemeral"] is True

    async def test_segunda_resposta_ephemeral_e_erro_de_estado(self) -> None:
        """O `0016` dizia que flag repetida é ok e contraditória é
        `ValueError` — mas isso é inalcançável: a segunda resposta já é
        `InteractionStateError` **antes** de qualquer comparação de
        flag.

        Este teste é a prova de que a máquina de estados cobre o caso,
        e de que não precisa de um guarda separado. Um segundo guarda
        seria código que nunca roda — e pior: daria a impressão de uma
        proteção que não existe."""
        ctx, api = _contexto()
        await ctx.defer(ephemeral=True)

        with pytest.raises(InteractionStateError):
            await ctx.defer(ephemeral=False)

        assert api.nomes == ["defer"]


# --------------------------------------------------------------------------
# Falha da API não avança o estado
# --------------------------------------------------------------------------


class TestFalhaDaApi:
    async def test_reply_que_falha_nao_muda_estado(self) -> None:
        """Se a requisição falhou, a interação **não** foi respondida.
        Avançar o estado aqui faria o dispatcher achar que já respondeu
        e engolir o erro."""
        ctx, api = _contexto()
        api.quebra = RuntimeError("sem rede")

        with pytest.raises(RuntimeError, match="sem rede"):
            await ctx.reply("oi")

        assert ctx.state is InteractionState.UNANSWERED

    async def test_defer_que_falha_nao_muda_estado(self) -> None:
        ctx, api = _contexto()
        api.quebra = RuntimeError("sem rede")

        with pytest.raises(RuntimeError):
            await ctx.defer()

        assert ctx.state is InteractionState.UNANSWERED

    async def test_estado_fica_estavel_para_tentar_de_novo(self) -> None:
        """Falhou, tenta de novo — e o retry tem que funcionar."""
        ctx, api = _contexto()
        api.quebra = RuntimeError("sem rede")

        with pytest.raises(RuntimeError):
            await ctx.reply("oi")

        api.quebra = None
        await ctx.reply("agora vai")

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond"]


# --------------------------------------------------------------------------
# Transições — a tabela inteira
# --------------------------------------------------------------------------


class TestTabela:
    def test_todo_estado_tem_entradas(self) -> None:
        """Cada estado tem uma linha — sem entrada, a ação é proibida,
        e isso é a regra, não um esquecimento."""
        assert set(_TRANSICOES) == set(InteractionState)

    def test_unanswered_so_tem_resposta_inicial(self) -> None:
        """O único estado de onde uma resposta inicial sai — e não tem
        `edit`, porque não há o que editar."""
        linha = _TRANSICOES[InteractionState.UNANSWERED]

        assert set(linha) == {
            "reply",
            "defer",
            "defer_update",
            "update",
            "send_modal",
            "launch_activity",
            "ack",
        }

    def test_modal_nao_tem_saida_de_resposta(self) -> None:
        """Terminal: só `ack` continua funcionando, e como no-op."""
        linha = _TRANSICOES[InteractionState.MODAL]

        assert set(linha) == {"ack"}
