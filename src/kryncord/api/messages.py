"""Envio, edição, leitura e remoção de mensagens.

O endpoint mais usado de toda a API do Discord, e o motivo de existir
um `api/` separado do `rest/`. `RESTClient.send_message` devolve o JSON
cru; aqui devolve `Message`, aceita objeto no lugar de ID, e cuida do
``message_reference`` que todo ``reply`` precisa.

Sobre `reply` vs `send`: o Discord não tem endpoint de resposta. Um
``reply`` é um ``send`` com um campo extra dizendo qual mensagem está
sendo respondida. Fazer isso manualmente a cada vez é o tipo de
repetição que biblioteca existe para eliminar.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from kryncord.api._parse import expect_model
from kryncord.api._resolve import ChannelLike, MessageLike, channel_id_of, message_id_of
from kryncord.builders.messages import normalizar_mensagem
from kryncord.models.message import Message
from kryncord.models.partial import PartialMessage
from kryncord.rest.client import RESTClient

#: ``fail_if_not_exists: false``: responder a uma mensagem que já saiu do
#: ar não deveria falhar o envio. É o que discord.py e discord.js fazem.
_REFERENCE_DEFAULTS: dict[str, Any] = {"fail_if_not_exists": False}


class MessagesAPI:
    """Operações de mensagem, prontas para usar."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: ChannelLike,
        content: str | None = None,
        **kwargs: Any,
    ) -> Message:
        """Manda uma mensagem num canal e devolve a mensagem criada.

        `channel` aceita ID, string de ID, `Channel`, `PartialChannel`
        ou a própria `Message`. `content` pode ficar de fora quando o
        envio é só de embed ou de anexo — o campo não entra no corpo em
        vez de entrar ``null``, porque o Discord trata os dois modos.

        `kwargs` vira o resto do corpo: ``tts``, ``embeds``,
        ``allowed_mentions``, ``files``. Sem validação aqui — validar
        payload é trabalho do Discord, que devolve a mensagem de erro
        com o campo apontado.
        """
        return await self._send_to(channel_id_of(channel), _body(content, kwargs))

    async def reply(
        self,
        message: MessageLike,
        content: str | None = None,
        *,
        mention_author: bool = True,
        **kwargs: Any,
    ) -> Message:
        """Responde a uma mensagem, com o ``message_reference`` pronto.

        `mention_author=False` manda a resposta sem pingar quem escreveu
        — o comportamento padrão do Discord é pingar, e é o que quase
        todo bot de reply quer desligar em alguma situação.
        """
        body = _body(content, kwargs)
        body["message_reference"] = {
            "message_id": str(message_id_of(message)),
            **_REFERENCE_DEFAULTS,
        }
        if not mention_author:
            # O Discord não tem flag de "não pinge"; a forma é suprimir
            # a menção no `allowed_mentions`. Só o autor da mensagem
            # respondida, e ele suprimido — o resto do conteúdo passa.
            allowed = dict(body.get("allowed_mentions") or {})
            allowed["users"] = []
            body["allowed_mentions"] = allowed

        return await self._send_to(_channel_for(message, None), body)

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    async def fetch(self, channel: ChannelLike, message_id: MessageLike) -> Message:
        """Busca uma mensagem específica.

        Tem limite próprio de rate limit (50/h por canal), separado do
        bucket de envio — o `RESTClient` descobre isso pelos headers e
        cuida sozinho.
        """
        canal = channel_id_of(channel)
        identificador = message_id_of(message_id)
        return expect_model(
            Message,
            await self._rest.request("GET", f"/channels/{canal}/messages/{identificador}"),
            route="GET /channels/:id/messages/:id",
        )

    # ------------------------------------------------------------------
    # Edição
    # ------------------------------------------------------------------

    async def edit(
        self,
        message: MessageLike,
        content: str | None = None,
        *,
        channel: ChannelLike | None = None,
        **kwargs: Any,
    ) -> Message:
        """Edita uma mensagem e devolve a versão nova.

        O Discord devolve o objeto inteiro atualizado, e não só o que
        mudou — por isso o retorno é uma `Message` nova, não a mesma
        alterada. Modelos são `frozen`: o que o handler tinha na mão
        continua sendo o estado da mensagem no momento em que ele viu.

        `channel` só é preciso quando `message` veio como ID puro — um
        `Message` ou `PartialMessage` carrega o `channel_id` sozinho.
        """
        identificador = message_id_of(message)
        canal = _channel_for(message, channel)
        return expect_model(
            Message,
            await self._rest.request(
                "PATCH",
                f"/channels/{canal}/messages/{identificador}",
                json=_body(content, kwargs),
            ),
            route="PATCH /channels/:id/messages/:id",
        )

    # ------------------------------------------------------------------
    # Remoção e fixação
    # ------------------------------------------------------------------

    async def delete(self, message: MessageLike, *, channel: ChannelLike | None = None) -> None:
        """Apaga uma mensagem. Devolve 204, sem corpo."""
        identificador = message_id_of(message)
        await self._rest.request(
            "DELETE", f"/channels/{_channel_for(message, channel)}/messages/{identificador}"
        )

    async def pin(self, message: MessageLike, *, channel: ChannelLike | None = None) -> None:
        """Fixa a mensagem no canal."""
        identificador = message_id_of(message)
        await self._rest.request(
            "PUT", f"/channels/{_channel_for(message, channel)}/pins/{identificador}", json={}
        )

    async def unpin(self, message: MessageLike, *, channel: ChannelLike | None = None) -> None:
        """Desafixa a mensagem."""
        identificador = message_id_of(message)
        await self._rest.request(
            "DELETE", f"/channels/{_channel_for(message, channel)}/pins/{identificador}"
        )

    # ------------------------------------------------------------------
    # Reações
    # ------------------------------------------------------------------

    async def add_reaction(
        self,
        message: MessageLike,
        emoji: str,
        *,
        user_id: int | str = "@me",
        channel: ChannelLike | None = None,
    ) -> None:
        """Reage a uma mensagem. Devolve 204, sem corpo.

        `emoji` aceita as três formas: ``👍``, ``name:123`` (custom já
        desmontado) e ``<:name:123>`` (como aparece no chat). Montar o
        segmento é trabalho aqui porque o caminho vai cru para a URL —
        emoji direto no log do Windows sai mojibake, e `<:name:123>`
        teria ``<`` e ``>`` que o Discord recusa no path.

        `user_id="@me"` é o bot. Outro usuário exige permissão
        ``MANAGE_MESSAGES`` — senão, 403.
        """
        await self._rest.request(
            "PUT",
            f"/channels/{_channel_for(message, channel)}/messages/"
            f"{message_id_of(message)}/reactions/{_emoji_segment(emoji)}/{user_id}",
        )

    async def remove_reaction(
        self,
        message: MessageLike,
        emoji: str,
        *,
        user_id: int | str = "@me",
        channel: ChannelLike | None = None,
    ) -> None:
        """Tira uma reação. Devolve 204, sem corpo."""
        await self._rest.request(
            "DELETE",
            f"/channels/{_channel_for(message, channel)}/messages/"
            f"{message_id_of(message)}/reactions/{_emoji_segment(emoji)}/{user_id}",
        )

    async def remove_all_reactions(
        self, message: MessageLike, *, channel: ChannelLike | None = None
    ) -> None:
        """Tira **todas** as reações de todos. Devolve 204, sem corpo.

        Requer ``MANAGE_MESSAGES`` — remover só a de um usuário não
        exige, remover de todo mundo exige. São dois endpoints
        diferentes, e é a diferença entre moderação e limpeza.
        """
        await self._rest.request(
            "DELETE",
            f"/channels/{_channel_for(message, channel)}/messages/"
            f"{message_id_of(message)}/reactions",
        )

    async def remove_all_reactions_for(
        self,
        message: MessageLike,
        emoji: str,
        *,
        channel: ChannelLike | None = None,
    ) -> None:
        """Tira todas as reações **de um emoji** — de todo mundo.

        O meio-termo: limpar o 👍 de todos sem apagar o resto da
        contagem.
        """
        await self._rest.request(
            "DELETE",
            f"/channels/{_channel_for(message, channel)}/messages/"
            f"{message_id_of(message)}/reactions/{_emoji_segment(emoji)}",
        )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    async def _send_to(self, canal: int, body: dict[str, Any]) -> Message:
        return expect_model(
            Message,
            await self._rest.request("POST", f"/channels/{canal}/messages", json=body),
            route="POST /channels/:id/messages",
        )


