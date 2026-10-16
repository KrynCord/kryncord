"""Testes do dispatcher — o ponto onde payload vira objeto.

O dispatcher é a camada que decide o que o handler recebe. Os testes
que importam aqui são os de **política**, e não os de parsing: o parsing
já está coberto em `test_models.py`. O que se decide aqui é quem roda,
em que ordem, o que acontece quando alguém erra, e o que fazer quando o
evento ainda não tem parser.

Handlers são `async` por contrato — ver `EventHandler` em
`events/dispatcher.py`. Os helpers abaixo evitam repetir `async def` em
cada teste, que é o tipo de ruído que faz gente escrever `lambda`.
"""

import asyncio
from typing import Any

import pytest

from kryncord.events import EventDispatcher, EventHandler, EventName, normalize_event_name
from kryncord.models import Message, PartialMessage, Ready, TypingStart

MESSAGE_CREATE = {
    "id": "100",
    "channel_id": "200",
    "author": {"id": "1", "username": "x"},
    "content": "oi",
}


def coletor(lista: list[Any]) -> EventHandler:
    """Handler que guarda o payload recebido."""

    async def _handler(payload: Any) -> None:
        lista.append(payload)

    return _handler


def coletor_dois(lista: list[tuple[Any, Any]]) -> EventHandler:
    """Handler de evento que paga snapshot (`0025` §5).

    São sete eventos que mudaram de um argumento para dois — este helper
    existe para cobrir essa tabela sem virar `*args` em cada teste, que
    esconderia justamente o que está sendo conferido.
    """

    async def _handler(payload: Any, old: Any) -> None:
        lista.append((payload, old))

    return _handler


def marcador(lista: list[str], nome: str) -> EventHandler:
    """Handler que só anota que rodou, e em que ordem."""

    async def _handler(payload: Any) -> None:
        lista.append(nome)

    return _handler


# ==========================================================================
# Nomes
# ==========================================================================


class TestNormalizeEventName:
    def test_maiusculas_viram_snake_case(self) -> None:
        assert normalize_event_name("MESSAGE_CREATE") == "message_create"

    def test_snake_case_passa_direto(self) -> None:
        assert normalize_event_name("message_create") == "message_create"

    def test_o_enum_tambem_funciona(self) -> None:
        assert normalize_event_name(EventName.MESSAGE_CREATE) == "message_create"

    def test_evento_desconhecido_volta_maiusculo(self) -> None:
        """Um evento que nem está em `events/names.py` continua
        funcionando — a biblioteca não finge que entende o que ainda não
        catalogou (`0025` §2)."""
        assert (
            normalize_event_name("GUILD_AUDIT_LOG_ENTRY_CREATE") == "GUILD_AUDIT_LOG_ENTRY_CREATE"
        )


# ==========================================================================
# Interpretação
# ==========================================================================


