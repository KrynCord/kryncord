"""Máquina de estados da resposta a interação — `0016`, completada no `0031`.

O ponto todo: violar a ordem é **nosso** erro, com a ação e o estado
na mensagem — não um 400 genérico do Discord que não diz qual chamada
saiu fora de hora.

Nenhum teste aqui toca na rede: o `InteractionsAPI` é um dublê que
registra chamadas.
"""

from __future__ import annotations

import time

import pytest

from kryncord.errors import InvalidInteractionState
from kryncord.interactions import InteractionContext, InteractionState
from kryncord.interactions.response import _TRANSICOES, DISCORD_EPOCH_MS
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


def _interacao(id: int = 1) -> Interaction:
    return Interaction(id=id, application_id=APP, type=2, token=TOKEN, guild_id=2, channel_id=3)


def _contexto(id: int = 1) -> tuple[InteractionContext, ApiFalsa]:
    api = ApiFalsa()
    return InteractionContext(_interacao(id), api), api


def _snowflake_de(ms_atras: int) -> int:
    """Um snowflake com a idade pedida — o id carrega o próprio instante."""
    ms = int(time.time() * 1000) - DISCORD_EPOCH_MS - ms_atras
    return (ms << 22) | 5


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
        assert ctx.is_expired() is False

    async def test_respond_vai_para_respondido(self) -> None:
        ctx, api = _contexto()

        await ctx.respond("oi")

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

        await ctx.edit_original_response("pronto")

        assert ctx.state is InteractionState.ANSWERED

    async def test_edit_de_answered_e_idempotente(self) -> None:
        """Responder e depois editar é o fluxo normal — não é erro."""
        ctx, api = _contexto()
        await ctx.respond("oi")

        await ctx.edit_original_response("outra")

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond", "edit_message"]

    async def test_open_modal_de_unanswered_e_terminal(self) -> None:
        """O Discord aceita modal como resposta inicial — não é erro."""
        ctx, api = _contexto()

        await ctx.open_modal({"title": "x"})

        assert ctx.state is InteractionState.MODAL_OPENED
        assert ctx.is_responded() is True
        assert api.nomes == ["show_modal"]

    async def test_open_modal_de_deferred_tambem(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        await ctx.open_modal({"title": "x"})

        assert ctx.state is InteractionState.MODAL_OPENED


# --------------------------------------------------------------------------
# Transições proibidas
# --------------------------------------------------------------------------


class TestTransicoesProibidas:
    async def test_respond_depois_de_respond_e_erro(self) -> None:
        """Resposta dupla é o erro que mais aparece em bot — e o do
        Discord é um 400 sem dizer qual chamada."""
        ctx, api = _contexto()
        await ctx.respond("oi")

        with pytest.raises(InvalidInteractionState) as info:
            await ctx.respond("de novo")

        texto = str(info.value)
        assert "respond()" in texto
        assert "ANSWERED" in texto
        assert "edit_original_response()" in texto  # diz a saída
        assert api.nomes == ["respond"]  # a segunda não foi mandada

    async def test_respond_depois_de_defer_e_erro(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        with pytest.raises(InvalidInteractionState, match="DEFERRED"):
            await ctx.respond("oi")

    async def test_defer_depois_de_respond_e_erro(self) -> None:
        ctx, _ = _contexto()
        await ctx.respond("oi")

        with pytest.raises(InvalidInteractionState):
            await ctx.defer()

    async def test_respond_depois_de_modal_e_erro(self) -> None:
        """Modal é terminal — o envio é uma interação nova."""
        ctx, _ = _contexto()
        await ctx.open_modal({"title": "x"})

        with pytest.raises(InvalidInteractionState, match="terminal"):
            await ctx.respond("oi")

    async def test_edit_de_unanswered_e_erro(self) -> None:
        """Não há resposta original para editar."""
        ctx, _ = _contexto()

        with pytest.raises(InvalidInteractionState):
            await ctx.edit_original_response("x")

    async def test_mensagem_de_erro_nao_quebra_no_unanswered(self) -> None:
        """Regressão: o mapa da saída não tinha entrada para
        `UNANSWERED`, então a própria mensagem de erro virava
        `KeyError` — mascarando o problema real com um erro que não
        diz nada."""
        ctx, _ = _contexto()

        with pytest.raises(InvalidInteractionState) as info:
            await ctx.edit_original_response("x")

        assert "UNANSWERED" in str(info.value)
        assert "respond()" in str(info.value)

    async def test_mensagem_de_erro_nomeia_o_estado_em_todos(self) -> None:
        """Cada estado tem que ter saída nomeada — sem entrada, o
        lookup da mensagem falha no lugar do erro."""
        ctx, _ = _contexto()
        await ctx.open_modal({"title": "x"})

        with pytest.raises(InvalidInteractionState, match="MODAL_OPENED"):
            await ctx.respond("x")

    async def test_delete_de_unanswered_e_erro(self) -> None:
        ctx, _ = _contexto()

        with pytest.raises(InvalidInteractionState):
            await ctx.delete_original_response()

    async def test_followup_de_unanswered_e_erro(self) -> None:
        """O follow-up referencia a resposta original — que ainda não
        existe. O Discord recusa, e a mensagem dele não diz por quê."""
        ctx, _ = _contexto()

        with pytest.raises(InvalidInteractionState, match="resposta inicial"):
            await ctx.followup("x")

    async def test_followup_depois_de_defer_funciona(self) -> None:
        ctx, api = _contexto()
        await ctx.defer()

        await ctx.followup("extra")

        assert api.nomes == ["defer", "followup"]


# --------------------------------------------------------------------------
# delete_original_response -> COMPLETED
# --------------------------------------------------------------------------


class TestCompleted:
    async def test_delete_de_answered_vai_para_completed(self) -> None:
        """Apagada a resposta original, não há mais o que editar nela."""
        ctx, api = _contexto()
        await ctx.respond("oi")

        await ctx.delete_original_response()

        assert ctx.state is InteractionState.COMPLETED
        assert api.nomes == ["respond", "delete_message"]

    async def test_delete_de_deferred_tambem(self) -> None:
        ctx, _ = _contexto()
        await ctx.defer()

        await ctx.delete_original_response()

        assert ctx.state is InteractionState.COMPLETED

    async def test_edit_de_completed_e_erro(self) -> None:
        ctx, _ = _contexto()
        await ctx.respond("oi")
        await ctx.delete_original_response()

        with pytest.raises(InvalidInteractionState, match="apagada"):
            await ctx.edit_original_response("x")

    async def test_followup_de_completed_funciona(self) -> None:
        """O follow-up é outro webhook message, não a resposta original."""
        ctx, api = _contexto()
        await ctx.respond("oi")
        await ctx.delete_original_response()

        await ctx.followup("ainda dá")

        assert api.nomes == ["respond", "delete_message", "followup"]


# --------------------------------------------------------------------------
# Expiração — o token vale 15 minutos
# --------------------------------------------------------------------------


class TestExpirado:
    def test_id_sintetico_nunca_expira(self) -> None:
        """`id=1` não é snowflake — julgar a idade dele seria inventar
        uma resposta para uma pergunta que o dado não faz."""
        ctx, _ = _contexto(id=1)

        assert ctx.is_expired() is False
        assert ctx.state is InteractionState.UNANSWERED

    def test_token_de_16_minutos_esta_expirado(self) -> None:
        ctx, _ = _contexto(id=_snowflake_de(16 * 60 * 1000))

        assert ctx.is_expired() is True
        assert ctx.state is InteractionState.EXPIRED

    def test_token_fresco_nao(self) -> None:
        ctx, _ = _contexto(id=_snowflake_de(60 * 1000))

        assert ctx.is_expired() is False
        assert ctx.state is not InteractionState.EXPIRED

    async def test_operacao_com_token_expirado_e_erro(self) -> None:
        """Nenhum callback funciona mais — e a mensagem diz isso, não a
        ordem das chamadas."""
        ctx, api = _contexto(id=_snowflake_de(16 * 60 * 1000))

        with pytest.raises(InvalidInteractionState, match="expirado"):
            await ctx.respond("oi")

        assert api.nomes == []

    async def test_followup_com_token_expirado_tambem(self) -> None:
        ctx, api = _contexto(id=_snowflake_de(16 * 60 * 1000))

        with pytest.raises(InvalidInteractionState, match="expirado"):
            await ctx.followup("x")

        assert api.nomes == []

    def test_expiracao_nao_atrapalha_o_fluxo_normal(self) -> None:
        """Snowflake de verdade e dentro da validade: a expiração é
        pergunta respondida com "não", não um guarda a mais no caminho."""
        ctx, _ = _contexto(id=_snowflake_de(60 * 1000))

        assert ctx.state is InteractionState.UNANSWERED
        assert ctx.is_expired() is False


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
        await ctx.respond("oi")

        await ctx.ack()

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond"]

    async def test_ack_de_modal_e_noop(self) -> None:
        ctx, api = _contexto()
        await ctx.open_modal({"title": "x"})

        await ctx.ack()

        assert ctx.state is InteractionState.MODAL_OPENED
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
        `InvalidInteractionState` **antes** de qualquer comparação de
        flag.

        Este teste é a prova de que a máquina de estados cobre o caso,
        e de que não precisa de um guarda separado. Um segundo guarda
        seria código que nunca roda — e pior: daria a impressão de uma
        proteção que não existe."""
        ctx, api = _contexto()
        await ctx.defer(ephemeral=True)

        with pytest.raises(InvalidInteractionState):
            await ctx.defer(ephemeral=False)

        assert api.nomes == ["defer"]


# --------------------------------------------------------------------------
# Falha da API não avança o estado
# --------------------------------------------------------------------------


class TestFalhaDaApi:
    async def test_respond_que_falha_nao_muda_estado(self) -> None:
        """Se a requisição falhou, a interação **não** foi respondida.
        Avançar o estado aqui faria o dispatcher achar que já respondeu
        e engolir o erro."""
        ctx, api = _contexto()
        api.quebra = RuntimeError("sem rede")

        with pytest.raises(RuntimeError, match="sem rede"):
            await ctx.respond("oi")

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
            await ctx.respond("oi")

        api.quebra = None
        await ctx.respond("agora vai")

        assert ctx.state is InteractionState.ANSWERED
        assert api.nomes == ["respond"]


# --------------------------------------------------------------------------
# Transições — a tabela inteira
# --------------------------------------------------------------------------


class TestTabela:
    def test_todo_estado_tem_entradas(self) -> None:
        """Cada estado tem uma linha — sem entrada, a ação é proibida,
        e isso é a regra, não um esquecimento. `EXPIRED` é a exceção
        honesta: ele não transiciona para nada, e a linha vazia é o
        contrato."""
        assert set(_TRANSICOES) == set(InteractionState)

    def test_unanswered_so_tem_resposta_inicial(self) -> None:
        """O único estado de onde uma resposta inicial sai — e não tem
        `edit`, porque não há o que editar."""
        linha = _TRANSICOES[InteractionState.UNANSWERED]

        assert set(linha) == {
            "respond",
            "defer",
            "defer_update",
            "update",
            "open_modal",
            "launch_activity",
            "ack",
        }

    def test_modal_nao_tem_saida_de_resposta(self) -> None:
        """Terminal: só `ack` continua funcionando, e como no-op."""
        linha = _TRANSICOES[InteractionState.MODAL_OPENED]

        assert set(linha) == {"ack"}

    def test_expired_nao_transiciona(self) -> None:
        """Token vencido — não há mais nenhuma ação possível."""
        assert _TRANSICOES[InteractionState.EXPIRED] == {}
