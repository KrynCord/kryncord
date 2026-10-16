"""Canais e threads: leitura, criação, moderação e arquivos.

O Discord tem dezenas de tipos de canal, e quase toda modificação
aceita só alguns campos por tipo — mudar ``name`` de um canal de voz
funciona, mudar ``topic`` não. Aqui não validamos isso: o campo que não
se aplica o Discord ignora ou recusa com a mensagem certa, e duplicar
essa tabela seria uma segunda fonte de verdade para sair de sincronia.

**Threads são `Channel`.** O Discord não tem objeto separado: uma thread
é um canal de tipo 10 (anunciada), 11 (pública) ou 12 (privada), com
campos extras (`archived`, `locked`, `owner_id`). `Channel.is_thread()`
já distingue, e é por isso que nada aqui devolve um "Thread".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.api._parse import expect_list, expect_model
from kryncord.api._resolve import ChannelLike, MessageLike, channel_id_of, message_id_of
from kryncord.errors import HTTPError
from kryncord.models.channel import Channel
from kryncord.models.message import Message
from kryncord.rest.client import RESTClient

#: Máximo que `GET /channels/:id/messages` aceita por página.
MAX_MESSAGES_PAGE = 100

#: Mensagens por chamada em `delete_messages`. O Discord não aceita mais
#: que 100 de uma vez — acima, ele responde 400 e não diz o limite.
MAX_BULK_DELETE = 100

#: Idade máxima de mensagem apagável em lote, em dias. Mais velho que
#: isso o Discord **ignora** silenciosamente: o endpoint não falha, ele
#: só não apaga. Ninguém avisa.
BULK_DELETE_MAX_AGE_DAYS = 14


@dataclass(frozen=True, slots=True)
class ThreadBatch:
    """Uma página de threads arquivadas.

    `has_more` não é decoração: sem ele, o fim da paginação seria
    "recebi menos que `limit`", que é uma suposição — o Discord pode
    devolver página cheia e ainda ter mais, ou página curta e ainda ter.
    Aqui ele vem no payload, e é o que este tipo preserva.
    """

    threads: tuple[Channel, ...]
    has_more: bool

    @property
    def oldest_id(self) -> int | None:
        """Cursor para a página seguinte, ou `None` se a lista vazia.

        É o ``before`` da próxima chamada — a lista vem em ordem
        decrescente, então o último item é o mais antigo.
        """
        if not self.threads:
            return None
        return self.threads[-1].id


class ChannelsAPI:
    """Operações de canal e de thread."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    # ------------------------------------------------------------------
    # Leitura e escrita de canal
    # ------------------------------------------------------------------

    async def fetch(self, channel: ChannelLike) -> Channel:
        """Busca um canal pelo ID, ou pelo objeto que o identifica."""
        identificador = channel_id_of(channel)
        return expect_model(
            Channel,
            await self._rest.request("GET", f"/channels/{identificador}"),
            route="GET /channels/:id",
        )

    async def modify(self, channel: ChannelLike, **fields: Any) -> Channel:
        """Altera campos do canal e devolve o estado novo.

        `fields` é o corpo direto: ``name``, ``topic``,
        ``rate_limit_per_user``, ``nsfw``. Sem intermediário que
        renomeie — o nome do campo é o do Discord, e quem lê o docs
        consegue escrever aqui.
        """
        identificador = channel_id_of(channel)
        return expect_model(
            Channel,
            await self._rest.request("PATCH", f"/channels/{identificador}", json=fields),
            route="PATCH /channels/:id",
        )

    async def delete(self, channel: ChannelLike) -> None:
        """Apaga o canal. Devolve 204, sem corpo. Não há desfazer."""
        identificador = channel_id_of(channel)
        await self._rest.request("DELETE", f"/channels/{identificador}")

    async def typing(self, channel: ChannelLike) -> None:
        """Mostra o indicador "digitando…".

        Dura 10 segundos no servidor e não pode ser desfeito — não há
        endpoint de parar. Se o bot demora mais que isso para responder,
        vale reenviar enquanto trabalha.
        """
        identificador = channel_id_of(channel)
        await self._rest.request("POST", f"/channels/{identificador}/typing", json={})

    async def create(
        self,
        guild_id: int | str,
        name: str,
        channel_type: int,
        **fields: Any,
    ) -> Channel:
        """Cria um canal num servidor.

        `channel_type` é o número do `ChannelType` (0 = texto, 2 = voz,
        4 = categoria, 11 = thread…). Vem como número porque é o que o
        Discord aceita, e inventar um enum parcial aqui seria uma segunda
        lista para manter.
        """
        return expect_model(
            Channel,
            await self._rest.request(
                "POST",
                f"/guilds/{guild_id}/channels",
                json={"name": name, "type": channel_type, **fields},
            ),
            route="POST /guilds/:id/channels",
        )

    # ------------------------------------------------------------------
    # Mensagens
    # ------------------------------------------------------------------

    async def list_messages(
        self,
        channel: ChannelLike,
        *,
        limit: int = 50,
        before: int | str | None = None,
        after: int | str | None = None,
        around: int | str | None = None,
    ) -> list[Message]:
        """Uma página de mensagens, da mais recente para a mais antiga.

        `before` é o cursor normal — passe o `id` da última mensagem
        recebida. `after` anda para frente (mais recentes), `around`
        busca em volta de uma mensagem específica, que é o caminho do
        "mostrar contexto".

        Os três juntos não combinam: o Discord aceita ``before`` **ou**
        ``after`` **ou** ``around``, e mandar dois ele usa um e ignora
        o outro, sem dizer qual. Aqui não barra — é dele a regra.

        `limit` acima de 100 vira 100. Ele não reclama, ele corta.
        """
        query: dict[str, Any] = {"limit": min(limit, MAX_MESSAGES_PAGE)}
        for key, value in (("before", before), ("after", after), ("around", around)):
            if value is not None:
                query[key] = value
        return expect_list(
            Message,
            await self._rest.request(
                "GET", f"/channels/{channel_id_of(channel)}/messages", query=query
            ),
            route="GET /channels/:id/messages",
        )

    async def delete_messages(
        self,
        channel: ChannelLike,
        messages: Iterable[MessageLike],
        *,
        reason: str | None = None,
    ) -> None:
        """Apaga mensagens em lote. Devolve 204, sem corpo.

        Três coisas que o Discord não diz quando dá errado:

        * Mais de **100** por chamada → 400. Este método não separa em
          páginas sozinho: a intenção de "apagar 500" e a de "apagar 3"
          são diferentes, e partir em silêncio esconderia que houve
          cinco chamadas e cinco rate limits.
        * Mensagens com mais de **14 dias** são **ignoradas**, não
          recusadas — o endpoint responde 204 e não apaga nada. Para
          isso existe o apagar-um-por-um.
        * ``reason`` vai no header de auditoria, que a camada `rest/`
          monta e faz URL-encoding.
        """
        ids = [str(message_id_of(m)) for m in messages]
        if not ids:
            # Um `POST` com lista vazia responde 400 apontando `messages`,
            # que é a mensagem errada para "não mandou nada para apagar".
            return
        if len(ids) > MAX_BULK_DELETE:
            raise ValueError(
                f"Apagar em lote aceita até {MAX_BULK_DELETE} mensagens por "
                f"chamada — recebi {len(ids)}. Parta a lista e chame de novo; "
                "esse método não parte sozinho para não esconder que são "
                "várias requisições."
            )
        await self._rest.request(
            "POST",
            f"/channels/{channel_id_of(channel)}/messages/delete",
            json={"messages": ids},
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def create_thread(
        self,
        channel: ChannelLike,
        name: str,
        *,
        message: MessageLike | None = None,
        **fields: Any,
    ) -> Channel:
        """Cria uma thread.

        `message` ligado transforma em thread **de mensagem**: ela nasce
        da mensagem citada, e o Discord mostra a resposta no contexto
        dela. Sem `message`, é thread iniciada à mão num canal de texto.

        Os dois não combinam — mandar os dois o Discord recusa com 400.
        """
        identificador = channel_id_of(channel)
        body: dict[str, Any] = {"name": name, **fields}
        if message is not None:
            body["message_id"] = str(message_id_of(message))
        return expect_model(
            Channel,
            await self._rest.request("POST", f"/channels/{identificador}/threads", json=body),
            route="POST /channels/:id/threads",
        )

    async def join_thread(self, channel: ChannelLike) -> None:
        """Entra na thread. Devolve 204, sem corpo.

        Thread privada exige convite — entrar à força dá 403.
        """
        await self._rest.request("PUT", f"/channels/{channel_id_of(channel)}/thread-members/@me")

    async def leave_thread(self, channel: ChannelLike) -> None:
        """Sai da thread. Devolve 204, sem corpo."""
        await self._rest.request("DELETE", f"/channels/{channel_id_of(channel)}/thread-members/@me")

    async def list_thread_members(self, channel: ChannelLike) -> list[dict[str, Any]]:
        """Quem está na thread, como dicts.

        Sem modelo: o payload traz a entrada de **cada membro** com
        campos que não existem no `Member` normal (``id`` do membro é o
        do usuário, e há ``join_timestamp`` e ``flags``). Um `Member`
        com metade dos campos faltando seria pior que o dict cru.
        """
        body = await self._rest.request_json(
            "GET", f"/channels/{channel_id_of(channel)}/thread-members"
        )
        if not isinstance(body, list):
            raise HTTPError(
                f"GET /channels/:id/thread-members devolveu {type(body).__name__}, esperava lista",
            )
        return [dict(item) for item in body if isinstance(item, Mapping)]

    async def list_active_threads(self, guild_id: int | str) -> ThreadBatch:
        """Threads ainda ativas (não arquivadas) do servidor.

        Não pagina — uma chamada devolve todas as ativas, que é sempre
        um número contido. As arquivadas é que precisam de cursor.
        """
        body = await self._rest.request_json("GET", f"/guilds/{guild_id}/threads/active")
        return _batch(body, route="GET /guilds/:id/threads/active")

    async def list_archived_threads(
        self,
        channel: ChannelLike,
        *,
        limit: int = 50,
        before: int | str | None = None,
        public: bool | None = None,
    ) -> ThreadBatch:
        """Uma página de threads arquivadas, com `has_more`.

        `before` é o cursor — passe `batch.oldest_id` da chamada
        anterior. `public=True` busca as públicas, `False` as privadas,
        `None` as duas (que é o default do Discord).

        Uma thread arquivada volta a ficar ativa sozinha quando alguém
        manda mensagem nela — não é preciso reabrir.
        """
        tipo = "public" if public is True else "private" if public is False else "public"
        query: dict[str, Any] = {"limit": limit}
        if before is not None:
            query["before"] = before
        identificador = channel_id_of(channel)
        body = await self._rest.request_json(
            "GET", f"/channels/{identificador}/threads/archived/{tipo}", query=query
        )
        return _batch(
            body,
            route=f"GET /channels/:id/threads/archived/{tipo}",
        )


def _batch(body: Any, *, route: str) -> ThreadBatch:
    """Converte ``{threads, has_more}`` em `ThreadBatch`.

    `has_more` ausente vira `False`, que é o único default honesto:
    o Discord manda sempre, e um payload sem ele não dá para paginar —
    afirmar ``True`` mandaria o chamador buscar página que não existe.
    """
    if not isinstance(body, Mapping):
        raise HTTPError(f"{route} devolveu {type(body).__name__}, esperava objeto")
    raw = body.get("threads")
    threads: list[Channel] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            channel = Channel.from_payload(item)
            if channel is not None:
                threads.append(channel)
    has_more = body.get("has_more")
    return ThreadBatch(threads=tuple(threads), has_more=bool(has_more))
