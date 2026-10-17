"""Configuração da KrynCord.

A configuração é imutável depois de construída: um `Config` válido no
início da aplicação não muda embaixo do pé do `Client`. Se algo precisar
mudar, constrói-se um `Config` novo.

Todos os campos têm default seguro. Nenhum exige que o usuário saiba o
que é um bucket de rate limit para conseguir ligar um bot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from kryncord.cache.policy import CachePolicy
from kryncord.intents import Intents
from kryncord.permissions import parse_permissions_list

#: Assinatura de qualquer middleware. O `block` é sempre o segundo
#: parâmetro — nas três categorias, sem exceção. Middleware assíncrona
#: é obrigatória; uma função síncrona aqui é erro no registro.
Middleware = Callable[[Any, Any], Awaitable[None]]

#: `on_error` recebe o contexto e a exceção. O default é do `0017`.
ErrorHandler = Callable[[Any, BaseException], Awaitable[None]]
"""`(ctx, error)` — o `on_error` das três categorias (`0017`)."""

NotFoundHandler = Callable[[Any], Awaitable[None]]
"""`(ctx)` — o `on_not_found` dos dois `Options` (`0029`).`

Um argumento só, porque não há erro a passar: `on_not_found` é
"ninguém atendeu", e o segundo parâmetro de uma assinatura de dois
seria sempre `None` — um parâmetro sem leitor.
"""


@dataclass(frozen=True, slots=True)
class CommandOptions:
    """Defaults aplicados a todos os comandos registrados.

    O decorator ainda pode sobrescrever middleware, `on_error` e
    `on_not_found` — estes são os defaults, não os valores finais.
    """

    default_member_permissions: Any = None
    """Restrição padrão de permissão, em qualquer forma aceita: nome
    (`"MANAGE_GUILD"`), número (`1 << 5`), `Permissions`, ou sequência
    delas. `None` é "sem restrição" — diferente de `Permissions(0)`,
    que seria "ninguém".
    """
    guilds: tuple[int, ...] = ()
    """Escopo padrão de quem não declarou `is_global` nem `guild=`.

    Vazio é global. É o `K1` que decide aqui: o decorator `guild=`
    continua existindo, e este campo é só o default de quem não usou.
    """
    middleware: Middleware | None = None
    on_error: ErrorHandler | None = None
    on_not_found: NotFoundHandler | None = None
    verbose: bool = False
    """Imprime as linhas do `SyncReport`. Independente de `load_logs`,
    que é do `bootstrap` — perguntas diferentes.
    """

    _resolved: Any = field(default=None, init=False, repr=False, compare=False)
    """Permissão já convertida, guardada no construto — para o `sync`
    não reparsear a mesma lista em cada comando. Não-declarável como
    atributo comum porque o dataclass é `slots=True`."""

    def __post_init__(self) -> None:
        # Validação na construção, não no sync: o erro tem que aparecer
        # na linha do `Config(...)`, com o nome do campo.
        object.__setattr__(
            self,
            "_resolved",
            parse_permissions_list(
                self.default_member_permissions,
                where="commands.default_member_permissions",
            ),
        )
        object.__setattr__(self, "guilds", tuple(int(g) for g in self.guilds))

    @property
    def default_member_permissions_resolved(self) -> Any:
        """A permissão já convertida, ou `None` para "sem restrição"."""
        return self._resolved


@dataclass(frozen=True, slots=True)
class ResponderOptions:
    """Defaults para responders de componente, modal e autocomplete."""

    middleware: Middleware | None = None
    on_error: ErrorHandler | None = None
    on_not_found: NotFoundHandler | None = None


@dataclass(frozen=True, slots=True)
class EventOptions:
    """Defaults para handlers de evento."""

    middleware: Middleware | None = None
    on_error: ErrorHandler | None = None
    dispatch_mode: Literal["sequential", "concurrent"] = "sequential"
    """Como os handlers de um evento rodam entre si.

    `sequential` em ordem de registro — é o default porque é o único
    modo em que a ordem significa algo para quem escreve o bot, e o
    `args` mutável do `EventFrame` só funciona aqui.

    `concurrent` despacha num `TaskGroup` e espera todos: handlers
    independentes pagam latência só uma vez. O cancelamento no shutdown
    alcança as tasks porque o `TaskGroup` é filho do despacho.
    """

    def __post_init__(self) -> None:
        if self.dispatch_mode not in ("sequential", "concurrent"):
            raise ValueError(
                "events.dispatch_mode precisa ser 'sequential' ou "
                f"'concurrent', recebido {self.dispatch_mode!r}"
            )


@dataclass(frozen=True, slots=True)
class HTTPConfig:
    """Ajustes da camada REST.

    `timeout` cobre a operação inteira (conexão + envio + leitura do
    corpo). Rate limits são tratados separadamente, pelo `BucketManager`.
    """

    base_url: str = "https://discord.com/api"
    version: int = 10
    """Versão da API. Entra na URL como ``/v10``, exceto em requisições
    marcadas ``versioned=False`` (endpoints de OAuth)."""
    timeout: float = 30.0
    max_retries: int = 3
    max_connections: int = 100
    max_keepalive_connections: int = 20
    """Conexões mantidas vivas entre requisições."""
    offset_ms: float = 50
    """Folga somada a todo reset de rate limit. Chegar exatamente no
    instante do reset é apertado demais."""
    global_requests_per_second: int = 50
    """Teto client-side do limite global. O Discord não publica o dele;
    50/s é o valor que a comunidade observou sem levar 429."""
    user_agent_appendix: str = ""
    """Texto extra no fim do ``User-Agent`` — biblioteca de cima pode
    se identificar aqui."""


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Ajustes da camada Gateway."""

    connect_timeout: float = 30.0
    """Tempo para o socket abrir (TCP + TLS + upgrade)."""
    hello_timeout: float = 60.0
    """Tempo para o primeiro frame (`HELLO`) depois de a conexão abrir.
    Passou disso, o Discord não vai falar — reconectar é mais barato
    do que esperar um `recv()` que nunca volta."""
    ready_timeout: float = 15.0
    """Tempo entre mandar Identify/Resume e receber `READY`/`RESUMED`.
    Sem isto, um servidor que aceita a conexão e fica calado deixaria o
    bot "ligado" para sempre sem estar pronto — e o heartbeat seguiria
    batindo, mascarando o problema."""
    heartbeat_interval: float | None = None
    """`None` usa o valor que o Discord manda no `HELLO`. Só sobrescreva
    em teste — em produção, adiantar ou atrasar o batimento é a forma
    mais rápida de ser derrubado por "zumbi"."""
    identify_timeout: float = 10.0
    resume_timeout: float = 10.0
    max_reconnect_attempts: int | None = 5
    """Falhas **consecutivas** antes de desistir e levantar
    `GatewayError`. Chegar ao `READY` zera o contador — o limite existe
    para não girar sozinho quando o token está errado, não para punir um
    bot que já funcionou. `None` tenta para sempre. Backoff exponencial
    com jitter entre as tentativas."""
    invalid_session_wait: tuple[float, float] = (1.0, 5.0)
    """Intervalo (mínimo, máximo) que o Discord manda esperar entre um
    `invalid_session` e a reconexão. Sorteado dentro da faixa para que
    várias shards caídas ao mesmo tempo não voltem em fila indiana."""


@dataclass(frozen=True, slots=True)
class Config:
    """Configuração raiz da KrynCord."""

    intents: Intents
    token: str = ""
    """Token do bot, do painel de desenvolvedor do Discord.

    Vazio é válido na construção e **não** no `Client.start()`: um
    `Config` é uma declaração de intenções, e nem toda declaração é uma
    aplicação que conecta. Falhar no `start()` dá a mensagem certa no
    lugar certo, sem exigir que quem só quer testar `Config` invente um
    token.

    Nunca comente o token no código. Ele vai em variável de ambiente.
    """
    enabled_intents: Intents = field(default_factory=Intents.all_non_privileged)
    """Intents que o portal concede.

    É o que a aplicação **pode** pedir, não o que pede. O `Client` valida
    `intents` contra isto no `start()` — assim um intent privileged
    esquecido falha no boot, e não depois de um Identify rejeitado.

    O default é conservador: nenhum privileged, porque ativar no portal é
    uma ação manual que ninguém faz sem querer.
    """
    http: HTTPConfig = field(default_factory=HTTPConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    cache: CachePolicy = field(default_factory=CachePolicy)
    """Política do cache local.

    Ligada por padrão, com os quatro tipos que o próprio gateway
    invalida sozinho. `members` e `messages` são opt-in por serem os
    dois que crescem com o servidor — e porque ninguém quer um bot que
    guarda cem mil objetos sem ter pedido. `CachePolicy.disabled()` é o
    caminho de zero memória; `CachePolicy.full()` é o de tudo, com teto.

    Trocar a política depois de ligar não desfaz o que já entrou:
    construa o `Config` novo e o `Client` novo junto.
    """
    log_level: str = "INFO"
    """Nível do logger `kryncord`. Vira um filtro, não configura o root."""
    commands: CommandOptions = field(default_factory=CommandOptions)
    """Defaults de comandos. `K10`/`K1` moram aqui."""
    responders: ResponderOptions = field(default_factory=ResponderOptions)
    """Defaults de responders."""
    events: EventOptions = field(default_factory=EventOptions)
    """Defaults de eventos, incluindo o `dispatch_mode`."""

    def __post_init__(self) -> None:
        _require_positive("http.timeout", self.http.timeout)
        _require_positive("gateway.connect_timeout", self.gateway.connect_timeout)
        _require_positive("gateway.hello_timeout", self.gateway.hello_timeout)
        _require_positive("gateway.ready_timeout", self.gateway.ready_timeout)
        _require_positive("gateway.identify_timeout", self.gateway.identify_timeout)
        _require_positive("gateway.resume_timeout", self.gateway.resume_timeout)
        if self.gateway.heartbeat_interval is not None:
            _require_positive("gateway.heartbeat_interval", self.gateway.heartbeat_interval)

        # Contagens, não durações: zero é uma escolha válida (desliga a
        # feature), então só o sinal negativo é erro.
        _require_non_negative("http.max_retries", self.http.max_retries)
        if self.gateway.max_reconnect_attempts is not None:
            _require_non_negative(
                "gateway.max_reconnect_attempts", self.gateway.max_reconnect_attempts
            )

        minimum, maximum = self.gateway.invalid_session_wait
        if minimum < 0 or maximum < minimum:
            raise ValueError(
                "gateway.invalid_session_wait deve ser (mínimo, máximo) com "
                f"mínimo >= 0 e máximo >= mínimo, recebido "
                f"{self.gateway.invalid_session_wait}"
            )

        if self.http.max_keepalive_connections > self.http.max_connections:
            raise ValueError(
                "http.max_keepalive_connections "
                f"({self.http.max_keepalive_connections}) não pode ser maior que "
                f"http.max_connections ({self.http.max_connections})"
            )


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} precisa ser positivo, recebido {value}")


def _require_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} não pode ser negativo, recebido {value}")
