"""Registry de comandos.

A chave é `(type, name, scope)` — três pontas, não duas. Um menu USER
chamado `ping` e o slash `/ping` são dois comandos distintos no
Discord; numa chave de duas pontas o segundo registro seria recusado
como duplicata.

`scope` é `int | None`, `None` sendo o global. Não há value object: é
o que a URL e o payload já usam, e um objeto aqui teria que ser
traduzido de volta na hora de montar a rota.

Registro duplicado tem dois comportamentos diferentes, e a fronteira é
a comparação do payload:

| Situação | Comportamento |
|---|---|
| Mesma chave, payload igual | Devolve a instância já registrada, silenciosamente |
| Mesma chave, payload diferente | `CommandDefinitionError` citando os dois módulos |

O primeiro caso é o caminho normal — `bootstrap` importa o módulo e o
usuário também importou direto. O segundo é dois módulos brigando pelo
mesmo nome, e sem citar os dois locais o erro não diz onde procurar.
"""

from __future__ import annotations

from collections.abc import Iterator

from kryncord.commands.definition import CommandDefinition
from kryncord.commands.instance import CommandInstance
from kryncord.enums import ApplicationCommandType
from kryncord.errors import CommandDefinitionError

#: `(type, name, scope)`. Três pontas — ver docstring.
CommandKey = tuple[ApplicationCommandType, str, int | None]


