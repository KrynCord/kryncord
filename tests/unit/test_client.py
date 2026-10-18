"""Testes de `kryncord.client` — ciclo de vida do cliente.

O `Client` abre o Gateway de verdade quando chamam `start()`, então os
testes aqui precisam de um `GatewayTransport` simulado — o mesmo que
`tests/conftest.py` usa para o `GatewayClient`. Nenhum teste deste
arquivo abre um socket.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from kryncord import CachePolicy, Client, Config, Intents
from kryncord.api import DiscordAPI
from kryncord.enums import GatewayOpcode
from kryncord.errors import FatalGatewayError, HTTPError, LifecycleError
from kryncord.gateway.payloads import Payload
from kryncord.models import GatewayBotInfo, SessionStartLimit
from kryncord.rest.client import RESTClient
from kryncord.state import ConnectionState
from tests.conftest import FakeGatewayTransport

TOKEN = "token-de-prova"

READY_DATA = {
    "session_id": "sessao-0123456789abcdef",
    "resume_gateway_url": "wss://bogusb.discord.gg",
    "user": {"id": "1", "username": "prova"},
}


def hello() -> Payload:
    return Payload(op=10, data={"heartbeat_interval": 41250})


def ready() -> Payload:
    return Payload(op=0, data=READY_DATA, sequence=1, event_name="READY")


def _transport() -> FakeGatewayTransport:
    """Um socket simulado já com `HELLO` e `READY` enfileirados."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    return transport


def _config(**kwargs: object) -> Config:
    return Config(token=TOKEN, intents=Intents.default(), **kwargs)  # type: ignore[arg-type]


