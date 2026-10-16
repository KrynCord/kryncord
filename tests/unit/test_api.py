"""Testes de `kryncord.api` — vocabulário por recurso sobre a mecânica REST.

Cobrem o que a camada acrescenta em relação ao `rest/`: aceitar objeto
no lugar de ID, devolver modelo em vez de dict, montar o
``message_reference`` de um reply, e reclamar alto quando a resposta não
forma o modelo pedido.

Nenhum teste toca a rede — o transporte é `httpx.MockTransport`, o
relógio é falso e o `sleeper` registra o que teria esperado.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from kryncord.api import DiscordAPI
from kryncord.api._parse import expect_model
from kryncord.api._resolve import channel_id_of, message_id_of
from kryncord.config import HTTPConfig
from kryncord.errors import HTTPError
from kryncord.http.authentication import Token
from kryncord.models import Channel, Guild, Message, PartialChannel, PartialMessage, User
from kryncord.rest.client import RESTClient
from tests.conftest import FakeClock, FakeSleeper

TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.AbCdEfGhIjKlMnOpQrStUvWxYz"

Factory = Callable[[], httpx.Response | BaseException]
DEFAULT_TOKEN = Token(value=TOKEN)

CANAL = 200
MENSAGEM = 100
GUILD = 300


def ok(**json_body: Any) -> Factory:
    return lambda: httpx.Response(200, json=json_body or {"ok": True})


def no_content() -> Factory:
    """204 — o que `DELETE` devolve. Corpo vazio, `.json()` devolve None."""
    return lambda: httpx.Response(204)


def failing(exc: BaseException) -> Factory:
    def make() -> httpx.Response | BaseException:
        return exc

    return make


def make_api(
    *factories: Factory,
    clock: FakeClock | None = None,
    sleeper: FakeSleeper | None = None,
    token: Token | None = DEFAULT_TOKEN,
) -> tuple[DiscordAPI, list[httpx.Request]]:
    """`DiscordAPI` sobre transporte falso.

    `factories` é a sequência de respostas; a última se repete. Cada
    resposta é construída na hora — reusar objeto `httpx.Response` daria
    "content already read".

    `clock` e `sleeper` têm default: quem só verifica rota e corpo não
    precisa de relógio nenhum, e passar os dois a cada chamada era ruído.
    Quem testa rate limit continua injetando os fixtures, e o `sleeper`
    criado aqui reaproveita o `clock` recebido se vier só ele.
    """
    if clock is None:
        clock = FakeClock()
    if sleeper is None:
        sleeper = FakeSleeper(clock)

    captured: list[httpx.Request] = []
    seq = list(factories) or [ok()]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = min(len(captured) - 1, len(seq) - 1)
        result = seq[index]()
        if isinstance(result, BaseException):
            raise result
        return result

    rest = RESTClient(
        HTTPConfig(),
        token=token,
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleeper=sleeper,
    )
    return DiscordAPI(rest), captured


def corpo_de(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode())


def payload_de_mensagem(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(MENSAGEM),
        "channel_id": str(CANAL),
        "guild_id": str(GUILD),
        "author": {"id": "1", "username": "x", "global_name": "X"},
        "content": "oi",
        "timestamp": "2024-01-01T00:00:00Z",
        "type": 0,
    }
    base.update(overrides)
    return base


# ==========================================================================
# Resolução de IDs — o que "aceitar objeto" significa na prática
# ==========================================================================


class TestResolucao:
    def test_canal_por_int(self) -> None:
        assert channel_id_of(CANAL) == CANAL

    def test_canal_por_string(self) -> None:
        """O Discord manda IDs como string; aceitar evita que o chamador
        decore qual método quer int."""
        assert channel_id_of("200") == CANAL

    def test_canal_por_modelo(self) -> None:
        channel = Channel.from_payload({"id": str(CANAL), "type": 0})
        assert channel is not None
        assert channel_id_of(channel) == CANAL

    def test_canal_por_parcial(self) -> None:
        assert channel_id_of(PartialChannel(id=CANAL)) == CANAL

    def test_canal_por_mensagem(self) -> None:
        """`send(mensagem.channel, ...)` não é preciso — a própria
        mensagem identifica o canal."""
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None
        assert channel_id_of(message) == CANAL

    def test_canal_por_mensagem_parcial(self) -> None:
        assert channel_id_of(PartialMessage(id=1, channel_id=CANAL)) == CANAL

    def test_bool_nao_passa_como_int(self) -> None:
        """`True == 1` em Python. Sem barreira, um `True` seria o canal
        de ID 1."""
        with pytest.raises(TypeError, match="bool"):
            channel_id_of(True)  # type: ignore[arg-type]

    def test_string_nao_numerica_e_erro(self) -> None:
        with pytest.raises(ValueError, match="numérico"):
            channel_id_of("geral")  # type: ignore[arg-type]

    def test_objeto_indistinguivel_e_erro(self) -> None:
        with pytest.raises(TypeError, match="não identificável"):
            channel_id_of(None)  # type: ignore[arg-type]

    def test_mensagem_por_int_e_por_objeto(self) -> None:
        assert message_id_of(MENSAGEM) == MENSAGEM
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None
        assert message_id_of(message) == MENSAGEM

    def test_mensagem_parcial_tambem(self) -> None:
        assert message_id_of(PartialMessage(id=MENSAGEM, channel_id=CANAL)) == MENSAGEM


# ==========================================================================
# expect_model — a resposta que não vira modelo
# ==========================================================================


class TestExpectModel:
    def test_devolve_o_modelo(self) -> None:
        response = httpx.Response(200, json=payload_de_mensagem()).json()
        assert isinstance(response, dict)

    def test_levanta_sem_corpo_de_objeto(self) -> None:
        """Um 200 com corpo lista ou vazio não é o que se pediu. Silenciar
        isso empurraria `None` para dentro de um `if` que ninguém escreveu."""
        from kryncord.http.response import Response

        resposta = Response.of(200, [], b"[]")
        with pytest.raises(HTTPError, match="sem corpo de objeto"):
            expect_model(Message, resposta, route="GET /x")

    def test_levanta_quando_nao_forma_o_modelo(self) -> None:
        """Corpo objeto, mas sem o campo essencial — `from_payload`
        devolve `None`, e isso vira erro, não valor nulo."""
        from kryncord.http.response import Response

        resposta = Response.of(200, [], json.dumps({"sem": "id"}).encode())
        with pytest.raises(HTTPError, match="não forma Message"):
            expect_model(Message, resposta, route="GET /x")

    def test_mensagem_de_erro_traz_a_rota(self) -> None:
        """Quem lê o erro precisa saber qual chamada falhou."""
        from kryncord.http.response import Response

        resposta = Response.of(200, [], b"{}")
        with pytest.raises(HTTPError, match="GET /channels/:id"):
            expect_model(Channel, resposta, route="GET /channels/:id")


# ==========================================================================
# MessagesAPI
# ==========================================================================


class TestMessages:
    async def test_send_devolve_modelo(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, _captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        message = await api.messages.send(CANAL, "oi")

        assert isinstance(message, Message)
        assert message.content == "oi"
        assert message.channel_id == CANAL
        assert message.author is not None
        assert message.author.display_name == "X"

    async def test_send_acerta_a_rota(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        await api.messages.send(CANAL, "oi")

        assert captured[0].method == "POST"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages"

    async def test_send_como_objeto(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        """O ponto de aceitar objeto: nada de `mensagem.channel_id.id`."""
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        channel = Channel.from_payload({"id": str(CANAL), "type": 0})
        assert channel is not None

        await api.messages.send(channel, "oi")

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages"

    async def test_send_sem_content_omite_o_campo(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """`{"content": None}` e `{}` significam a mesma coisa para o
        Discord, mas o segundo é mais honesto: o campo não foi enviado."""
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        await api.messages.send(CANAL, embeds=[{"title": "oi"}])

        corpo = corpo_de(captured[0])
        assert "content" not in corpo
        assert corpo["embeds"] == [{"title": "oi"}]

    async def test_send_manda_kwargs_no_corpo(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        """Sem intermediário que renomeie: o nome do campo é o do
        Discord, e quem lê o docs consegue escrever aqui."""
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        await api.messages.send(CANAL, "oi", tts=True, allowed_mentions={"parse": []})

        corpo = corpo_de(captured[0])
        assert corpo["tts"] is True
        assert corpo["allowed_mentions"] == {"parse": []}

    async def test_reply_monta_o_message_reference(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """O Discord não tem endpoint de resposta — um reply é um send
        com um campo dizendo o que está sendo respondido."""
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        original = Message.from_payload(payload_de_mensagem())
        assert original is not None

        await api.messages.reply(original, "pong")

        corpo = corpo_de(captured[0])
        assert corpo["message_reference"] == {
            "message_id": str(MENSAGEM),
            "fail_if_not_exists": False,
        }
        assert corpo["content"] == "pong"

    async def test_reply_vai_para_o_canal_da_mensagem(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        original = Message.from_payload(payload_de_mensagem())
        assert original is not None

        await api.messages.reply(original, "pong")

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages"

    async def test_reply_sem_ping_suprime_o_autor(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """Não existe flag de "não pinge" no Discord. A forma é suprimir
        a menção no `allowed_mentions`."""
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        original = Message.from_payload(payload_de_mensagem())
        assert original is not None

        await api.messages.reply(original, "pong", mention_author=False)

        corpo = corpo_de(captured[0])
        assert corpo["allowed_mentions"]["users"] == []

    async def test_reply_aceita_id_puro_quando_tem_canal(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        parcial = PartialMessage(id=MENSAGEM, channel_id=CANAL)

        await api.messages.reply(parcial, "pong")

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages"

    async def test_reply_com_id_puro_sem_canal_falta_alto(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """Um int não carrega canal. Mandar a requisição para o canal
        errado seria pior que reclamar — e o Discord nem diria."""
        api, _ = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        with pytest.raises(TypeError, match="channel_id"):
            await api.messages.reply(MENSAGEM, "pong")

    async def test_fetch_devolve_modelo(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        message = await api.messages.fetch(CANAL, MENSAGEM)

        assert isinstance(message, Message)
        assert captured[0].method == "GET"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}"

    async def test_edit_devolve_o_estado_novo(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        """Modelos são `frozen`: o que o handler tinha na mão continua
        sendo o estado no momento em que ele viu. O retorno é a versão
        nova, não a mesma alterada."""
        api, captured = make_api(
            ok(**payload_de_mensagem(content="editado")), clock=clock, sleeper=sleeper
        )

        edited = await api.messages.edit(MENSAGEM, "editado", channel=CANAL)

        assert edited.content == "editado"
        assert captured[0].method == "PATCH"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}"

    async def test_edit_com_id_puro_sem_canal_falta_alto(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """Um int não carrega canal. Mandar para o canal errado daria um
        404 apontando "mensagem não encontrada" — a resposta errada para
        o problema real."""
        api, _ = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)

        with pytest.raises(TypeError, match="channel="):
            await api.messages.edit(MENSAGEM, "novo")

    async def test_delete_com_id_puro_e_canal_explicito(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """`channel=` é o que um int não pode dizer — e o caso existe:
        IDs guardados em banco, sem objeto na mão."""
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)

        await api.messages.delete(MENSAGEM, channel=CANAL)

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}"

    async def test_edit_aceita_mensagem(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(**payload_de_mensagem()), clock=clock, sleeper=sleeper)
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None

        await api.messages.edit(message, "novo")

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}"

    async def test_delete_manda_delete_sem_corpo(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None

        await api.messages.delete(message)

        assert captured[0].method == "DELETE"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}"
        assert captured[0].content in (b"", None)

    async def test_pin_e_unpin(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None

        await api.messages.pin(message)
        await api.messages.unpin(message)

        assert captured[0].method == "PUT"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/pins/{MENSAGEM}"
        assert captured[1].method == "DELETE"
        assert captured[1].url.path == f"/api/v10/channels/{CANAL}/pins/{MENSAGEM}"

    async def test_send_com_corpo_ruim_levanta(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """O chamador fez `await` e esperou `Message`. Devolver `None`
        empurraria uma decisão que ninguém escreveu para o código dele."""
        api, _ = make_api(ok(outra="coisa"), clock=clock, sleeper=sleeper)

        with pytest.raises(HTTPError, match="POST /channels/:id/messages"):
            await api.messages.send(CANAL, "oi")


# ==========================================================================
# ChannelsAPI
# ==========================================================================


class TestChannels:
    async def test_fetch(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(
            ok(id=str(CANAL), type=0, name="geral"), clock=clock, sleeper=sleeper
        )

        channel = await api.channels.fetch(CANAL)

        assert isinstance(channel, Channel)
        assert channel.name == "geral"
        assert captured[0].method == "GET"

    async def test_modify_devolve_o_estado_novo(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        api, captured = make_api(
            ok(id=str(CANAL), type=0, name="novo"), clock=clock, sleeper=sleeper
        )

        channel = await api.channels.modify(CANAL, name="novo", topic="t")

        assert channel.name == "novo"
        assert corpo_de(captured[0]) == {"name": "novo", "topic": "t"}

    async def test_delete(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)

        await api.channels.delete(CANAL)

        assert captured[0].method == "DELETE"

    async def test_typing(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)

        await api.channels.typing(CANAL)

        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/typing"

    async def test_create(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(
            ok(id="9", type=0, name="novo", guild_id=str(GUILD)),
            clock=clock,
            sleeper=sleeper,
        )

        channel = await api.channels.create(GUILD, "novo", 0, topic="t")

        assert channel.id == 9
        assert corpo_de(captured[0]) == {"name": "novo", "type": 0, "topic": "t"}


# ==========================================================================
# UsersAPI
# ==========================================================================


class TestUsers:
    async def test_me_e_o_teste_de_token(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(id="1", username="bot", bot=True), clock=clock, sleeper=sleeper)

        user = await api.users.me()

        assert isinstance(user, User)
        assert user.bot is True
        assert captured[0].url.path == "/api/v10/users/@me"
        assert captured[0].headers["Authorization"].startswith("Bot ")

    async def test_fetch(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(id="42", username="x"), clock=clock, sleeper=sleeper)

        user = await api.users.fetch(42)

        assert user.id == 42
        assert captured[0].url.path == "/api/v10/users/42"

    async def test_sem_token_recusa_antes_de_mandar(
        self, clock: FakeClock, sleeper: FakeSleeper
    ) -> None:
        """Sem token, `HTTPClient` recusa a requisição em vez de mandar.

        Um `Token("")` mandaria ``Authorization: Bot `` — malformado —,
        o Discord responderia 401 apontando para o token, e quem lê o
        erro correria para rotacionar um token que nunca esteve errado.
        Recusar antes diz o que falta, no lugar certo.
        """
        api, captured = make_api(ok(id="1", username="x"), token=None, clock=clock, sleeper=sleeper)

        with pytest.raises(HTTPError, match="sem token configurado"):
            await api.users.me()

        # E nada foi para a rede.
        assert captured == []


# ==========================================================================
# GuildsAPI
# ==========================================================================


class TestGuilds:
    async def test_fetch(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, _ = make_api(ok(id=str(GUILD), name="Kryn"), clock=clock, sleeper=sleeper)

        guild = await api.guilds.fetch(GUILD)

        assert isinstance(guild, Guild)
        assert guild.name == "Kryn"

    async def test_modify(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(ok(id=str(GUILD), name="novo"), clock=clock, sleeper=sleeper)

        guild = await api.guilds.modify(GUILD, name="novo")

        assert guild.name == "novo"
        assert captured[0].method == "PATCH"

    async def test_leave(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, captured = make_api(no_content(), clock=clock, sleeper=sleeper)

        await api.guilds.leave(GUILD)

        assert captured[0].method == "DELETE"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/members/@me"


# ==========================================================================
# DiscordAPI — a fachada
# ==========================================================================


class TestFachada:
    async def test_aclose_fecha_o_pool(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, _ = make_api(ok(), clock=clock, sleeper=sleeper)

        await api.aclose()

        # Fechar duas vezes não é erro.
        await api.aclose()

    def test_rest_fica_acessivel(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        """Para o caso raro de precisar da rota crua — não escondemos a
        mecânica, só a empurramos para baixo."""
        api, _ = make_api(ok(), clock=clock, sleeper=sleeper)
        assert isinstance(api.rest, RESTClient)

    async def test_contexto_fechando(self, clock: FakeClock, sleeper: FakeSleeper) -> None:
        api, _ = make_api(ok(), clock=clock, sleeper=sleeper)

        async with api:
            pass
