"""Máquina de estados da resposta a uma interação.

Uma interação aceita **uma** resposta inicial. Depois disso, só
follow-up e edição. Violar isso é erro do Discord — e o erro dele é um
400 genérico que não diz qual chamada estava fora de ordem. Guardar
antes é o único jeito de apontar o problema certo.

O dono do estado é este contexto, e não o modelo `Interaction`: o
modelo continua dado puro (`0003`), e o mesmo `Interaction` pode ser
entregue a mais de um contexto durante um dispatch.

    UNANSWERED ──reply──────────────> ANSWERED
         │                              ▲
         ├──defer/defer_update────> DEFERRED ──edit──────────────┘
         │                              │
         ├──update──────────────────────>│  (direto a ANSWERED)
         ├──launch_activity──────────────>│
         └──send_modal────────────> MODAL   (terminal)
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from kryncord.api.interactions import InteractionsAPI
from kryncord.errors import InteractionStateError
from kryncord.models.interaction import Interaction


class InteractionState(IntEnum):
    """Estados possíveis de uma resposta."""

    UNANSWERED = 0
    """Nada foi enviado. Único estado de onde uma resposta inicial sai."""
    DEFERRED = 1
    """Defer enviado — comprou 15 minutos, mas ainda não respondeu."""
    ANSWERED = 2
    """Resposta final enviada. Edição continua possível."""
    MODAL = 3
    """Modal aberto — terminal. Não há follow-up de modal."""

    @property
    def responded(self) -> bool:
        """Se já houve alguma resposta.

        Um defer **já respondeu** — é por isso que o método público se
        chama `is_responded()` e não `is_replied()`. Quem pergunta
        "posso responder?" quer `False` só em `UNANSWERED`.
        """
        return self is not InteractionState.UNANSWERED


#: Transições a partir de cada estado, por ação. O `_` é o resultado —
#: `None` significa "erro", e o chamador levanta com contexto.
_TRANSICOES: dict[InteractionState, dict[str, InteractionState | None]] = {
    InteractionState.UNANSWERED: {
        "reply": InteractionState.ANSWERED,
        "defer": InteractionState.DEFERRED,
        "defer_update": InteractionState.DEFERRED,
        "update": InteractionState.ANSWERED,
        "send_modal": InteractionState.MODAL,
        "launch_activity": InteractionState.ANSWERED,
        "ack": InteractionState.DEFERRED,
    },
    InteractionState.DEFERRED: {
        "edit": InteractionState.ANSWERED,
        "send_modal": InteractionState.MODAL,
        # `ack` de novo é no-op: o chamador queria garantir que foi
        # acknowledge, e garantir é garantir — reclamar seria dizer que
        # ele errou por ter atingido o objetivo.
        "ack": InteractionState.DEFERRED,
    },
    InteractionState.ANSWERED: {
        # Edição é idempotente: responder e editar é o fluxo normal.
        "edit": InteractionState.ANSWERED,
        "ack": InteractionState.ANSWERED,
    },
    InteractionState.MODAL: {
        "ack": InteractionState.MODAL,
    },
}


class InteractionContext:
    """Estado e respostas de uma interação.

    Um por dispatch. `reply`/`defer`/`edit` são delegação para o
    `InteractionsAPI` — este objeto só decide **se pode** e **o que
    mudou de estado**. Centralizar isso é o que torna a ordem testável
    sem rede.
    """

    __slots__ = ("_api", "_emitidos", "_interaction", "_profundidade", "_state")

    def __init__(self, interaction: Interaction, api: InteractionsAPI) -> None:
        self._interaction = interaction
        self._api = api
        self._state = InteractionState.UNANSWERED
        #: Guardas do `emit_responder` (ideia 09 §5). Vivem aqui, e não
        #: no `ResponderContext`, porque aqui é o "um por dispatch" —
        #: um emit cria contexto novo, e perder a contagem seria deixar
        #: o loop voltar.
        self._emitidos: set[str] = set()
        self._profundidade = 0

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    @property
    def interaction(self) -> Interaction:
        return self._interaction

    @property
    def state(self) -> InteractionState:
        return self._state

    def is_responded(self) -> bool:
        """Se já houve qualquer resposta — defer inclusive."""
        return self._state.responded

    def is_deferred(self) -> bool:
        return self._state is InteractionState.DEFERRED

    def is_answered(self) -> bool:
        return self._state is InteractionState.ANSWERED

    @property
    def emitidos(self) -> set[str]:
        """`custom_id`s já emitidos neste dispatch — guarda do `emit_responder`."""
        return self._emitidos

    @property
    def profundidade(self) -> int:
        """Nível de `emit_responder` aninhado — guarda contra loop."""
        return self._profundidade

    @profundidade.setter
    def profundidade(self, valor: int) -> None:
        self._profundidade = valor

    # ------------------------------------------------------------------
    # Resposta inicial
    # ------------------------------------------------------------------

    async def reply(self, content: str | None = None, **kwargs: Any) -> None:
        """Responde com mensagem, dentro dos 3 segundos.

        `ephemeral` é uma escolha única por interação — e não há um
        guarda separado para ela porque a máquina de estados já cobre:
        repetir a chamada é `InteractionStateError` antes de qualquer
        comparação de flag. Um segundo guarda seria código que nunca
        roda.
        """
        self._exige("reply")
        await self._api.respond(self._interaction, content, **kwargs)
        self._state = _TRANSICOES[self._state]["reply"]  # type: ignore[assignment]

    async def defer(self, *, ephemeral: bool = False) -> None:
        """Mostra "pensando…" e compra 15 minutos.

        `ephemeral=True` faz o pensando visível só para quem invocou,
        e a resposta final herda — é o caminho comum de "só quem chamou
        vê".

        Em componente o Discord já mostra o carregamento no botão, então
        o tipo muda sozinho para `DEFERRED_UPDATE_MESSAGE` — e aí
        **`ephemeral=True` é erro**, porque aquele tipo não aceita flags.
        Descartá-las em silencioso era o comportamento antigo e é
        exatamente o que o `0023` baniu: o usuário pedia "só quem chamou
        vê" e não via. O caminho para pensando efêmero de botão é
        `defer_update()` + `follow_up(ephemeral=True)`.
        """
        if ephemeral and self._interaction.is_message_component():
            raise ValueError(
                "defer(ephemeral=True) num componente não existe — DEFERRED_UPDATE_MESSAGE "
                "não aceita flags, então a ephemeral seria descartada em silêncio. Use "
                "defer_update() e depois follow_up(ephemeral=True)."
            )
        self._exige("defer")
        await self._api.defer(self._interaction, ephemeral=ephemeral)
        self._state = _TRANSICOES[self._state]["defer"]  # type: ignore[assignment]

    async def defer_update(self) -> None:
        """Confirma o clique **sem** mudar a mensagem.

        Pergunta própria, diferente da do `defer()`: este é o handler de
        botão que sabe o que quer, e não o que só precisa de tempo. Só
        existe em componente — em comando, o Discord não tem "mensagem
        a confirmar".
        """
        if not self._interaction.is_message_component():
            raise InteractionStateError(
                "defer_update() só existe em interação de componente — em comando não há "
                "mensagem a confirmar, e o equivalente é defer()"
            )
        self._exige("defer_update")
        await self._api.defer_update(self._interaction)
        self._state = _TRANSICOES[self._state]["defer_update"]  # type: ignore[assignment]

    async def update(self, content: str | None = None, **kwargs: Any) -> None:
        """Substitui a mensagem que continha o componente.

        Aceita vazio — diferente de `reply()`, que recusa payload sem
        nada. Aqui "mantém como está" é uma resposta válida e é o ack de
        botão mais comum que existe; recusar obrigaria a mandar `content`
        fake só para o Discord não reclamar.

        Só em componente, e só antes de qualquer resposta: o `defer()`
        já teria virado um "pensando…" na tela, e trocar esse "pensando"
        por uma mensagem nova não é o que `update` faz.
        """
        if not self._interaction.is_message_component():
            raise InteractionStateError(
                "update() só existe em interação de componente — não há mensagem a "
                "substituir num comando. Use reply() ou defer()."
            )
        self._exige("update")
        await self._api.update_message(self._interaction, content, **kwargs)
        self._state = _TRANSICOES[self._state]["update"]  # type: ignore[assignment]

    async def ack(self) -> None:
        """Garante que a interação foi acknowledge.

        Idempotente: em `UNANSWERED` faz um defer implícito; nos demais
        estados é no-op. Reclamar que já foi respondido seria dizer que
        o chamador errou por ter atingido o objetivo.
        """
        destino = _TRANSICOES[self._state]["ack"]
        if destino is self._state:
            return
        await self.defer()

    async def send_modal(self, modal: Any) -> None:
        """Abre um modal — **terminal**.

        Permitido a partir de `UNANSWERED` e `DEFERRED`: o Discord
        aceita modal como resposta inicial de comando e de componente.
        A partir de `ANSWERED` é erro — já existe mensagem na tela, e
        um modal em cima dela não tem como ser editado depois.
        """
        self._exige("send_modal")
        await self._api.show_modal(self._interaction, modal)
        self._state = _TRANSICOES[self._state]["send_modal"]  # type: ignore[assignment]

    async def launch_activity(self) -> None:
        """Abre a atividade do app no canal da interação.

        Resposta inicial como outra qualquer — depois dela, a máquina
        está em `ANSWERED` e só `edit`/`delete`/`follow_up` restam.

        Exige atividade habilitada no Developer Portal; sem ela, o
        `callback` é aceito e nada acontece. O método existe porque é
        um tipo de resposta do Discord (`12`) e custa uma linha —
        testá-lo de ponta a ponta exigiria atividade no bot de teste
        (0023, divergência preservada).
        """
        self._exige("launch_activity")
        await self._api.launch_activity(self._interaction)
        self._state = _TRANSICOES[self._state]["launch_activity"]  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Depois da resposta
    # ------------------------------------------------------------------

    async def edit(
        self,
        content: str | None = None,
        *,
        message_id: str | int = "@original",
        **kwargs: Any,
    ) -> None:
        """Edita uma mensagem desta interação. Padrão: a original.

        Possível de `DEFERRED` e `ANSWERED` — o defer existe justamente
        para ser editado.

        `message_id` alcança um follow-up; `@original` é o que quase
        todo código quer, e é o default porque errar o alvo é mais
        caro que digitar de menos.
        """
        self._exige("edit")
        await self._api.edit_message(
            self._interaction.application_id,
            self._interaction.token,
            message_id,
            content,
            **kwargs,
        )
        self._state = _TRANSICOES[self._state]["edit"]  # type: ignore[assignment]

    async def delete(self, *, message_id: str | int = "@original") -> None:
        """Apaga uma mensagem desta interação. Padrão: a original."""
        self._exige("edit")
        await self._api.delete_message(
            self._interaction.application_id, self._interaction.token, message_id
        )

    async def fetch_reply(self, *, message_id: str | int = "@original") -> Any:
        """Busca uma mensagem desta interação. Padrão: a original.

        `None` quando ainda não existe — um defer nunca editado é um
        "pensando…" que o Discord não devolve como mensagem. Não é
        erro: é "ainda não há o que buscar".
        """
        return await self._api.fetch_message(
            self._interaction.application_id, self._interaction.token, message_id
        )

    async def follow_up(self, content: str | None = None, **kwargs: Any) -> Any:
        """Envia uma mensagem adicional — não é a resposta inicial.

        Disponível de qualquer estado, inclusive `UNANSWERED`? **Não**:
        o Discord recusa follow-up antes da resposta inicial, porque o
        follow-up referencia a resposta original.
        """
        if self._state is InteractionState.UNANSWERED:
            raise InteractionStateError(
                "follow_up() antes da resposta inicial — o follow-up referencia a "
                "resposta original, que ainda não existe. Responda ou defera primeiro."
            )
        return await self._api.followup(
            self._interaction.application_id,
            self._interaction.token,
            content,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _exige(self, acao: str) -> None:
        """Levanta se a ação não é permitida do estado atual.

        A mensagem cita o estado, a ação e a saída possível — sem isso,
        "inválido" obriga a ler a máquina inteira. `UNANSWERED` precisa
        da sua entrada: sem ela, a própria mensagem de erro virava um
        `KeyError`, mascarando o problema real.
        """
        if _TRANSICOES[self._state].get(acao) is not None:
            return

        sae = {
            InteractionState.UNANSWERED: (
                "ainda não houve resposta — use reply() ou defer() antes"
            ),
            InteractionState.ANSWERED: "responda com edit() ou delete(), ou use follow_up()",
            InteractionState.DEFERRED: "finalize com edit(), ou use follow_up()",
            InteractionState.MODAL: "um modal é terminal — não há mais resposta nesta interação",
        }[self._state]

        raise InteractionStateError(f"{acao}() não é permitido depois de {self._state.name}; {sae}")