def _client(transport: FakeGatewayTransport | None = None, **kwargs: object) -> Client:
    return Client(
        _config(),
        transport_factory=lambda: transport or _transport(),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_start_then_close() -> None:
    transport = _transport()
    async with _client(transport) as client:
        await client.start()
        assert client.is_started
        assert not client.is_closed
        # `start()` devolve só depois do READY — é a diferença entre
        # "socket aberto" e "bot recebendo eventos".
        assert client.is_ready

    assert client.is_closed
    assert not client.is_started


async def test_start_identifies() -> None:
    transport = _transport()
    async with _client(transport) as client:
        await client.start()
        assert transport.identify["token"] == TOKEN
        assert transport.identify["intents"] == Intents.default().to_payload()


async def test_cannot_start_twice() -> None:
    async with _client() as client:
        await client.start()
        with pytest.raises(LifecycleError, match="já foi iniciado"):
            await client.start()


async def test_cannot_start_after_close() -> None:
    client = _client()
    await client.close()
    with pytest.raises(LifecycleError, match="já foi fechado"):
        await client.start()


async def test_close_is_idempotent() -> None:
    """Fechar duas vezes não é erro — é o comportamento esperado em shutdown."""
    client = _client()
    await client.close()
    await client.close()
    assert client.is_closed


async def test_close_without_start_is_allowed() -> None:
    """`async with` que nunca chamou start ainda tem que fechar limpo."""
    client = _client()
    async with client:
        pass
    assert client.is_closed


async def test_spawn_creates_supervised_task() -> None:
    ran = asyncio.Event()

    async def work() -> None:
        ran.set()

    async with _client() as client:
        client.spawn(work())
        await asyncio.wait_for(ran.wait(), timeout=1)


async def test_spawned_tasks_are_cancelled_on_close() -> None:
    cancelled = asyncio.Event()

    async def forever() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    client = _client()
    async with client:
        client.spawn(forever())
        await asyncio.sleep(0)

    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_context_exit_propagates_exception() -> None:
    """Erro dentro do bloco não é engolido pelo __aexit__."""
    with pytest.raises(ValueError, match="boom"):
        async with _client() as client:
            await client.start()
            raise ValueError("boom")


async def test_exposes_config_and_intents() -> None:
    config = _config()
    async with Client(config, transport_factory=_transport) as client:
        assert client.config is config
        assert client.intents is Intents.default()


async def test_privileged_intent_fails_at_start() -> None:
    """O erro aparece no start, não depois de um Identify rejeitado."""
    config = Config(token=TOKEN, intents=Intents.GUILD_MEMBERS)
    async with Client(config, transport_factory=_transport) as client:
        with pytest.raises(ValueError, match="GUILD_MEMBERS"):
            await client.start()


async def test_empty_token_fails_at_start_with_a_useful_message() -> None:
    """O token é o erro mais comum de um bot que não liga, e a mensagem
    tem que dizer onde pegar o valor — não só "inválido"."""
    for token in ("", "   "):
        config = Config(token=token, intents=Intents.default())
        async with Client(config, transport_factory=_transport) as client:
            with pytest.raises(ValueError, match="token"):
                await client.start()
            assert not client.is_started


async def test_fatal_gateway_error_surfaces_out_of_start() -> None:
    """4014 (intents não permitidos) não é erro de config do Client — é
    o Discord recusando. Subir a exceção real é mais útil que um
    genérico "não conectou"."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.drop(code=4014, reason="intents não permitidos")

    async with _client(transport) as client:
        with pytest.raises(FatalGatewayError) as excinfo:
            await client.start()
        assert excinfo.value.code == 4014


async def test_handlers_receive_dispatches() -> None:
    transport = _transport()
    seen: list[str] = []

    async with _client(transport) as client:

        @client.on("READY")
        async def pronto(data: object) -> None:
            seen.append("READY")

        await client.start()
        await asyncio.sleep(0)

    assert seen == ["READY"]


async def test_handler_names_are_case_insensitive() -> None:
    transport = _transport()
    seen: list[str] = []

    async with _client(transport) as client:

        @client.on("ready")
        async def pronto(data: object) -> None:
            seen.append("ok")

        await client.start()
        await asyncio.sleep(0)

    assert seen == ["ok"]


async def test_a_broken_handler_does_not_kill_the_connection() -> None:
    """Um handler que estoura não pode derrubar a conexão que está
    mantendo o bot no ar."""
    transport = _transport()
    seen: list[str] = []

    async with _client(transport) as client:

        @client.on("READY")
        async def quebrado(data: object) -> None:
            raise RuntimeError("handler ruim")

        @client.on("READY")
        async def bom(data: object) -> None:
            seen.append("ok")

        await client.start()
        await asyncio.sleep(0)

    # O segundo handler ainda rodou, e a conexão seguia viva até o close.
    assert seen == ["ok"]


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


async def test_cache_existe_desde_a_construcao() -> None:
    """Mesmo caminho do `api`: um handler registrado fora do `async
    with` captura `client.cache` no closure, e para isso ele tem que
    existir antes de qualquer conexão.

    Nascer aqui e não no `start()` não é preguiça — é o que faz a
    referência ser estável durante toda a vida do objeto.
    """
    client = _client()

    assert isinstance(client.cache, ConnectionState)
    assert client.cache.enabled is True
    assert client.cache.me is None  # nada chegou ainda
    assert client.cache.guilds == ()


async def test_config_cache_flui_para_o_estado() -> None:
    """A política vem do `Config` e o estado nasce com ela. Trocar
    depois de ligar não desfaz o que já entrou — por isso é config,
    e não setter: uma configuração sem efeito seria o pior dos dois."""
    config = Config(token=TOKEN, intents=Intents.default(), cache=CachePolicy.disabled())
    client = Client(config, transport_factory=_transport)

    assert client.cache.policy is config.cache
    assert client.cache.enabled is False
    assert client.cache.as_dict()["enabled"] is False


async def test_cache_e_alimentado_antes_do_handler() -> None:
    """É a ordem inteira que importa. Se o handler rodasse antes, todo
    `cache.get_member()` dentro dele veria o estado do evento anterior —
    e o bug não apareceria em teste unitário nem em conversa: só sob
    carga, e sumiria quando alguém parasse o bot para olhar."""
    GUILD_CREATE = {
        "id": "10",
        "name": "Servidor",
        "roles": [{"id": "30", "name": "Mod"}],
        "channels": [{"id": "20", "name": "geral", "type": 0}],
    }
    transport = _transport()
    transport.feed_payload(Payload(op=0, data=GUILD_CREATE, sequence=2, event_name="GUILD_CREATE"))
    dentro_do_handler: list[object] = []
    chegou = asyncio.Event()

    async with _client(transport) as client:

        @client.on("guild_create")
        async def chegando(dados: object) -> None:
            # O evento ainda está sendo entregue, e o cache já foi.
            dentro_do_handler.append(client.cache.get_guild(10))
            dentro_do_handler.append(client.cache.get_role(10, 30))
            chegou.set()

        await client.start()
        await asyncio.wait_for(chegou.wait(), timeout=2)

    guild = dentro_do_handler[0]
    assert guild is not None
    assert guild.name == "Servidor"
    assert dentro_do_handler[1] is not None


async def test_falha_no_cache_nao_derruba_a_entrega() -> None:
    """Contrato dos handlers, aplicado ao cache: exceção aqui é logada e
    o resto do dispatch segue. Um payload que não deu para interpretar
    não pode derrubar a conexão que está mantendo o bot no ar.

    O `EventUpdater` é trocado à mão porque o erro tem que vir de
    dentro dele — é o caminho que existe, e é o que um payload bizarro
    do Discord viraria.
    """
    transport = _transport()
    chamados: list[str] = []

    class CacheQuebrado:
        def apply(self, name: str, payload: object) -> None:
            raise RuntimeError("cache ruim")

    async with _client(transport) as client:
        # Troca direta, sem rodeio: é o caminho de falha que existe, e
        # o que um payload bizarro do Discord viraria.
        client._updater = CacheQuebrado()

        @client.on("READY")
        async def pronto(dados: object) -> None:
            chamados.append("READY")

        @client.on("ready")
        async def pronto_normalizado(dados: object) -> None:
            chamados.append("ready")

        await client.start()
        await asyncio.sleep(0)

    # O `READY` seguiu: pronto, handler, e a conexão viva até o close.
    assert chamados == ["READY", "ready"]
    assert client.is_ready


async def test_spawn_outside_context_raises() -> None:
    client = _client()

    async def work() -> None:
        return None

    with pytest.raises(Exception, match="fora do bloco"):
        client.spawn(work())


# --------------------------------------------------------------------------
# Ligação com o REST
# --------------------------------------------------------------------------


async def test_api_existe_desde_a_construcao() -> None:
    """REST e Gateway são independentes (ver `docs/decisions/0004`). Um
    bot que só quer consultar a API não precisa de WebSocket, e um
    handler registrado fora do `async with` ainda captura `client.api`
    no closure — por isso não é preguiça construir antes do `start()`."""
    client = _client()
    assert isinstance(client.api, DiscordAPI)
    assert client.gateway is None  # Gateway só nasce no `start()`
    assert client.latency is None  # e sem ACK não há latência a mostrar
    assert client.is_started is False


async def test_api_funciona_sem_gateway() -> None:
    """Sem `start()`, sem Gateway — e o REST segue respondendo."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "1", "username": "prova", "bot": True})

    client = _client(http_transport=httpx.MockTransport(handler))

    user = await client.api.users.me()

    assert user.bot is True
    assert captured[0].url.path == "/api/v10/users/@me"


async def test_close_fecha_o_pool_http() -> None:
    """Um pool aberto segura socket. `close()` devia liberar tudo —
    Gateway e HTTP — e não só metade."""
    fechado = False
    original = RESTClient.aclose

    async def espiar(self: RESTClient) -> None:
        nonlocal fechado
        fechado = True
        await original(self)

    RESTClient.aclose = espiar  # type: ignore[method-assign]
    try:
        async with _client(_transport()) as client:
            await client.start()
        assert fechado
    finally:
        RESTClient.aclose = original  # type: ignore[method-assign]


async def test_close_direto_tambem_fecha_o_rest() -> None:
    """O caminho de `close()` explícito, sem depender do `__aexit__`.

    `start()` exige o bloco `async with` — sem ele não há TaskGroup para
    supervisionar a task do Gateway, e o `Lifecycle` recusa. Aqui entra
    no contexto e chama `close()` à mão, que é o caso que importa.
    """
    async with _client(_transport()) as client:
        await client.start()
        await client.close()

        # Depois de fechado, uma requisição reclama em vez de segurar
        # socket — e nada mais é mandado para a rede.
        with pytest.raises(HTTPError, match="fechado"):
            await client.api.users.me()


async def test_update_presence_delega_ao_gateway() -> None:
    """`Client.update_presence` chega no gateway e vira op 3 no socket."""
    transport = _transport()
    async with _client(transport) as client:
        await client.start()

        await client.update_presence(status="idle", activities=[{"name": "prova"}])

        enviado = next(f for f in transport.sent if f["op"] == GatewayOpcode.PRESENCE_UPDATE)
        assert enviado["d"]["status"] == "idle"
        assert enviado["d"]["activities"] == [{"name": "prova"}]


async def test_update_presence_sem_gateway_erro() -> None:
    """Antes do `start()` a recusa é na cara — o gateway ainda não existe."""
    client = _client()

    with pytest.raises(LifecycleError, match="start"):
        await client.update_presence()


def _gateway_info(shards: int) -> GatewayBotInfo:
    """`/gateway/bot` de mentira para os testes de sharding."""
    return GatewayBotInfo(
        url="wss://gateway.discord.gg",
        shards=shards,
        session_start_limit=SessionStartLimit(
            total=1000, remaining=1000, reset_after=0.0, max_concurrency=1
        ),
    )


def _http_que_reclama() -> httpx.MockTransport:
    """Transporte HTTP que falha o teste se for chamado.

    A regressão que este espinho protege: um `start()` que passasse a
    buscar `/gateway/bot` sem ninguém pedir sharding quebraria o bot
    single-shard com um REST que ninguém mockou — e o teste que só
    checava `is_ready` continuaria verde até o usuário reclamar.
    """

    def estoura(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"start() não devia chamar REST; chamou {request.url.path}")

    return httpx.MockTransport(estoura)


async def test_single_shard_sem_rest_continua_igual() -> None:
    """Zero sharding = uma shard, e nenhum REST novo — o comportamento
    de sempre, provado com um HTTP que reclama."""
    async with _client(_transport(), http_transport=_http_que_reclama()) as client:
        await client.start()

        assert client.is_ready
        gerenciador = client.gateway
        assert gerenciador is not None
        assert gerenciador.shard_count == 1
        assert gerenciador.assignment.shard_ids == (0,)


async def test_shard_ids_explicitos_pulam_rest() -> None:
    """Com `gateway_information` na mão, `shard_ids` não busca nada —
    os dois vêm do chamador, e o REST fica quieto."""
    transports = [_transport(), _transport()]
    fila = list(transports)
    client = Client(
        _config(),
        transport_factory=lambda: fila.pop(0),  # type: ignore[misc]
        http_transport=_http_que_reclama(),
        shard_ids=(0, 1),
        gateway_information=_gateway_info(2),
    )
    async with client:
        await client.start()

        gerenciador = client.gateway
        assert gerenciador is not None
        assert gerenciador.shard_count == 2
        for shard_id, transport in enumerate(transports):
            identify = next(f for f in transport.sent if f["op"] == GatewayOpcode.IDENTIFY)
            assert identify["d"]["shard"] == [shard_id, 2]
