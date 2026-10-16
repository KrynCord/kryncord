"""Instância registrada de um comando.

`CommandInstance` é o que o usuário encadeia — `.sub()`, `.group()`,
`.autocomplete()` — e o que o dispatcher busca. `CommandDefinition` é a
propriedade `.definition`: o dado que vai ao Discord.

A separação existe porque a instância tem que existir **antes** da
definição estar completa. Um comando com subcomandos é declarado em
várias linhas, e cada uma acrescenta; só no fim a definição fecha.
Recalculá-la a cada declaração é O(n) no import, que é o custo certo —
a alternativa seria guardar estado parcial e descobrir tarde.

`run` é o contrato de transporte de dados (`0022`): devolve algo, e o
dispatcher injeta no subcommand. Não há um segundo mecanismo.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from kryncord.commands.definition import CommandDefinition
from kryncord.commands.option import Option
from kryncord.enums import ApplicationCommandType
from kryncord.errors import CommandDefinitionError

#: Handler aceito pelo decorator. `*args` é permitido (`K9`); a
#: sincronicidade é que é obrigatória, e é checada no registro.
Handler = Callable[..., Any]


class CommandInstance:
    """Um comando registrado, com seu handler e seus subcomandos."""

    __slots__ = (
        "_autocomplete",
        "_base_options",
        "_deferido",
        "_definition",
        "_escopos",
        "_groups",
        "_grupo_descricoes",
        "_grupo_handlers",
        "_handler",
        "_middleware",
        "_on_error",
        "_subcommands",
    )

    def __init__(
        self,
        definition: CommandDefinition,
        handler: Handler | None = None,
    ) -> None:
        self._definition = definition
        #: As `options` declaradas **na construção**. `_rebuild` parte
        #: delas, não das atuais — senão os subcomandos sintetizados da
        #: rebuild anterior sobreviveriam e seriam reacrescentados, e
        #: cada nova declaração duplicaria o grupo.
        self._base_options: tuple[Option, ...] = definition.options
        #: `None` é a âncora legítima: o `command.py` raiz pode ser só
        #: um lugar onde os filhos se penduram (ideia 04 §6). Nesse caso
        #: não há valor a injetar, e o filho recebe `None` — que é o que
        #: faz o `DispatchError` dizer "anotava StoreData, recebui
        #: NoneType" em vez de "missing 1 required positional argument".
        self._handler = handler
        #: nome → handler do **grupo** (não do subcomando). Guardado por
        #: instância e não no `_Grupo` porque `.group()` pode ser
        #: chamado de dois módulos para o mesmo nome, e o `_Grupo` é
        #: criado a cada chamada.
        self._grupo_handlers: dict[str, Handler] = {}
        #: nome → handler, para subcomando de primeiro nível
        self._subcommands: dict[str, Handler] = {}
        #: grupo → {subcomando → handler}
        self._groups: dict[str, dict[str, Handler]] = {}
        #: grupo → descrição declarada. Por instância: no módulo seria
        #: compartilhada entre todos os comandos, e o grupo de um
        #: comando apareceria na descrição do outro.
        self._grupo_descricoes: dict[str, str] = {}
        #: opção → função; `"*"` é a genérica
        self._autocomplete: dict[str, Handler] = {}
        self._middleware: tuple[Any, ...] = ()
        self._on_error: Handler | None = None
        #: Os escopos que esta instância ocupa no registry (`0026` §2):
        #: `guild=(123, 456)` são duas chaves apontando para **este**
        #: objeto. O `definition.scope` é o primeiro deles.
        self._escopos: tuple[int | None, ...] = (definition.scope,)
        #: Se o decorator não declarou escopo nenhum, e o default vem do
        #: `Config(commands=...)` no `start()` (`0028` §2). Registrado
        #: no global de qualquer forma — é o default, e é o que faz o
        #: `reescopiar` ser no-op para quem nunca configurou nada.
        self._deferido = False

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    @property
    def definition(self) -> CommandDefinition:
        """A definição completa, já com os subcomandos serializados."""
        return self._definition

    @property
    def name(self) -> str:
        return self._definition.name

    @property
    def type(self) -> ApplicationCommandType:
        return self._definition.type

    @property
    def scope(self) -> int | None:
        return self._definition.scope

    @property
    def handler(self) -> Handler | None:
        """O handler da **raiz**, ou `None` quando é só âncora.

        Não confundir com o de um grupo: `grupo_handler(nome)` é o que
        roda no nível do grupo, e o da raiz roda antes, devolvendo o
        valor que o resto recebe (ideia 04 §4).
        """
        return self._handler

    @property
    def subcommands(self) -> Mapping[str, Handler]:
        return self._subcommands

    @property
    def groups(self) -> Mapping[str, Mapping[str, Handler]]:
        return self._groups

    @property
    def autocomplete_handlers(self) -> Mapping[str, Handler]:
        return self._autocomplete

    @property
    def middleware(self) -> tuple[Any, ...]:
        """Middleware declarada no decorator — concatenada **depois** da
        global (`0026` §10: global primeiro, depois o da entrada)."""
        return self._middleware

    @property
    def on_error(self) -> Handler | None:
        """O `on_error` declarado **neste comando**, ou `None`.

        O despacho o prefere ao do `Options` e herda o `Options` quando
        ele é `None` (`0030` §1) — a mesma relação de prioridade da
        middleware local sobre a global (`0017`).

        Não tem `on_not_found` correspondente: uma instância só existe
        se o nome dela for conhecido, e "este nome não existe" é
        pergunta que só o `Options` consegue responder (`0030` §2).
        """
        return self._on_error

    @property
    def escopos(self) -> tuple[int | None, ...]:
        """Todos os escopos desta instância, em ordem de registro."""
        return self._escopos

    @property
    def deferido(self) -> bool:
        """Se o decorator deixou o escopo por conta do `Config` (`0028`)."""
        return self._deferido

    def grupo_handler(self, name: str) -> Handler | None:
        """O handler do **grupo**, ou `None` quando não tem.

        Sem handler de grupo, o valor do comando pai vai direto ao
        subcomando (ideia 04 §4) — é o caso de um grupo que existe só
        para organizar a árvore no Discord.
        """
        return self._grupo_handlers.get(name)

    def __call__(self, fn: Handler | None = None) -> Any:
        """A instância também é decorator (ideia 04 §2).

        As duas formas, e as duas são comuns o suficiente para valer:

        ```python
        @command_instance()
        async def run(ctx): ...

        @command_instance
        async def run(ctx): ...
        ```

        `fn=None` é o caso dos parênteses vazios — o decorator chega
        depois. Devolve a **função original**, mesmo critério do
        `@command` (`0026` §1): trocar o objeto da função quebraria
        `@staticmethod`, `wraps` e teste que inspeciona.
        """

        def decorador(alvo: Handler) -> Handler:
            _exige_assincrono(alvo, f"handler do comando {self.name!r}")
            self._handler = alvo
            self._rebuild()
            return alvo

        if fn is None:
            return decorador
        return decorador(fn)

    async def run(self, ctx: Any, valor: Any = None) -> Any:
        """Executa **este nível** e devolve o valor (`0022`).

        A raiz não recebe valor de ninguém — é o começo da cadeia. Por
        isso `run(ctx)` chama o handler com `ctx` só, mesmo quando a
        assinatura dele declara dois parâmetros: um parâmetro que a
        cadeia nunca preenche é erro de declaração, e o `TypeError` do
        `await` aponta exatamente para ele.

        `valor` existe para compatibilidade de quem chama o nível de
        forma uniforme; na raiz ele é ignorado, e é **isso** que
        distingue este método do `_Grupo.run`.
        """
        if self._handler is None:
            return None
        return await self._handler(ctx)

    # ------------------------------------------------------------------
    # Encadeamento declarativo
    # ------------------------------------------------------------------

    def sub(self, name: str, handler: Handler, *, description: str = "") -> CommandInstance:
        """Subcommand direto, sem grupo."""
        self._require_chat_input("sub")
        if name in self._subcommands:
            raise CommandDefinitionError(f"comando {self.name!r}: subcomando {name!r} duplicado")
        self._subcommands[name] = handler
        self._rebuild()
        return self

    def group(self, name: str, description: str = "", **subs: Handler) -> _Grupo:
        """Grupo de subcomandos, com os subcomandos já declarados.

        ```python
        @command("papel")
        async def _(ctx): ...

        _.group("papel", add=adicionar, remove=remover)
        ```

        `description` é a do grupo; a de cada subcomando vem do
        docstring do respectivo handler.
        """
        self._require_chat_input("group")
        if name in self._subcommands:
            raise CommandDefinitionError(
                f"comando {self.name!r}: {name!r} já é subcommand; não pode virar grupo"
            )
        if name in self._groups:
            raise CommandDefinitionError(f"comando {self.name!r}: grupo {name!r} repetido")

        self._groups[name] = dict(subs)
        self._grupo_descricoes[name] = description
        self._rebuild()
        return _Grupo(self, name)

    def autocomplete(self, option_name: str = "*") -> Callable[[Handler], Handler]:
        """Registra a função de autocomplete de uma opção.

        `option_name` aponta para uma opção específica; `"*"` é a
        genérica, que responde qualquer opção sem função própria. Duas
        funções para a mesma opção são erro (`0021`) — dois autores
        brigando por uma opção, e o perdedor não saberia.
        """

        def decorator(fn: Handler) -> Handler:
            if option_name in self._autocomplete:
                raise CommandDefinitionError(
                    f"comando {self.name!r}: autocomplete para {option_name!r} já registrado"
                )
            self._autocomplete[option_name] = fn
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _require_chat_input(self, acao: str) -> None:
        """USER e MESSAGE não têm estrutura — o alvo vem do clique.

        Deixar `.sub()` funcionar e falhar só no sync seria descobrir
        tarde e sem dizer qual linha.
        """
        if self._definition.type is not ApplicationCommandType.CHAT_INPUT:
            raise CommandDefinitionError(
                f"comando {self.name!r}: {acao}() só existe em CHAT_INPUT; "
                f"{self._definition.type.name} não tem opções"
            )

    def _registra_sub_em_grupo(self, grupo: str, name: str, handler: Handler) -> None:
        subs = self._groups.setdefault(grupo, {})
        if name in subs:
            raise CommandDefinitionError(
                f"comando {self.name!r}: subcomando {name!r} duplicado no grupo {grupo!r}"
            )
        subs[name] = handler
        self._rebuild()

    def _rebuild(self) -> None:
        """Serializa os subcomandos declarados nas `options` da
        definição. Chamado a cada declaração — só acontece no import.

        Parte sempre de `_base_options`, nunca das atuais: as atuais já
        contêm o sintetizado da declaração anterior, e somar seria
        duplicar o grupo a cada `.add()`."""
        options: list[Option] = [o for o in self._base_options]

        for nome, handler in self._subcommands.items():
            options.append(Option.sub_command(nome, _doc(handler)))

        for nome, subs in self._groups.items():
            grupo_handler = self._grupo_handlers.get(nome)
            options.append(
                Option.group(
                    nome,
                    self._grupo_descricoes.get(nome) or _doc(grupo_handler),
                    options=tuple(Option.sub_command(s, _doc(h)) for s, h in subs.items()),
                )
            )

        d = self._definition
        self._definition = CommandDefinition(
            name=d.name,
            description=d.description,
            type=d.type,
            scope=d.scope,
            options=tuple(options),
            default_member_permissions=d.default_member_permissions,
            dm_permission=d.dm_permission,
            nsfw=d.nsfw,
            name_localizations=d.name_localizations,
            description_localizations=d.description_localizations,
        )


def _doc(handler: Handler | None) -> str:
    """Descrição vem da primeira linha do docstring do handler.

    É o lugar onde ela já está escrita — pedir duas vezes é garantia
    de que as duas vão divergir. Cortada em 100, o máximo do Discord.

    `None` é a âncora sem handler, e devolve `""` — sem este guarda, o
    `getattr(None, "__doc__")` devolveria o docstring do `NoneType`,
    que apareceria como descrição do grupo no Discord.
    """
    if handler is None:
        return ""
    doc = (getattr(handler, "__doc__", None) or "").strip()
    return doc.splitlines()[0].strip()[:100] if doc else ""


class _Grupo:
    """Retorno de `.group()`, que aceita `.add()` e o handler do grupo."""

    __slots__ = ("_instancia", "_nome")

    def __init__(self, instancia: CommandInstance, nome: str) -> None:
        self._instancia = instancia
        self._nome = nome

    def add(self, name: str, handler: Handler) -> _Grupo:
        """Acrescenta um subcomando ao grupo."""
        self._instancia._registra_sub_em_grupo(self._nome, name, handler)
        return self

    @property
    def name(self) -> str:
        return self._nome

    def handler(self, fn: Handler) -> Handler:
        """Registra o handler do **grupo** — a forma imperativa.

        A forma decorator (`@grupo`) chama isto; os dois são o mesmo
        registro, e o grupo é um só por nome, porque o Discord tem um.
        """
        _exige_assincrono(fn, f"handler do grupo {self._nome!r}")
        if self._nome in self._instancia._grupo_handlers:
            raise CommandDefinitionError(
                f"comando {self._instancia.name!r}: grupo {self._nome!r} já "
                "tem handler — dois handlers brigando por um grupo, e o "
                "perdedor não saberia"
            )
        self._instancia._grupo_handlers[self._nome] = fn
        self._instancia._rebuild()
        return fn

    def __call__(self, fn: Handler) -> Handler:
        """`@grupo` — registra o handler do grupo (ideia 04 §4)."""
        return self.handler(fn)

    async def run(self, ctx: Any, valor: Any = None) -> Any:
        """Executa **este nível** injetando o valor do nível acima.

        É o meio da cadeia `command.run(ctx) -> grupo.run(ctx, valor) ->
        sub.run(ctx, valor)` (`0022`). Sem handler registrado devolve o
        valor recebido — o grupo que existe só para organizar a árvore
        não pode ser o lugar onde o dado morre.

        A injeção passa pelo mesmo `_injeta` do despacho, por import
        adiado: é a mesma checagem de anotação, e reimplementar aqui
        faria os dois caminhos divergirem — um aceitando tipo que o
        outro recusa, dependendo de por onde o grupo foi chamado.
        """
        handler = self._instancia._grupo_handlers.get(self._nome)
        if handler is None:
            return valor

        from kryncord.commands.dispatch import _injeta

        return await _injeta(handler, ctx, valor, f"grupo {self._nome!r}")


def _exige_assincrono(fn: Any, onde: str) -> None:
    """`TypeError` no registro, não no clique (`0010`).

    A mesma regra dos eventos: `await` de uma função síncrona falha
    alto, e o sintoma (handler que nunca roda) é dos piores de
    diagnosticar — mas só depois do bot estar no ar.
    """
    if inspect.iscoroutinefunction(fn):
        return
    try:
        if inspect.iscoroutinefunction(fn.__call__):
            return
    except AttributeError:
        pass
    raise TypeError(
        f"{onde} tem que ser `async def`. Recebi {fn!r}. Função síncrona "
        "bloquearia o event loop dentro do despacho."
    )
