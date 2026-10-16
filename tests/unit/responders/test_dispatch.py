"""`dispatch.py` — do clique ao handler, e o `emit_responder` (ideia 09).

O fio: `block()` para tudo **inclusive** o `on_not_found` — a 0017
sobrescreveu a ideia 11 nisso, e o teste é a prova viva da decisão.

Nenhum teste toca na rede: o `InteractionsAPI` é um dublê.
"""

from __future__ import annotations

import pytest

from kryncord.enums import ResponderType
from kryncord.errors import DispatchError
from kryncord.interactions.response import InteractionContext
from kryncord.models.interaction import Interaction
from kryncord.responders.context import ResponderContext
from kryncord.responders.decorators import responder
from kryncord.responders.dispatch import (
    MAX_PROFUNDIDADE,
    Esperas,
    block,
    dispatch_responder,
    emit_responder,
)
from kryncord.responders.registry import ResponderRegistry

B = [ResponderType.BUTTON]


class ApiFalsa:
    """Dublê do `InteractionsAPI` — registra, não manda."""

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


def _botao(custom_id: str, *, mensagem_id: int | None = 555) -> Interaction:
    raw: dict = {
        "id": "1",
        "application_id": "1",
        "type": 3,
        "token": "t",
        "data": {"custom_id": custom_id, "component_type": 2},
    }
    if mensagem_id is not None:
        raw["message"] = {"id": str(mensagem_id)}
    return Interaction.from_payload(raw)


class CacheFalso:
    def __init__(self, mensagens: dict[int, object] | None = None) -> None:
        self.mensagens = mensagens or {}

    def get_message(self, mid: int | str):
        #: O id chega como string do payload bruto — o ConnectionState
        #: real normaliza na chave, o dublê faz o mesmo.
        return self.mensagens.get(int(mid))


class ClientFalso:
    def __init__(self, cache=None) -> None:
        self.cache = cache


class TestDispatch:
    async def test_roda_handler_com_params_injetados(self) -> None:
        reg = ResponderRegistry()
        recebido: dict = {}

        async def h(ctx, user_id: int, action: str):
            recebido["user_id"] = user_id
            recebido["action"] = action
            recebido["custom_id"] = ctx.custom_id
            recebido["is_button"] = ctx.is_button()

        responder("/manage/user/:user_id/:action", types=B, registry=reg)(h)

        ok = await dispatch_responder(_botao("/manage/user/123/ban"), ApiFalsa(), registry=reg)

        assert ok is True
        assert recebido["user_id"] == 123
        assert recebido["action"] == "ban"
        assert recebido["custom_id"] == "/manage/user/123/ban"
        assert recebido["is_button"] is True

    async def test_sem_handler_chama_on_not_found(self) -> None:
        reg = ResponderRegistry()
        chamados: list = []

        async def not_found(ctx):
            chamados.append(ctx.custom_id)
            await ctx.reply("Isso não foi configurado ainda.", ephemeral=True)

        ok = await dispatch_responder(
            _botao("/ninguem"),
            ApiFalsa(),
            registry=reg,
            on_not_found=not_found,
        )

        assert ok is False
        assert chamados == ["/ninguem"]

    async def test_sem_handler_sem_on_not_found(self) -> None:
        reg = ResponderRegistry()

        ok = await dispatch_responder(_botao("/ninguem"), ApiFalsa(), registry=reg)

        assert ok is False

    async def test_tipo_errado_e_como_nao_existir(self) -> None:
        """Botão registrado, chegou select — é `on_not_found`, não o
        handler errado rodando."""
        reg = ResponderRegistry()
        chamados: list = []

        async def h(ctx): ...

        async def not_found(ctx):
            chamados.append(1)

        responder("/a", types=B, registry=reg)(h)

        raw = {
            "id": "1",
            "application_id": "1",
            "type": 3,
            "token": "t",
            "data": {"custom_id": "/a", "component_type": 3},
        }
        ok = await dispatch_responder(
            Interaction.from_payload(raw), ApiFalsa(), registry=reg, on_not_found=not_found
        )

        assert ok is False
        assert chamados == [1]