def _channel_for(message: MessageLike, channel: ChannelLike | None) -> int:
    """Canal onde a mensagem está.

    `Message` e `PartialMessage` carregam o `channel_id`, e o chamador
    não precisa dizer nada. Um ID puro não carrega — e aí `channel=` diz
    o que um int não pode.

    Falhando as duas, `TypeError` com a saída na mensagem, em vez de
    mandar a requisição para o canal errado. Um 404 do Discord apontaria
    para "mensagem não encontrada", que é a resposta errada para o
    problema real.
    """
    if channel is not None:
        return channel_id_of(channel)
    if isinstance(message, (Message, PartialMessage)):
        return message.channel_id
    raise TypeError(
        f"Não dá para descobrir o canal de {message!r} — passe um objeto "
        "com channel_id, ou informe channel=..."
    )


def _body(content: str | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Monta o corpo, omitindo `content` quando não veio.

    ``{"content": None}`` e ``{}`` significam a mesma coisa para o
    Discord, mas o segundo é mais honesto: o campo não foi enviado.

    Passa pela normalização compartilhada — componente, embed e flag
    serializam aqui como no `api.interactions._message_data`, porque
    a regra é a mesma mensagem nos dois endpoints. O `content` entra
    **antes**: a tabela V1 × V2 precisa vê-lo para recusar `content`
    junto com flag V2.
    """
    bruto = dict(kwargs)
    if content is not None:
        bruto["content"] = content
    return normalizar_mensagem(bruto)


def _emoji_segment(emoji: str) -> str:
    """Converte qualquer forma de emoji no segmento que a URL pede.

    Quatro formas chegam, e as duas de custom têm um detalhe que quebra
    quem só tira os ``<>``:

    * ``👍`` — unicode, vai direto para percent-encoding;
    * ``name:123`` — custom já desmontado, passa como está;
    * ``<:name:123>`` — depois de tirar ``<>`` sobra **``:name:123``**,
      com dois-pontos na frente, porque o formatador é ``<`` +
      ``:name:123`` + ``>``;
    * ``<a:name:123>`` — animado, sobra ``a:name:123``. O ``a_`` de
      animação é com **dois-pontos**, não sublinhado — e no caminho o
      Discord não distingue, então ele sai.

    Percent-encoding no fim é o que o Discord espera, e mantém a rota em
    ASCII — que importa porque a rota vira nome de bucket e entra em log
    (emoji cru no console do Windows sai mojibake).
    """
    bruto = emoji.strip()
    if bruto.startswith("<") and bruto.endswith(">"):
        bruto = bruto[1:-1]
    if bruto.startswith("a:"):
        bruto = bruto[2:]
    elif bruto.startswith(":"):
        bruto = bruto[1:]
    # `safe=":"` deixa `name:123` legível no log e na URL — dois-pontos
    # é legal em segmento de caminho (RFC 3986, `pchar`).
    return quote(bruto, safe=":")