class CommandRegistry:
    """Armazena e busca comandos registrados."""

    __slots__ = ("_por_chave",)

    def __init__(self) -> None:
        self._por_chave: dict[CommandKey, CommandInstance] = {}

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(
        self,
        instance: CommandInstance,
        escopos: tuple[int | None, ...] | None = None,
    ) -> CommandInstance:
        """Registra, ou devolve a instância já existente.

        Re-registrar o mesmo comando é silencioso — é o que acontece
        quando `bootstrap` e um import direto do usuário carregam o
        mesmo módulo. Brigar por isso derrubaria o caminho normal.

        `escopos` é o `K1` multiplicando a chave: `guild=(123, 456)`
        vira **duas** chaves apontando para **este mesmo objeto**
        (`0026` §2). Uma instância por escopo, com `_rebuild` em
        cascata, faria `.sub()` num escopo afetar só o primeiro — e a
        sincronia se manteria só enquanto ninguém esquecesse.
        """
        alvos = escopos if escopos is not None else (instance.definition.scope,)
        instance._escopos = tuple(alvos)

        existente: CommandInstance | None = None
        for escopo in alvos:
            chave = (instance.definition.type, instance.definition.name, escopo)
            achado = self._por_chave.get(chave)
            if achado is None:
                self._por_chave[chave] = instance
                continue
            if achado is instance:
                continue
            self._confere_igualdade(achado, instance, chave)
            existente = achado

        return existente if existente is not None else instance

    def reescopiar(self, escopos: tuple[int, ...]) -> None:
        """Move os comandos **adiados** para o default do `Config` (`0028`).

        Chamado pelo `Client.start()`, que é o primeiro momento em que
        o `Config`, o registry já preenchido e as importações
        concluídas coexistem. Registrar antes disso é ordem de import
        decidindo comportamento, que é o que este método existe para
        evitar.

        Com `escopos` vazio é **no-op**: `()` significa "padrão é
        global", e o adiado já está no global — é o que faz todo bot
        que nunca mexeu em `CommandOptions.guilds` continuar igual.
        """
        if not escopos:
            return

        adiados = [
            (chave, instancia)
            for chave, instancia in list(self._por_chave.items())
            if instancia.deferido
        ]
        if not adiados:
            return

        vistos: set[int] = set()
        for chave, instancia in adiados:
            if id(instancia) in vistos:
                # Mesma instância em vários escopos já removidos numa
                # iteração anterior — o `.escopos` lista todos, então
                # repete aqui.
                continue
            vistos.add(id(instancia))

            del self._por_chave[chave]
            novos = tuple(int(g) for g in escopos)
            for escopo in novos:
                self._por_chave[(chave[0], chave[1], escopo)] = instancia
            instancia._escopos = novos
            instancia._deferido = False

    def _confere_igualdade(
        self,
        existente: CommandInstance,
        novo: CommandInstance,
        chave: CommandKey,
    ) -> None:
        """Dois módulos com o mesmo nome e payloads diferentes é erro
        real — e a mensagem precisa citar os dois, senão o usuário
        persegue o lugar errado."""
        a, b = existente.definition.to_payload(), novo.definition.to_payload()
        if a == b:
            return

        divergencias = sorted(
            f"{k}: {a.get(k)!r} -> {b.get(k)!r}" for k in set(a) | set(b) if a.get(k) != b.get(k)
        )
        raise CommandDefinitionError(
            f"comando {chave[1]!r} (type={chave[0].name}, "
            f"scope={chave[2] if chave[2] is not None else 'global'}) já registrado em "
            f"{_onde(existente)} com definição diferente de {_onde(novo)}: "
            + "; ".join(divergencias)
        )

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------

    def get(
        self,
        type: ApplicationCommandType,
        name: str,
        scope: int | None = None,
    ) -> CommandInstance | None:
        """Busca pela chave completa. `None` se não existir."""
        return self._por_chave.get((type, name, scope))

    def has(
        self,
        type: ApplicationCommandType,
        name: str,
        scope: int | None = None,
    ) -> bool:
        return (type, name, scope) in self._por_chave

    def instances(self) -> tuple[CommandInstance, ...]:
        """Todos os comandos, em ordem estável, **sem repetição**.

        Ordenação por `(type, name, scope)` — o `sync()` depende de a
        ordem ser a mesma entre execuções, senão o diff enxerga
        movimentação como mudança.

        Deduplica por identidade porque `guild=(123, 456)` são duas
        chaves para um objeto só (`0026` §2). Sem deduplicar, um
        comando em duas guilds apareceria duas vezes em
        `client.commands.instances()` — que é o número que o `bootstrap`
        do `0027` conta no `load_logs`.
        """
        vistos: set[int] = set()
        saida: list[CommandInstance] = []
        for k in sorted(self._por_chave, key=lambda k: (int(k[0]), k[1], k[2] or -1)):
            instancia = self._por_chave[k]
            if id(instancia) in vistos:
                continue
            vistos.add(id(instancia))
            saida.append(instancia)
        return tuple(saida)

    def for_scope(self, scope: int | None) -> tuple[CommandInstance, ...]:
        """Comandos de um escopo — o que o `sync()` despacha de uma vez.

        Filtra pela **chave**, não por `instance.scope`: a instância de
        `guild=(123, 456)` guarda em `.scope` só o primeiro, e o
        despacho e o sync leem a chave (`0026` §2).
        """
        return tuple(
            self._por_chave[k]
            for k in sorted(self._por_chave, key=lambda k: (int(k[0]), k[1], k[2] or -1))
            if k[2] == scope
        )

    def scopes(self) -> tuple[int | None, ...]:
        """Escopos presentes, ordenados. `None` (global) primeiro.

        Derivado das chaves, pelos mesmos motivos do `for_scope`.
        """
        encontrados = {k[2] for k in self._por_chave}
        return tuple(sorted(encontrados, key=lambda s: (s is not None, s or 0)))

    def __len__(self) -> int:
        return len(self._por_chave)

    def __iter__(self) -> Iterator[CommandInstance]:
        return iter(self.instances())

    def __contains__(self, item: object) -> bool:
        if isinstance(item, tuple) and len(item) == 3:
            return item in self._por_chave
        return False

    # ------------------------------------------------------------------
    # Chave
    # ------------------------------------------------------------------

    @staticmethod
    def chave_de(definition: CommandDefinition) -> CommandKey:
        """A chave de uma definição. Exportada porque o `sync` e os
        testes precisam do mesmo cálculo, sem reimplementar."""
        return (definition.type, definition.name, definition.scope)


def _onde(instance: CommandInstance) -> str:
    """Módulo onde o handler foi definido.

    `__module__` do handler é o que aponta o arquivo real. Sem isso a
    mensagem diz "já registrado" e o usuário não sabe em que lugar.
    """
    modulo = getattr(instance.handler, "__module__", None)
    return modulo or "<desconhecido>"