class TestInterpretacao:
    async def test_message_create_vira_modelo(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert len(recebido) == 1
        assert isinstance(recebido[0], Message)
        assert recebido[0].content == "oi"

    async def test_message_delete_entrega_id_e_old(self) -> None:
        """`MESSAGE_DELETE` mudou de um argumento para dois (`0025`
        §Quebras).

        O primeiro é o **id** vindo direto do payload — não o objeto.
        O parser não entra: `monta_args` monta `(id, old)` sem chamar
        `REGISTRY`, porque `Message` nenhum se materializa de dois
        campos. O segundo é o snapshot lido antes do updater, e aqui o
        chamador não passou nenhum, então é `None`.
        """
        dispatcher = EventDispatcher()
        recebido: list[tuple[Any, Any]] = []
        dispatcher.add("MESSAGE_DELETE", coletor_dois(recebido))

        await dispatcher.dispatch("MESSAGE_DELETE", {"id": "1", "channel_id": "2"})

        assert recebido[0][0] == 1
        assert recebido[0][1] is None

    async def test_message_delete_com_snapshot_vem_no_segundo(self) -> None:
        """O snapshot entregue pelo chamador chega na segunda posição."""
        dispatcher = EventDispatcher()
        recebido: list[tuple[Any, Any]] = []
        dispatcher.add("MESSAGE_DELETE", coletor_dois(recebido))
        antes = PartialMessage.from_payload({"id": "1", "channel_id": "2"})

        await dispatcher.dispatch("MESSAGE_DELETE", {"id": "1", "channel_id": "2"}, old=antes)

        assert recebido[0][1] is antes

    async def test_message_delete_deixa_essa_chegar_cru(self) -> None:
        """Sem `id` nenhum, o primeiro argumento é `None` — a aridade
        fica a mesma, porque `TypeError` de argumento faltando
        mascararia o erro verdadeiro (`0025` §4)."""
        dispatcher = EventDispatcher()
        recebido: list[tuple[Any, Any]] = []
        dispatcher.add("MESSAGE_DELETE", coletor_dois(recebido))

        await dispatcher.dispatch("MESSAGE_DELETE", {"channel_id": "2"})

        assert recebido == [(None, None)]

    async def test_ready_vira_modelo(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("READY", coletor(recebido))

        await dispatcher.dispatch("READY", {"user": {"id": "1", "username": "b"}})

        assert isinstance(recebido[0], Ready)

    async def test_evento_sem_parser_chega_cru(self) -> None:
        """A biblioteca não finge que entende o que ainda não
        catalogou. O dict chega inteiro — e num argumento só, que é o
        formato do `0006` para o que está fora da tabela (`0025` §2)."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("PRESENCE_UPDATE", coletor(recebido))
        bruto = {"user": {"id": "7"}, "status": "online"}

        await dispatcher.dispatch("PRESENCE_UPDATE", bruto)

        assert recebido == [bruto]

    async def test_typing_start_vira_modelo(self) -> None:
        """`TYPING_START` ganhou parser no `0025` — era o caso cru, e
        deixou de ser."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("TYPING_START", coletor(recebido))

        await dispatcher.dispatch("TYPING_START", {"channel_id": "5", "user_id": "9"})

        assert isinstance(recebido[0], TypingStart)
        assert recebido[0].channel_id == 5

    async def test_payload_ja_modelo_passa_direto(self) -> None:
        """Evita que o parser rode duas vezes sobre o mesmo objeto — e
        permite que o teste entregue interpretado."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))
        pronto = Message.from_payload(MESSAGE_CREATE)

        await dispatcher.dispatch("MESSAGE_CREATE", pronto)

        assert recebido[0] is pronto

    async def test_payload_malformado_chega_cru_sem_levantar(self) -> None:
        """Um `MESSAGE_CREATE` sem `id` não vira `Message`. Entregar
        cru é melhor que derrubar o dispatch — o handler que só quer o
        dict ainda funciona."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        await dispatcher.dispatch("MESSAGE_CREATE", {"sem": "id"})

        assert recebido == [{"sem": "id"}]

    async def test_payload_nulo_nao_levanta(self) -> None:
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        await dispatcher.dispatch("MESSAGE_CREATE", None)

        assert recebido == [None]

    def test_known_events_lista_so_os_interpretados(self) -> None:
        """Só entra o que tem parser — quem está aqui é o que o
        dispatcher sabe interpretar, e não o que o Discord tem."""
        dispatcher = EventDispatcher()
        assert "MESSAGE_CREATE" in dispatcher.known_events
        assert "MESSAGE_DELETE_BULK" not in dispatcher.known_events


# ==========================================================================
# Nomes de registro
# ==========================================================================


class TestRegistro:
    async def test_maiusculo_e_snake_case_mesmo_handler(self) -> None:
        """`on("MESSAGE_CREATE")` e `on("message_create")` chegam ao
        mesmo lugar — trocar o nome de uma hora para outra é como se
        quebra compatibilidade sem ganhar nada."""
        dispatcher = EventDispatcher()
        recebido: list[Any] = []
        dispatcher.add("MESSAGE_CREATE", coletor(recebido))

        await dispatcher.dispatch("message_create", MESSAGE_CREATE)

        assert len(recebido) == 1

    async def test_registros_duplicados_ambos_rodando(self) -> None:
        """Registrar o mesmo handler duas vezes com formas diferentes
        não descarta nenhum — são duas entradas, não uma."""
        dispatcher = EventDispatcher()
        chamadas: list[str] = []
        dispatcher.add("MESSAGE_CREATE", marcador(chamadas, "A"))
        dispatcher.add("message_create", marcador(chamadas, "B"))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert chamadas == ["A", "B"]

    def test_handlers_for_devolve_em_ordem(self) -> None:
        dispatcher = EventDispatcher()
        lista: list[str] = []
        dispatcher.add("READY", marcador(lista, "a"))
        dispatcher.add("READY", marcador(lista, "b"))

        assert len(dispatcher.handlers_for("ready")) == 2

    def test_handlers_for_desconhecido_devolve_vazio(self) -> None:
        assert EventDispatcher().handlers_for("qualquer") == ()


# ==========================================================================
# Política de execução — a decisão documentada em dispatcher.py
# ==========================================================================


class TestPolitica:
    async def test_handlers_rodam_em_ordem_de_registro(self) -> None:
        """Sequencial e na ordem. Task por handler daria ordem
        imprevisível, e imprevisibilidade num dispatch de mensagem é
        como se fabrica bug de corrida."""
        dispatcher = EventDispatcher()
        ordem: list[str] = []
        dispatcher.add("MESSAGE_CREATE", marcador(ordem, "primeiro"))
        dispatcher.add("MESSAGE_CREATE", marcador(ordem, "segundo"))
        dispatcher.add("MESSAGE_CREATE", marcador(ordem, "terceiro"))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert ordem == ["primeiro", "segundo", "terceiro"]

    async def test_excecao_em_um_handler_nao_para_os_outros(self) -> None:
        """Derrubar a conexão por um `KeyError` num log seria trocar um
        evento perdido por um bot fora do ar — e o bot fora do ar
        perde *todos* os eventos."""
        dispatcher = EventDispatcher()
        rodou: list[str] = []

        async def quebra(payload: Any) -> None:
            raise RuntimeError("handler ruim")

        dispatcher.add("MESSAGE_CREATE", quebra)
        dispatcher.add("MESSAGE_CREATE", marcador(rodou, "depois"))

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert rodou == ["depois"]

    async def test_cancelamento_propaga(self) -> None:
        """Diferente de exceção, cancelamento não é erro: é o `close()`
        mandando o bot desligar. Engolir isso deixaria tarefa pendurada.

        Aqui o cancelamento vem de fora — é o caso que importa.
        """
        dispatcher = EventDispatcher()
        dispatcher.add("MESSAGE_CREATE", coletor([]))

        task = asyncio.create_task(dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE))
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_cancelamento_dentro_do_handler_propaga(self) -> None:
        """Um handler que cancela a própria task — raro, mas tem que
        subir, não virar log enganoso."""
        dispatcher = EventDispatcher()

        async def que_cancela(payload: Any) -> None:
            raise asyncio.CancelledError

        dispatcher.add("MESSAGE_CREATE", que_cancela)

        with pytest.raises(asyncio.CancelledError):
            await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

    async def test_handler_assincrono_e_aguardado(self) -> None:
        """Se o handler faz `await`, o dispatch espera — senão o
        cancelamento no `close()` não o pegaria."""
        dispatcher = EventDispatcher()
        terminou = asyncio.Event()

        async def lento(payload: Any) -> None:
            await asyncio.sleep(0)
            terminou.set()

        dispatcher.add("MESSAGE_CREATE", lento)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert terminou.is_set()

    def test_handler_sincrono_e_rejeitado_no_registro(self) -> None:
        """Prova o contrato: função síncrona não é handler válido.

        Validar no registro, uma vez, é melhor que descobrir no
        primeiro evento. Sem isso o `await` falharia toda vez, o
        dispatcher logaria e ignoraria, e o sintoma — handler que nunca
        roda, sem erro visível — é dos piores de diagnosticar.
        """
        dispatcher = EventDispatcher()

        with pytest.raises(TypeError, match="async def"):
            dispatcher.add("MESSAGE_CREATE", lambda payload: None)  # type: ignore[arg-type]

    def test_objeto_com_call_assincrono_e_aceito(self) -> None:
        """`inspect.iscoroutinefunction` sozinho rejeitaria isto: a
        assinatura está no `__call__`, e não no objeto."""

        class Handler:
            async def __call__(self, payload: Any) -> None:
                return None

        dispatcher = EventDispatcher()
        dispatcher.add("MESSAGE_CREATE", Handler())

        assert len(dispatcher.handlers_for("MESSAGE_CREATE")) == 1

    def test_partial_de_funcao_assincrona_e_aceito(self) -> None:
        """`functools.partial` de `async def` é handler legítimo — o
        `inspect` faz o unwrap."""
        from functools import partial

        async def base(payload: Any, rotulo: str) -> None:
            return None

        dispatcher = EventDispatcher()
        dispatcher.add("MESSAGE_CREATE", partial(base, rotulo="x"))

        assert len(dispatcher.handlers_for("MESSAGE_CREATE")) == 1


# ==========================================================================
# Caso real: o bot inteiro, do payload ao handler
# ==========================================================================


class TestCasoReal:
    async def test_handler_ve_o_que_precisa(self) -> None:
        """O teste que prova o propósito da Fase 3: `message.content`,
        não `data["content"]`."""
        dispatcher = EventDispatcher()
        anotado: list[str] = []

        async def registra(message: Any) -> None:
            anotado.append(f"{message.author_name}: {message.content}")

        dispatcher.add("message_create", registra)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert anotado == ["x: oi"]

    async def test_mesmo_payload_para_dois_handlers(self) -> None:
        """Os dois handlers recebem o mesmo objeto — não duas cópias.
        `frozen` garante que um não altera o que o outro vê."""
        dispatcher = EventDispatcher()
        vistos: list[int] = []

        async def anota_id(payload: Any) -> None:
            vistos.append(id(payload))

        dispatcher.add("MESSAGE_CREATE", anota_id)
        dispatcher.add("MESSAGE_CREATE", anota_id)

        await dispatcher.dispatch("MESSAGE_CREATE", MESSAGE_CREATE)

        assert vistos[0] == vistos[1]
