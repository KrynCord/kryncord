"""Resposta a interações — o relógio de 3 segundos.

A regra que governa este módulo inteiro:

    **O Discord dá 3 segundos.** Passou, ele descarta e mostra
    "A aplicação não respondeu". Não adianta responder depois — o
    erro já apareceu para o usuário, e o token continua válido,
    então uma resposta tardia some sem dar sinal.

Por isso `defer` existe, e é o método mais importante daqui. Ele troca
a resposta por um "pensando…" que o Discord mostra **na primeira
segunda**, e compra **15 minutos** para o `followup` completar. Quem
não sabe quanto tempo vai levar, faz `defer` primeiro — é sempre
melhor um carregamento que vira resposta que um erro que não vira
nada.

`callback` é o único caminho de resposta: tudo o mais aqui (respond,
defer, update_message, pong, modal) monta o ``type`` certo e delega.
Cinco métodos porque são cinco os códigos que o Discord aceita, e
lembrar que ``7`` é "atualizar mensagem" é decodificar número em
documentação toda vez.

A autenticação é o ``token`` da interação, que vai na URL. Um followup
com token válido funciona sem ``Authorization`` nenhuma — e é segredo:
quem o tem responde no lugar do bot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from kryncord.api._parse import expect_model
from kryncord.builders.messages import normalizar_mensagem
from kryncord.enums import InteractionResponseType
from kryncord.errors import DiscordAPIError
from kryncord.models.interaction import Interaction
from kryncord.models.message import Message
from kryncord.rest.client import RESTClient

#: Tempo que o Discord dá para a **primeira** resposta, em segundos.
RESPONSE_WINDOW_S = 3

#: Tempo que um `defer` compra para o `followup`, em minutos.
DEFERRED_WINDOW_MIN = 15


class InteractionsAPI:
    """Resposta a comandos, botões, selects e modals."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    # ------------------------------------------------------------------
    # Primeira resposta
    # ------------------------------------------------------------------

    async def callback(
        self,
        interaction: Interaction,
        response_type: int | InteractionResponseType,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Responde a interação. Devolve 204, sem corpo.

        É o único endpoint de primeira resposta — os métodos daqui
        montam `data` e chamam este. `response_type` aceita o número ou
        o `InteractionResponseType`, porque quem decora ``5`` é quem
        lê o docs do Discord toda vez.
        """
        await self._rest.request(
            "POST",
            f"/interactions/{interaction.id}/{interaction.token}/callback",
            json={"type": int(response_type), "data": data}
            if data
            else {"type": int(response_type)},
        )

    async def respond(
        self, interaction: Interaction, content: str | None = None, **kwargs: Any
    ) -> None:
        """Responde com mensagem, dentro dos 3 segundos.

        `content=None` e nenhum outro campo manda ``data: {}``, que o
        Discord recusa — uma resposta sem nada não é resposta. O erro
        vem como 400 apontando ``data``, que é o campo errado para o
        problema real (que é "não mandou conteúdo").
        """
        data = _message_data(content, kwargs)
        if not data:
            # Erro de argumento, não de HTTP: nada foi mandado, e nenhum
            # status do Discord descreveria isto. `ValueError` é o tipo
            # que quem chama espera de validação de chamada.
            raise ValueError(
                "Resposta de interação vazia — manda content, embed, "
                "component ou outra coisa que o usuário veja. Para ganhar "
                "tempo sem conteúdo, use defer()."
            )
        await self.callback(interaction, InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE, data)

    async def defer(
        self,
        interaction: Interaction,
        *,
        ephemeral: bool = False,
    ) -> None:
        """Mostra "pensando…" e compra 15 minutos.

        `ephemeral=True` faz o pensando ser visível só para quem
        invocou — e a resposta final herda isso, que é o caminho
        comum de "só quem chamou vê".

        De componente o Discord já mostra o carregamento no botão, e
        mandar "pensando…" de novo duplicaria — por isso o tipo muda
        sozinho, conforme `interaction.is_message_component()`.
        """
        if interaction.is_message_component():
            response_type = InteractionResponseType.DEFERRED_UPDATE_MESSAGE
            data: dict[str, Any] | None = None
        else:
            response_type = InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            data = {"flags": 64} if ephemeral else None
        await self.callback(interaction, response_type, data)

    async def defer_update(self, interaction: Interaction) -> None:
        """Confirma o clique sem mudar a mensagem.

        `DEFERRED_UPDATE_MESSAGE` explícito — o `defer()` já chega aqui
        sozinho quando a interação é componente, mas o handler de botão
        que sabe o que quer não deveria depender dessa escolha implícita
        para a leitura do código (0023, R1).
        """
        await self.callback(interaction, InteractionResponseType.DEFERRED_UPDATE_MESSAGE)

    async def update_message(
        self, interaction: Interaction, content: str | None = None, **kwargs: Any
    ) -> None:
        """Substitui a mensagem que continha o componente.

        O caminho de botão que edita a própria mensagem. `content=None`
        com embed no `kwargs` também serve — o Discord troca a mensagem
        inteira, não mescla.
        """
        await self.callback(
            interaction,
            InteractionResponseType.UPDATE_MESSAGE,
            _message_data(content, kwargs),
        )

    async def pong(self, interaction: Interaction) -> None:
        """Responde a um `PING` (tipo 1) do Discord.

        Só acontece em verificação de URL do endpoint de interação.
        Quem não responde não recebe evento nenhum, e o Discord mostra
        "falha na verificação" no portal sem dizer mais.
        """
        await self.callback(interaction, InteractionResponseType.PONG)

    async def show_modal(self, interaction: Interaction, modal: Mapping[str, Any]) -> None:
        """Abre um modal. `modal` é o payload do Discord.

        Só é legal a partir de comando ou de botão — de select não,
        e o Discord devolve 400. Não validamos antes: a tabela de
        combinações é do Discord e muda.
        """
        await self.callback(interaction, InteractionResponseType.MODAL, modal)

    async def autocomplete(
        self, interaction: Interaction, choices: Iterable[Mapping[str, Any]]
    ) -> None:
        """Devolve as opções de um autocomplete.

        Lista vazia é legal — significa "nada a sugerir", e o Discord
        deixa o usuário digitar livre. Só 25 entram; o resto ele corta
        sem avisar.
        """
        await self.callback(
            interaction,
            InteractionResponseType.APPLICATION_COMMAND_AUTOCOMPLETE_RESULT,
            {"choices": [dict(c) for c in choices]},
        )

    async def launch_activity(self, interaction: Interaction) -> None:
        """Abre a atividade do app no canal da interação.

        Exige atividade habilitada no Developer Portal — sem ela, o
        `callback` é aceito e o Discord não faz nada. O método existe
        porque é um tipo de resposta do Discord (12) e custa uma linha;
        testar o **efeito** exigiria atividade no bot de teste
        (0023, divergência preservada).
        """
        await self.callback(interaction, InteractionResponseType.LAUNCH_ACTIVITY)

    # ------------------------------------------------------------------
    # Depois da primeira resposta
    # ------------------------------------------------------------------

    async def fetch_message(
        self,
        application_id: int | str,
        token: str,
        message_id: str | int = "@original",
    ) -> Message | None:
        """Busca uma mensagem desta interação. Padrão: a original.

        `None` quando ainda não há nenhuma: um `defer` seguido de
        `followup` sem nunca editar a original deixa ela como está, e o
        Discord devolve 404. Não é erro de rede, é "ainda não existe".

        O 404 tem que ser pego da **exceção**: `RESTClient` converte
        4xx em `DiscordAPIError` antes de devolver a `Response`, então
        checar ``response.status`` nunca seria alcançado — daria o 404
        na cara de quem só queria saber se a mensagem existe.
        """
        try:
            response = await self._rest.request(
                "GET",
                f"/webhooks/{application_id}/{token}/messages/{message_id}",
                auth=False,
            )
        except DiscordAPIError as exc:
            if exc.status == 404:
                return None
            raise
        return expect_model(
            Message,
            response,
            route=f"GET /webhooks/:id/:token/messages/{message_id}",
        )

    async def edit_message(
        self,
        application_id: int | str,
        token: str,
        message_id: str | int = "@original",
        content: str | None = None,
        **kwargs: Any,
    ) -> Message:
        """Edita uma mensagem desta interação. Padrão: a original.

        É o que transforma o "pensando…" na resposta de verdade — o
        `followup` criaria uma **segunda** mensagem, e quase toda vez
        o que se quer é editar a primeira.
        """
        return expect_model(
            Message,
            await self._rest.request(
                "PATCH",
                f"/webhooks/{application_id}/{token}/messages/{message_id}",
                json=_message_data(content, kwargs),
                auth=False,
            ),
            route=f"PATCH /webhooks/:id/:token/messages/{message_id}",
        )

    async def delete_message(
        self, application_id: int | str, token: str, message_id: str | int = "@original"
    ) -> None:
        """Apaga uma mensagem desta interação. Padrão: a original."""
        await self._rest.request(
            "DELETE",
            f"/webhooks/{application_id}/{token}/messages/{message_id}",
            auth=False,
        )

    async def followup(
        self,
        application_id: int | str,
        token: str,
        content: str | None = None,
        *,
        wait: bool = True,
        **kwargs: Any,
    ) -> Message | None:
        """Manda uma mensagem **depois** da primeira resposta.

        Diferente do `webhooks.execute`, `wait=True` aqui é o default:
        seguir a interação é quase sempre para editar ou reagir depois,
        e para isso precisa do ID — que só vem com ``wait=true``.

        Depois do `defer`, são **15 minutos** até o Discord descartar o
        token. Passou, o `followup` falha com 404 e o usuário vê o
        "pensando…" até hoje.
        """
        query = None if wait else {"wait": "false"}
        response = await self._rest.request(
            "POST",
            f"/webhooks/{application_id}/{token}",
            json=_message_data(content, kwargs),
            query=query,
            auth=False,
        )
        if not wait:
            return None
        return expect_model(Message, response, route="POST /webhooks/:id/:token")


def _message_data(content: str | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Corpo de mensagem de interação, omitindo `content` quando não veio.

    Passa pela normalização compartilhada (`normalizar_mensagem`) — é o
    ponto de convergência de `respond`/`followup`/`edit`: componente,
    embed e flag serializam aqui, uma vez. Igual a `api.messages._body`,
    e é o mesmo código porque a regra é a mesma mensagem.

    O `content` entra **antes** da normalização: a tabela V1 × V2
    precisa vê-lo para recusar `content` + flag V2 — o Discord
    **ignora** essa combinação em silêncio, e a validação depois dele
    nunca rodaria.
    """
    bruto = dict(kwargs)
    if content is not None:
        bruto["content"] = content
    return normalizar_mensagem(bruto)
