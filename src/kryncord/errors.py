"""Hierarquia de erros da KrynCord.

Regra: toda falha que o usuário precisa tratar tem exceção própria e
mensagem acionável. Nada de `Exception` genérica escapando para fora da
biblioteca.

Hierarquia::

    KrynCordError
    ├── DefinitionError          erro no código do usuário, na importação
    │   ├── CommandDefinitionError
    │   ├── ResponderDefinitionError
    │   └── EventDefinitionError
    ├── HTTPError                falha na camada REST
    │   ├── RateLimitError
    │   └── DiscordAPIError
    └── GatewayError             falha na camada Gateway
"""

from __future__ import annotations


class KrynCordError(Exception):
    """Raiz de toda exceção levantada pela KrynCord."""


# --------------------------------------------------------------------------
# Definição — erro no código do usuário, detectado na importação
# --------------------------------------------------------------------------


class DefinitionError(KrynCordError):
    """Uma definição (comando, responder, evento) é inválida.

    Levantado no momento da importação do módulo, nunca durante o dispatch.
    """


class CommandDefinitionError(DefinitionError):
    """Definição de comando de aplicação inválida."""


class ResponderDefinitionError(DefinitionError):
    """Definição de responder (rota de custom_id) inválida."""


class EventDefinitionError(DefinitionError):
    """Definição de handler de evento inválida."""


class HandlerSignatureError(DefinitionError):
    """A assinatura do handler não bate com o tipo de interação.

    `@command` e os decorators de componente entregam uma classe
    determinística — `CommandInteraction` para `/ping`, `ButtonInteraction`
    para um clique (`0031`). O primeiro parâmetro anotado tem que ser
    essa classe (ou uma filha); anotar outro tipo é erro **na
    importação**, porque no clique a anotação mentira e o handler leria
    um atributo que não existe.

    Fora da hierarquia de `DefinitionError`? Não — é erro de definição,
    detectado no registro, e `except DefinitionError` tem que pegá-lo.
    """


# --------------------------------------------------------------------------
# REST
# --------------------------------------------------------------------------


class HTTPError(KrynCordError):
    """Falha na camada HTTP, antes de interpretar a resposta do Discord."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        failure_kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.failure_kind = failure_kind
        """``not_sent`` | ``ambiguous`` | ``server_error`` | ... — o que
        `http.retries` usa para decidir se tenta de novo. Pode ser `None`
        quando a falha não veio do transporte."""


class RateLimitError(HTTPError):
    """O Discord respondeu 429 e a espera não foi possível ou foi excedida."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float,
        global_limit: bool = False,
        bucket: str | None = None,
    ) -> None:
        super().__init__(message, status=429)
        self.retry_after = retry_after
        self.global_limit = global_limit
        self.bucket = bucket


class DiscordAPIError(HTTPError):
    """O Discord respondeu com um erro de API (4xx ou 5xx interpretado)."""

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: int | None = None,
        errors: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, status=status)
        self.code = code
        self.errors = errors or {}


# --------------------------------------------------------------------------
# Gateway
# --------------------------------------------------------------------------


class GatewayError(KrynCordError):
    """Falha na conexão ou no protocolo do Gateway."""


class SessionInvalidError(GatewayError):
    """O Discord recusou o resume; é preciso um Identify novo."""


class ConnectionClosedError(GatewayError):
    """A conexão WebSocket caiu. Carrega o código de fechamento.

    `code` é o código WebSocket recebido. `None` quando o socket morreu
    sem mandar frame de fechamento (corte de rede) — nesse caso o
    `reconnect.classify_close` decide pelo flag de erro de rede.
    """

    def __init__(self, message: str, *, code: int | None = None, reason: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


class FatalGatewayError(GatewayError):
    """Falha que não se recupera: não adianta reconectar.

    Token inválido (4004), intents errados (4013/4014), shard inválida
    (4010). Levantado no boot — o processo deve morrer com uma mensagem
    dizendo o que corrigir, porque tentar de novo só gasta o rate limit
    do Gateway até o Discord nos bloquear.
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MemberRequestError(GatewayError):
    """Falha num pedido de membros (op 8). Base da família."""


class MemberRequestTimeout(MemberRequestError):
    """O Discord não mandou chunk dentro do prazo (120s por padrão).

    O prazo renova a cada chunk recebido, então o que esgota é um
    pedido que parou de andar — não um servidor grande demais.
    """


class MemberRequestRateLimited(MemberRequestError):
    """O Gateway recusou o pedido (dispatch `RATE_LIMITED`) com um
    `retry_after` em segundos — o mesmo campo do REST."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TooManyMemberRequests(MemberRequestError):
    """Teto de pedidos de membros simultâneos estourado.

    O discord.js não tem teto (só incrementa max-listeners); aqui ele
    existe para o erro sair na cara de quem chamou, e não virar fila de
    futuros que ninguém consome.
    """


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


class LifecycleError(KrynCordError, RuntimeError):
    """Falha no ciclo de vida: spawn fora do contexto, reuso indevido.

    Herda de `RuntimeError` também, de propósito: `Client.start()`
    sempre levantou `RuntimeError` por reuso indevido, e quebrar quem já
    captura esse tipo seria trocar uma mensagem melhor por um
    incompatibilidade. Quem quer o caso específico captura
    `LifecycleError`; quem só quer o genérico continua funcionando.
    """


# --------------------------------------------------------------------------
# Despacho — 0017
# --------------------------------------------------------------------------


class DispatchError(KrynCordError):
    """Falha durante o despacho de um comando, responder ou evento."""


class BlockHandlers(DispatchError):
    """`block()` chamado por middleware — o tratamento foi assumido ali.

    A **única** exceção controlada do despacho: o dispatcher a captura
    antes de chegar ao `on_error`, porque quem chamou `block()` não errou
    — decidiu. Levantar isto fora de middleware é erro, e vira
    `on_error` como qualquer outro.

    `tags` é o filtro de eventos: `block()` sem argumentos tira todos os
    handlers, `block("morning")` tira só os que têm alguma daquela tag
    (`ideia 10` §4, `0017`). Comandos e responders não têm tags na 1.0,
    então lá o argumento é sempre vazio e o efeito é "bloqueia tudo" —
    que é o mesmo comportamento, por não haver o que filtrar.
    """

    #: As tags que o chamador pediu para bloquear. Pode ser vazio.
    tags: tuple[str, ...]

    def __init__(self, tags: tuple[str, ...] = ()) -> None:
        super().__init__(tags)
        self.tags = tuple(tags)


class ConversionError(DispatchError):
    """Um conversor de parâmetro falhou.

    Dentro de `DispatchError` porque é falha de despacho: a definição
    estava certa, é o valor que não converteu.
    """


class ComponentError(KrynCordError):
    """Montagem de componente inválida.

    Fora de `DispatchError` de propósito: montar componente não é
    despacho, e `except DispatchError` não deveria pegá-lo.

    A mensagem carrega o caminho (`rows[2].components[3]`) — sem ele, o
    erro diz "inválido" e o usuário lê a tela inteira procurando.
    """


class InvalidInteractionState(KrynCordError):
    """Transição inválida na máquina de estados da resposta.

    Não é `DispatchError`: o despacho funcionou, é o código que chamou
    `respond()` depois de já ter respondido — ou com o token já
    expirado. Escapa do `on_error` de propósito — é um bug de uso, não
    uma falha a ser tratada.
    """


class InteractionTimeoutError(KrynCordError):
    """Token da interação expirou — 15 minutos.

    É o que o `on_error` default pega para **não** tentar responder de
    novo, que falharia com 400 e mascararia o erro real.
    """
