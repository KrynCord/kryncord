"""Testes do Bloco 7 — eventos: nomes, tabela, instantânea e `@event`.

Três camadas, e elas respondem perguntas diferentes (`0025`):

| Camada | Módulo | Pergunta |
|---|---|---|
| nomes | `events/names.py` | como o evento se chama |
| payloads | `events/payloads.py` | **quantos** argumentos o handler recebe |
| snapshot | `events/snapshot.py` | o que o cache tinha **antes** |

Nenhum teste aqui toca rede nem dorme. O `EventDispatcher` é construído
à mão em cada caso — registries compartilhados entre testes são
contaminação que aparece como falha num outro teste qualquer (`K12`).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kryncord.errors import BlockHandlers, EventDefinitionError
from kryncord.events import (
    EVENT_PAYLOADS,
    EventDispatcher,
    EventName,
    event,
    normalize_event_name,
)
from kryncord.events.context import EventFrame
from kryncord.events.payloads import id_de, ids_de, monta_args
from kryncord.events.snapshot import EVENTOS_COM_OLD, instantanea
from kryncord.internal.compose import block, compose
from kryncord.internal.tasks import TaskRegistry
from kryncord.models import Message, PartialMessage, Ready

MESSAGE_CREATE = {
    "id": "100",
    "channel_id": "200",
    "author": {"id": "1", "username": "x"},
    "content": "oi",
}


class _CacheFalso:
    """O mínimo do `ConnectionState` que a instantânea lê por contrato.

    `Any` e não `ConnectionState`: o `events/` não conhece o `state/`,
    e colocar o tipo real aqui reproduziria em teste o acoplamento que
    o módulo se recusa a ter.
    """

    __slots__ = ("canais", "guilds", "mensagens", "voz")

    def __init__(self) -> None:
        self.mensagens: dict[int, Any] = {}
        self.guilds: dict[int, Any] = {}
        self.canais: dict[int, Any] = {}
        self.voz: dict[tuple[int, int], Any] = {}

    def get_message(self, codigo: int) -> Any:
        return self.mensagens.get(codigo)

    def get_guild(self, codigo: int) -> Any:
        return self.guilds.get(codigo)

    def get_channel(self, codigo: int) -> Any:
        return self.canais.get(codigo)

    def get_voice_state(self, guild_id: int, user_id: int) -> Any:
        return self.voz.get((guild_id, user_id))


def coletor(lista: list[Any]) -> Any:
    async def _handler(*args: Any) -> None:
        lista.append(args)

    return _handler


# ==========================================================================
# Nomes
# ==========================================================================


class TestNomes:
    def test_screaming_vira_snake(self) -> None:
        assert normalize_event_name("MESSAGE_CREATE") == "message_create"

    def test_o_enum_tambem_funciona(self) -> None:
        assert normalize_event_name(EventName.MESSAGE_CREATE) == "message_create"

    def test_o_que_nao_catalogou_continua_como_veio(self) -> None:
        """A biblioteca não finge que entende o que ainda não
        catalogou (`0025` §2)."""
        assert normalize_event_name("GUILD_AUDIT_LOG_ENTRY_CREATE") == (
            "GUILD_AUDIT_LOG_ENTRY_CREATE"
        )

    def test_tabela_tem_quinze(self) -> None:
        """`0025`: a tabela é o contrato, e o tamanho dela é o número
        de assinaturas que a biblioteca consegue prometer."""
        assert len(EVENT_PAYLOADS) == 15

    def test_sete_eventos_nao_pagam_snapshot(self) -> None:
        """Os oito de `EVENTOS_COM_OLD` são os que entregam `old`."""
        assert len(EVENTOS_COM_OLD) == 8
        assert "message_create" not in EVENTOS_COM_OLD
        assert "voice_state_update" in EVENTOS_COM_OLD

    def test_tabela_e_formas_cobrem_os_mesmos(self) -> None:
        """Quem está na tabela tem forma; quem tem forma tem `old` ou
        não — mas ninguém fica de fora das duas."""
        from kryncord.events.payloads import _FORMAS

        assert set(_FORMAS) == set(EVENT_PAYLOADS)


# ==========================================================================
# Montagem de argumentos
# ==========================================================================


class TestMontaArgs:
    def test_unico_argumento_e_o_objeto(self) -> None:
        msg = Message.from_payload(MESSAGE_CREATE)
        assert monta_args("message_create", msg, None, MESSAGE_CREATE) == (msg,)

    def test_old_new_poe_o_cache_na_frente(self) -> None:
        """`message_update` entrega `(old, new)` — e o `old` vai
        primeiro porque é o que o handler está procurando."""
        novo = Message.from_payload(MESSAGE_CREATE)
        antigo = Message.from_payload({**MESSAGE_CREATE, "content": "antes"})

        assert monta_args("message_update", novo, antigo, MESSAGE_CREATE) == (antigo, novo)

    def test_id_old_entrega_o_id_nao_o_objeto(self) -> None:
        """`message_delete` não tem objeto nenhum: o parser não entra,
        porque dois campos não materializam uma mensagem."""
        assert monta_args("message_delete", MESSAGE_CREATE, None, MESSAGE_CREATE) == (100, None)

    def test_ids_olds_fica_alinhado_por_indice(self) -> None:
        """`None` marca a que o cache não tinha. Filtrar perderia a
        informação de qual faltou (`0025` §Quebras)."""
        data = {"ids": ["1", "2", "3"]}
        args = monta_args("message_delete_bulk", data, (None, "b", None), data)

        assert args == ((1, 2, 3), (None, "b", None))

    def test_ready_continua_com_o_modelo(self) -> None:
        """A correção do `0025` §2: o `0020` escrevia `ready -> ()`, e
        isso anularia o `0006` e o teste `test_ready_vira_modelo`."""
        bruto = {"v": 10, "user": {"id": "7", "username": "meu bot"}}
        pronto = Ready.from_payload(bruto)

        assert monta_args("ready", pronto, None, bruto) == (pronto,)

    def test_resumed_entrega_o_payload_cru(self) -> None:
        """`resumed` não tem parser, mas tem forma: o dicionário chega
        sozinho, e não vazio."""
        bruto = {"session_id": "abc"}

        assert monta_args("resumed", bruto, None, bruto) == (bruto,)

    def test_fora_da_tabela_vem_como_no_0006(self) -> None:
        """Evento fora da tabela devolve `(parsed,)` — trocar isso
        porque uma tabela nova apareceu seria quebrar o que funcionava."""
        bruto = {"user": {"id": "7"}, "status": "online"}

        assert monta_args("PRESENCE_UPDATE", bruto, None, bruto) == (bruto,)


class TestHelpersDeId:
    def test_aceita_string_e_int(self) -> None:
        assert id_de({"id": "123"}) == 123
        assert id_de({"id": 123}) == 123

    def test_bool_e_rejeitado_antes_de_int(self) -> None:
        """`true` é JSON quebrado, não o id 1."""
        assert id_de({"id": True}) is None

    def test_ids_descarta_o_item_quebrado(self) -> None:
        """Um item ruim não derruba o resto: as mensagens boas ainda
        podem ser apagadas do cache."""
        assert ids_de({"ids": ["1", "x", 2, True]}) == (1, 2)

    def test_payload_nao_mapping_devolve_vazio(self) -> None:
        assert id_de(None) is None
        assert ids_de(None) == ()


# ==========================================================================
# Instantânea
# ==========================================================================


class TestInstantanea:
    async def test_evento_sem_old_devolve_none_sem_perguntar(self) -> None:
        cache = _CacheFalso()
        assert instantanea("message_create", MESSAGE_CREATE, cache) is None

    async def test_message_update_le_antes_do_updater(self) -> None:
        cache = _CacheFalso()
        antigo = Message.from_payload({**MESSAGE_CREATE, "content": "antes"})
        cache.mensagens[100] = antigo

        assert instantanea("message_update", MESSAGE_CREATE, cache) is antigo

    async def test_message_delete_tambem_paga(self) -> None:
        cache = _CacheFalso()
        antigo = PartialMessage.from_payload(MESSAGE_CREATE)
        cache.mensagens[100] = antigo

        assert instantanea("message_delete", MESSAGE_CREATE, cache) is antigo

    async def test_bulk_devolve_dict_por_id(self) -> None:
        """`dict` e não lista: o `monta_args` precisa casar cada mensagem
        com o seu id, e nada garante que o cache devolveu na ordem."""
        cache = _CacheFalso()
        uma = PartialMessage.from_payload({"id": "1", "channel_id": "9"})
        cache.mensagens[1] = uma

        achado = instantanea("message_delete_bulk", {"ids": ["1", "2"]}, cache)

        assert achado == {1: uma, 2: None}

    async def test_voz_pergunta_com_guild_e_usuario(self) -> None:
        """Voz só existe dentro de servidor, e o estado é sempre de
        alguém — sem as duas pontas não há para onde perguntar."""
        cache = _CacheFalso()
        cache.voz[(10, 20)] = "estado-anterior"
        data = {"guild_id": "10", "user_id": "20"}

        assert instantanea("voice_state_update", data, cache) == "estado-anterior"

    async def test_voz_sem_guild_nao_pergunta(self) -> None:
        assert instantanea("voice_state_update", {"user_id": "20"}, _CacheFalso()) is None

    async def test_payload_nao_mapping_devolve_none(self) -> None:
        """`None` é "não há o que guardar", e não uma falha — é o
        caso legítimo de mensagem que o cache nunca viu."""
        assert instantanea("message_update", None, _CacheFalso()) is None

    async def test_guild_e_canal_tambem_pagam(self) -> None:
        cache = _CacheFalso()
        cache.guilds[5] = "g"
        cache.canais[5] = "c"

        assert instantanea("guild_update", {"id": "5"}, cache) == "g"
        assert instantanea("channel_update", {"id": "5"}, cache) == "c"


# ==========================================================================
# EventFrame
# ==========================================================================


class TestContexto:
    def test_normaliza_o_nome(self) -> None:
        frame = EventFrame("MESSAGE_CREATE", [])

        assert frame.name == "message_create"

    def test_args_e_list_e_mutavel(self) -> None:
        """A injeção de argumentos da ideia 10 §6 precisa de lista viva.
        Tupla imutável faria a injeção falhar em silêncio."""
        frame = EventFrame("message_create", ["a"])
        frame.args[0] = "b"

        assert frame.args == ["b"]

    def test_state_nasce_vazio_e_e_do_dispatch(self) -> None:
        frame = EventFrame("message_create", [])

        assert frame.state == {}

    def test_state_recebido_e_o_mesmo_objeto(self) -> None:
        """Compartilhado por dispatch (`0026` §D6) — a middleware
        escreve, o handler lê, e os dois estão no mesmo dicionário."""
        compartilhado: dict[str, Any] = {}
        frame = EventFrame("message_create", [], state=compartilhado)
        frame.state["chave"] = 1

        assert compartilhado == {"chave": 1}

    async def test_spawn_sem_registry_e_erro(self) -> None:
        """Task sem dono sobrevive ao client, e é o oposto do que
        "background" promete (0012)."""
        frame = EventFrame("message_create", [])

        async def nada() -> None:
            return None

        coro = nada()
        try:
            with pytest.raises(RuntimeError, match="TaskRegistry"):
                frame.spawn(coro)
        finally:
            coro.close()

    async def test_spawn_com_registry_devolve_task(self) -> None:
        tasks = TaskRegistry()
        frame = EventFrame("message_create", [], tasks=tasks)

        async def nada() -> None:
            return None

        tarefa = frame.spawn(nada(), nome="teste")

        try:
            await asyncio.wait_for(tarefa, timeout=1)
        finally:
            await tasks.cancela_todas()

    def test_repr_mostra_o_que_importa(self) -> None:
        frame = EventFrame("message_create", ["a", "b"])

        assert "message_create" in repr(frame)
        assert "args=2" in repr(frame)


# ==========================================================================
# @event — validação na importação
# ==========================================================================


class TestDecorator:
    def test_devolve_a_funcao_original(self) -> None:
        """Trocar a função por um registro quebraria `functools.wraps`
        e qualquer teste que inspeciona a função — sem ganhar nada."""
        dispatcher = EventDispatcher()

        async def meu(msg: Message) -> None: ...

        registrado = event("message_create", registry=dispatcher)(meu)

        assert registrado is meu

    def test_ready_e_once_forcado(self) -> None:
        """O anúncio de sessão acontece uma vez; um `ready` disparando
        duas vezes é um bot que "conecta" duas vezes (ideia 10 §3)."""
        dispatcher = EventDispatcher()

        @event("ready", registry=dispatcher)
        async def pronto(r: Ready) -> None: ...

        entrada = dispatcher._entradas_de("ready")[0]
        assert entrada.once is True

    def test_ready_com_once_false_e_erro(self) -> None:
        dispatcher = EventDispatcher()

        with pytest.raises(EventDefinitionError, match="once=True"):

            @event("ready", once=False, registry=dispatcher)
            async def pronto(r: Ready) -> None: ...

    def test_evento_inexistente_e_erro_com_sugestao(self) -> None:
        """Aceitar qualquer nome faria o handler nunca rodar em
        silêncio — o pior sintoma de diagnosticar."""
        dispatcher = EventDispatcher()

        with pytest.raises(EventDefinitionError, match="Quer dizer"):

            @event("message_creates", registry=dispatcher)
            async def errado(msg: Message) -> None: ...

    def test_aridade_errada_e_erro_na_importacao(self) -> None:
        dispatcher = EventDispatcher()

        with pytest.raises(EventDefinitionError, match="recebe 0 argumento"):

            @event("message_create", registry=dispatcher)
            async def curto() -> None: ...

    def test_args_pula_a_validacao_de_aridade(self) -> None:
        """`K9`: quem escreveu `*args` disse que não quer número nenhum."""
        dispatcher = EventDispatcher()

        @event("message_create", registry=dispatcher)
        async def generico(*args: Any) -> None: ...

        assert len(dispatcher.handlers_for("message_create")) == 1

    def test_anotacao_incompativel_e_erro(self) -> None:
        """Reduzido pelo `0025` §3 ao que é honesto: só incompatibilidade
        declarada. Anotar `str` onde a tabela promete `Message` é erro."""
        dispatcher = EventDispatcher()

        with pytest.raises(EventDefinitionError, match="não bate com a tabela"):

            @event("message_update", registry=dispatcher)
            async def errado(old: str, new: Message) -> None: ...

    def test_anotacao_any_passa(self) -> None:
        """A anotação é ganho de editor, não contrato de runtime."""
        dispatcher = EventDispatcher()

        @event("message_update", registry=dispatcher)
        async def generico(old: Any, new: Any) -> None: ...

        assert len(dispatcher.handlers_for("message_update")) == 1

    def test_uniao_compativel_passa(self) -> None:
        dispatcher = EventDispatcher()

        @event("message_update", registry=dispatcher)
        async def certo(old: Message | None, new: Message) -> None: ...

        assert len(dispatcher.handlers_for("message_update")) == 1

    def test_nome_humano_aparece_na_entrada(self) -> None:
        dispatcher = EventDispatcher()

        @event("message_create", name="observador", registry=dispatcher)
        async def generico(msg: Message) -> None: ...

        assert dispatcher._entradas_de("message_create")[0].label == "observador"


# ==========================================================================
# Despacho
# ==========================================================================


class TestDespacho:
    async def test_event_frame_vem_primeiro_na_middleware(self) -> None:
        """O handler recebe o payload só (`0031`) — quem vê o quadro
        primeiro é a middleware, que recebe `(frame, block)`."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        quadros: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        async def observa(frame: Any, _block: Any) -> None:
            quadros.append(frame)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, middleware=[observa])

        assert isinstance(quadros[0], EventFrame)
        assert isinstance(recebido[0][0], Message)

    async def test_sem_contexto_continua_recebendo_só_o_objeto(self) -> None:
        """Um contrato para os dois caminhos (`0031`): `client.on` e
        `@event` recebem o payload só, sem contexto na frente."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert len(recebido[0]) == 1
        assert isinstance(recebido[0][0], Message)

    async def test_snapshot_chega_na_segunda_posicao(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_UPDATE", coletor(recebido))

        antigo = Message.from_payload({**MESSAGE_CREATE, "content": "antes"})
        await dispatcher.dispatch(
            "MESSAGE_UPDATE", {**MESSAGE_CREATE, "content": "depois"}, old=antigo
        )

        assert recebido[0][0] is antigo
        assert recebido[0][1].content == "depois"

    async def test_handler_sincrono_e_erro_no_registro(self) -> None:
        """Sem isso o `await` falharia toda vez, o dispatcher logaria e
        ignoraria — e o sintoma é dos piores de diagnosticar."""
        dispatcher = EventDispatcher()

        with pytest.raises(TypeError, match="async def"):
            dispatcher.add("MESSAGE_CREATE", lambda *_: None)

    async def test_erro_do_handler_vai_para_on_error(self) -> None:
        dispatcher = EventDispatcher()

        async def quebra(msg: Message) -> None:
            raise RuntimeError("boom")

        erros: list[BaseException] = []

        async def captura(frame: Any, exc: BaseException) -> None:
            erros.append(exc)

        dispatcher.add("MESSAGE_CREATE", quebra)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, on_error=captura)

        assert len(erros) == 1
        assert isinstance(erros[0], RuntimeError)

    async def test_middleware_injeta_argumento(self) -> None:
        """O recurso da ideia 10 §8: escrever em `frame.args[0]` muda o
        que os handlers seguintes recebem — e só funciona com lista viva.
        """
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        async def troca(frame: Any, _block: Any) -> None:
            frame.args[0] = "substituido"

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, middleware=[troca])

        assert recebido == [("substituido",)]

    async def test_block_sem_tag_para_tudo(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        async def para(_frame: Any, _block: Any) -> None:
            block()

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, middleware=[para])

        assert recebido == []

    async def test_block_com_tag_somente_os_rotulados(self) -> None:
        """Handlers **sem tag nenhuma** passam sempre — é o que torna
        as tags úteis: quem rotulou é quem aceitou ser filtrado."""
        dispatcher = EventDispatcher()
        passou: list[Any] = []
        filtrado: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(passou))
        dispatcher.add("MESSAGE_CREATE", coletor(filtrado), tags=("manha",))

        async def para_manha(_frame: Any, _block: Any) -> None:
            block("manha")

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, middleware=[para_manha])

        assert len(passou) == 1
        assert filtrado == []

    async def test_block_dentro_de_handler_para_os_que_faltam(self) -> None:
        """Bloquear dentro de handler é tratamento, não falha — o
        `on_error` não roda pela mesma razão do `0017`."""
        dispatcher = EventDispatcher()
        depois: list[Any] = []
        erros: list[Any] = []

        async def para(msg: Message) -> None:
            block()

        async def captura(frame: Any, exc: BaseException) -> None:
            erros.append(exc)

        dispatcher.add("MESSAGE_CREATE", para)
        dispatcher.add("MESSAGE_CREATE", coletor(depois))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, on_error=captura)

        assert depois == []
        assert erros == []

    async def test_once_some_depois_do_primeiro(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido), once=True)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)
        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert len(recebido) == 1

    async def test_once_que_falhou_continua_registrado(self) -> None:
        """`once` é consumido **depois** do `await` bem sucedido: um
        handler que levantou não rodou, ele falhou, e tirá-lo da lista
        transformaria um erro transitório num handler morto para sempre.

        Neste teste o erro é engolido de propósito — a intenção é contar
        tentativas, não testar o `on_error` duas vezes.
        """
        dispatcher = EventDispatcher()
        tentativas: list[int] = []

        async def instavel(msg: Message) -> None:
            tentativas.append(1)
            if len(tentativas) == 1:
                raise RuntimeError("transitório")

        async def ignora(frame: Any, exc: BaseException) -> None:
            return None

        dispatcher.add("MESSAGE_CREATE", instavel, once=True)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, on_error=ignora)
        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE, on_error=ignora)

        assert len(tentativas) == 2

    async def test_state_e_o_mesmo_dict_no_dispatch(self) -> None:
        """O `state` entregue ao dispatch é o mesmo dicionário que o
        quadro carrega — o handler não o vê (`0031`), então quem o vê
        aqui é a middleware."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        quadros: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        async def observa(frame: Any, _block: Any) -> None:
            quadros.append(frame)

        compartilhado: dict[str, Any] = {}
        await dispatcher.dispatch(
            "MESSAGE_CREATE", MESSAGE_CREATE, state=compartilhado, middleware=[observa]
        )

        quadros[0].state["chave"] = 1
        assert compartilhado == {"chave": 1}


# ==========================================================================
# compose
# ==========================================================================


class TestCompose:
    async def test_rodas_em_ordem(self) -> None:
        ordem: list[int] = []

        async def uma(ctx: Any, block: Any) -> None:
            ordem.append(1)

        async def duas(ctx: Any, block: Any) -> None:
            ordem.append(2)

        await compose(uma, duas)(None, block)

        assert ordem == [1, 2]

    async def test_block_no_meio_para_as_que_faltam(self) -> None:
        ordem: list[int] = []

        async def para(ctx: Any, block: Any) -> None:
            ordem.append(1)
            block()

        async def nunca(ctx: Any, block: Any) -> None:
            ordem.append(2)

        with pytest.raises(BlockHandlers):
            await compose(para, nunca)(None, block)

        assert ordem == [1]

    async def test_middleware_sincrona_e_erro_na_chamada(self) -> None:
        """No registro, e não no dispatch: descobrir no clique seria
        descobrir depois do botão publicado."""

        def sincrona(ctx: Any, block: Any) -> None: ...

        with pytest.raises(TypeError, match="assíncrona"):
            compose(sincrona, sincrona)

    async def test_vazia_nao_derruba(self) -> None:
        await compose()(None, block)