class TestCachePolitica:
    """ "`cache="cached"`: só dispara com a mensagem no cache (K2)."""

    async def test_cached_com_mensagem_no_cache(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def h(ctx):
            rodou.append(1)

        responder("/a", types=B, cache="cached", registry=reg)(h)
        client = ClientFalso(CacheFalso(mensagens={555: object()}))

        ok = await dispatch_responder(_botao("/a"), ApiFalsa(), registry=reg, client=client)

        assert ok is True
        assert rodou == [1]

    async def test_cached_sem_mensagem_no_cache_nao_dispara(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def h(ctx):
            rodou.append(1)

        responder("/a", types=B, cache="cached", registry=reg)(h)

        ok = await dispatch_responder(
            _botao("/a"), ApiFalsa(), registry=reg, client=ClientFalso(CacheFalso())
        )

        assert ok is False
        assert rodou == []

    async def test_fresh_dispara_fora_do_cache(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def h(ctx):
            rodou.append(1)

        responder("/a", types=B, cache="fresh", registry=reg)(h)

        com_cache = await dispatch_responder(
            _botao("/a"), ApiFalsa(), registry=reg, client=ClientFalso(CacheFalso({555: object()}))
        )
        sem_cache = await dispatch_responder(
            _botao("/a"), ApiFalsa(), registry=reg, client=ClientFalso(CacheFalso())
        )

        assert com_cache is False
        assert sem_cache is True
        assert rodou == [1]


class TestMiddleware:
    async def test_block_para_handler_e_on_not_found(self) -> None:
        """0017: `block()` aborta tudo. A ideia 11 dizia que
        `on_not_found` sobrevivia — foi sobrescrito."""
        reg = ResponderRegistry()
        rodou: list = []

        async def proibe(ctx, block_fn):
            rodou.append("middleware")
            block_fn()

        async def h(ctx):
            rodou.append("handler")

        async def not_found(ctx):
            rodou.append("on_not_found")

        responder("/a", types=B, registry=reg)(h)

        ok = await dispatch_responder(
            _botao("/a"), ApiFalsa(), registry=reg, middleware=[proibe], on_not_found=not_found
        )

        assert ok is True
        assert rodou == ["middleware"]

    async def test_sem_block_a_fila_inteira_roda_em_ordem(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def m1(ctx, block_fn):
            rodou.append("m1")

        async def m2(ctx, block_fn):
            rodou.append("m2")

        async def h(ctx):
            rodou.append("handler")

        responder("/a", types=B, registry=reg)(h)

        await dispatch_responder(_botao("/a"), ApiFalsa(), registry=reg, middleware=[m1, m2])

        assert rodou == ["m1", "m2", "handler"]

    async def test_excecao_no_handler_vai_ao_on_error(self) -> None:
        reg = ResponderRegistry()
        erros: list = []

        async def h(ctx):
            raise RuntimeError("boom")

        async def on_error(ctx, exc):
            erros.append(exc)

        responder("/a", types=B, registry=reg)(h)

        ok = await dispatch_responder(_botao("/a"), ApiFalsa(), registry=reg, on_error=on_error)

        assert ok is True
        assert isinstance(erros[0], RuntimeError)

    async def test_excecao_sem_on_error_responde_ephemera(self) -> None:
        """O default do 0017: loga e responde efêmera — o usuário não
        vê o botão morrer em silêncio."""
        reg = ResponderRegistry()
        api = ApiFalsa()

        async def h(ctx):
            raise RuntimeError("boom")

        responder("/a", types=B, registry=reg)(h)

        ok = await dispatch_responder(_botao("/a"), api, registry=reg)

        assert ok is True
        assert api.chamadas == ["respond"]


def _contexto(interaction: Interaction) -> ResponderContext:
    api = ApiFalsa()
    return ResponderContext(InteractionContext(interaction, api))


class TestEmitResponder:
    async def test_emite_e_roda_handler(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def h(ctx, user_id: int):
            rodou.append(user_id)

        responder("/manage/user/:user_id/:action", types=B, registry=reg)(h)
        ctx = _contexto(_botao("/manage/user/123/ban"))

        ok = await emit_responder("/manage/user/456/kick", ctx, registry=reg)

        assert ok is True
        assert rodou == [456]

    async def test_ninguem_atende_devolve_false_sem_on_not_found(self) -> None:
        """K10: chamada programática não é "não foi configurado ainda".
        O aviso de usuário final por id que veio do nosso código seria
        expor erro que não é erro."""
        reg = ResponderRegistry()
        chamados: list = []

        async def not_found(ctx):
            chamados.append(1)

        ctx = _contexto(_botao("/ninguem"))

        ok = await emit_responder("/ninguem", ctx, registry=reg)

        assert ok is False
        assert chamados == []

    async def test_re_emitir_e_erro(self) -> None:
        reg = ResponderRegistry()

        async def h(ctx): ...

        responder("/a", types=B, registry=reg)(h)
        ctx = _contexto(_botao("/a"))

        await emit_responder("/a", ctx, registry=reg)

        with pytest.raises(DispatchError, match="já emitido"):
            await emit_responder("/a", ctx, registry=reg)

    async def test_force_re_emite(self) -> None:
        reg = ResponderRegistry()
        rodou: list = []

        async def h(ctx):
            rodou.append(1)

        responder("/a", types=B, registry=reg)(h)
        ctx = _contexto(_botao("/a"))

        await emit_responder("/a", ctx, registry=reg)
        ok = await emit_responder("/a", ctx, registry=reg, force=True)

        assert ok is True
        assert rodou == [1, 1]

    async def test_profundidade_acima_do_limite_e_erro(self) -> None:
        """Um responder emitindo a si mesmo não terminaria nunca — o
        guard existe porque `force=True` não abre a profundidade."""
        reg = ResponderRegistry()

        async def looper(ctx):
            await emit_responder("/loop", ctx, registry=reg, force=True)

        responder("/loop", types=B, registry=reg)(looper)
        ctx = _contexto(_botao("/loop"))

        with pytest.raises(DispatchError, match="aninhado"):
            await emit_responder("/loop", ctx, registry=reg, force=True)

    async def test_params_passados_pulam_o_parse(self) -> None:
        reg = ResponderRegistry()
        recebido: dict = {}

        async def h(ctx, user_id: int):
            recebido["user_id"] = user_id

        responder("/x/:user_id", types=B, registry=reg)(h)
        ctx = _contexto(_botao("/x/qualquer-coisa"))

        await emit_responder("/x/qualquer-coisa", ctx, registry=reg, params={"user_id": "777"})

        assert recebido["user_id"] == 777


class TestEsperas:
    async def test_resolve_entrega_o_retorno_do_handler(self) -> None:
        """`await_responder` observa sem consumir: o handler roda, e a
        espera recebe o que ele devolveu (0022 — transporte por
        retorno)."""
        reg = ResponderRegistry()
        esperas = Esperas()

        async def h(ctx):
            return {"nome": "ana"}

        responder("/register/form", types=B, registry=reg)(h)

        futura = esperas.registra("/register/form")
        import asyncio

        tarefa = asyncio.create_task(
            dispatch_responder(_botao("/register/form"), ApiFalsa(), registry=reg, esperas=esperas)
        )
        resultado = await asyncio.wait_for(futura, 2)
        await tarefa

        assert resultado == {"nome": "ana"}

    async def test_resolve_sem_esperas_devolve_false(self) -> None:
        esperas = Esperas()

        assert esperas.resolve("/nada", 1) is False


class TestBlockFn:
    def test_block_levanta_com_tags(self) -> None:
        from kryncord.errors import BlockHandlers

        with pytest.raises(BlockHandlers) as exc_info:
            block("morning", "noite")

        assert exc_info.value.args[0] == ("morning", "noite")


class TestLimite:
    def test_max_profundidade_e_cinco(self) -> None:
        """O número é contrato da ideia 09 §5 — mudar sem atualizar a
        decisão é mudar a API em silêncio."""
        assert MAX_PROFUNDIDADE == 5
