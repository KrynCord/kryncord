"""Comandos de aplicação tipados — `CommandInteraction` e parentes.

`CommandInteraction` é o handler de `/comando`. Menus de contexto têm
a própria classe porque têm o próprio **alvo**: `UserCommandInteraction`
expõe `target_user`, `MessageCommandInteraction` expõe
`target_message`. Fingir que os três são o mesmo objeto (como faz um
payload genérico) obriga todo handler a checar qual é.

`EntryPointInteraction` cobre `PRIMARY_ENTRY_POINT` — inicialização de
Activity, sem alvo e sem opções.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from kryncord.enums import ApplicationCommandType
from kryncord.interactions.base import BaseInteraction
from kryncord.models.attachment import Attachment
from kryncord.models.channel import Channel
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.role import Role
from kryncord.models.user import User


class CommandInteraction(BaseInteraction):
    """Um comando de aplicação (CHAT_INPUT) sendo executado."""

    __slots__ = ()

    @property
    def options(self) -> OptionsAccessor:
        """As opções declaradas, já convertidas pelo conversor."""
        return OptionsAccessor(self.interaction)

    @property
    def command_name(self) -> str | None:
        """Nome do comando invocado."""
        return self.interaction.command_name

    def _tabela_de_alvo(self, tabela: str, campo: str) -> Any:
        """Um objeto de `data.resolved`, com erro que cita o campo."""
        data = self.interaction.data or {}
        resolved = data.get("resolved", {})
        alvos = (resolved.get(tabela) or {}) if isinstance(resolved, Mapping) else {}
        if not alvos:
            raise AttributeError(
                f"{campo} não existe nesta interação — o alvo vem do clique em "
                f"menu USER/MESSAGE, e /comando não tem alvo"
            )
        return next(iter(alvos.values()))


class UserCommandInteraction(CommandInteraction):
    """Menu de contexto sobre **usuário** — o alvo vem do clique."""

    __slots__ = ()

    @property
    def target_user(self) -> User:
        """Alvo do menu USER. `AttributeError` se o payload não trouxer."""
        return cast("User", User.from_payload(dict(self._tabela_de_alvo("users", "target_user"))))

    @property
    def target_member(self) -> Member | None:
        """Alvo do menu USER como membro — `None` se o payload não
        trouxer o `resolved.members` correspondente.

        `resolved.members[id]` vem **sem** `user`; o `user` está em
        `resolved.users[id]` — mesma fusão do `OptionsAccessor.
        get_member`.
        """
        data = self.interaction.data or {}
        resolved = data.get("resolved", {})
        membros = (resolved.get("members") or {}) if isinstance(resolved, Mapping) else {}
        usuarios = (resolved.get("users") or {}) if isinstance(resolved, Mapping) else {}
        if not membros:
            return None
        id_alvo, bruto = next(iter(membros.items()))
        if not isinstance(bruto, Mapping):
            return None
        fundido = dict(bruto)
        usuario = usuarios.get(str(id_alvo))
        if isinstance(usuario, Mapping):
            fundido["user"] = usuario
        return Member.from_payload(fundido)


class MessageCommandInteraction(CommandInteraction):
    """Menu de contexto sobre **mensagem** — o alvo vem do clique."""

    __slots__ = ()

    @property
    def target_message(self) -> Message:
        """Alvo do menu MESSAGE. `AttributeError` se não vier."""
        bruto = self._tabela_de_alvo("messages", "target_message")
        return cast("Message", Message.from_payload(dict(bruto)))


class EntryPointInteraction(CommandInteraction):
    """`PRIMARY_ENTRY_POINT` — inicialização de Activity."""

    __slots__ = ()


class OptionsAccessor:
    """Leitura tipada das opções de um comando.

    Duas exceções diferentes porque são dois erros diferentes:

    | Exceção | Quando |
    |---|---|
    | `AttributeError` | opção não declarada neste comando |
    | `KeyError` | chave desconhecida no `[]` |

    A primeira é "você digitou o nome errado"; a segunda é "essa opção
    não existe". Misturar as duas obriga a ler a pilha para saber qual.

    Opções de subcommand são **achatadas**: com
    ``/grupo sub op:1``, ``interaction.options["op"]`` funciona — sem o
    `getSubcommand()` do discord.js para chegar até ela. O subcommand
    em si continua consultável, porque às vezes a pergunta é "qual
    ramo foi invocado" e não "qual o valor".
    """

    __slots__ = ("_resolvidos", "_sub", "_sub_grupo", "_valores")

    def __init__(self, interaction: Interaction) -> None:
        data = interaction.data or {}
        self._valores: dict[str, Any] = {}
        self._sub: str | None = None
        self._sub_grupo: str | None = None
        self._achata(data.get("options") or [])
        resolved = data.get("resolved")
        self._resolvidos: Mapping[str, Any] = resolved if isinstance(resolved, Mapping) else {}

    def _achata(self, bruto: Any) -> None:
        """Achata a árvore de opções no dicionário de valores.

        Subcommand (type 1) e grupo (type 2) não têm `value` — têm
        `options`. Registrar o nome na trilha e descer é o que faz o
        achatamento; sem ele, toda opção de subcommand exigiria o
        caminho completo na mão.
        """
        for o in bruto:
            if not isinstance(o, Mapping) or "name" not in o:
                continue
            tipo = o.get("type")
            if tipo in (1, 2) and isinstance(o.get("options"), list):
                if tipo == 2:
                    self._sub_grupo = str(o["name"])
                else:
                    self._sub = str(o["name"])
                self._achata(o["options"])
                continue
            self._valores[str(o["name"])] = o.get("value")

    @property
    def valores(self) -> Mapping[str, Any]:
        """Todos os valores crus, sem conversão."""
        return self._valores

    def get_subcommand(self) -> str | None:
        """O subcommand invocado, se houver. `None` no comando simples."""
        return self._sub

    def get_subcommand_group(self) -> str | None:
        """O grupo invocado, se houver. `None` fora de grupo."""
        return self._sub_grupo

    def __getitem__(self, nome: str) -> Any:
        try:
            return self._valores[nome]
        except KeyError:
            raise KeyError(
                f"opção {nome!r} não foi enviada — declarada? disponíveis: {sorted(self._valores)}"
            ) from None

    def __contains__(self, nome: object) -> bool:
        return nome in self._valores

    def __getattr__(self, nome: str) -> Any:
        """`interaction.options.pontos` só para opção declarada.

        `AttributeError` com a lista do que existe — sem isto, o Python
        devolveria um `AttributeError` interno de `__slots__` que não
        menciona o nome digitado.
        """
        try:
            return self._valores[nome]
        except KeyError:
            raise AttributeError(
                f"opção {nome!r} não declarada neste comando; disponíveis: {sorted(self._valores)}"
            ) from None

    # ------------------------------------------------------------------
    # Getters tipados
    # ------------------------------------------------------------------

    def get_string(self, nome: str, default: str | None = None) -> str | None:
        return cast("str | None", self._get(nome, str, default))

    def get_int(self, nome: str, default: int | None = None) -> int | None:
        return cast("int | None", self._get(nome, int, default))

    def get_float(self, nome: str, default: float | None = None) -> float | None:
        """Também é o getter de `NUMBER`, que o Discord manda como float."""
        return cast("float | None", self._get(nome, float, default))

    #: Alias legível — discord.js chama de `getNumber`. Um nome só não
    #: bastou porque `float` já era o nome do tipo no KrynCord.
    get_number = get_float

    def get_bool(self, nome: str, default: bool | None = None) -> bool | None:
        return cast("bool | None", self._get(nome, bool, default))

    def _get(self, nome: str, tipo: type, default: Any) -> Any:
        """`None` quando a opção não foi enviada; `TypeError` quando
        enviou do tipo errado.

        Fundir os dois faria um `default` mascarar um tipo errado —
        que é quase sempre um bug na declaração da opção, e não um
        dado faltando.

        O `cast` nos getters é seguro porque o `isinstance` aqui já
        provou o tipo — o mypy só não consegue seguir até lá."""
        if nome not in self._valores:
            return default
        valor = self._valores[nome]
        if not isinstance(valor, tipo):
            raise TypeError(
                f"opção {nome!r} veio como {type(valor).__name__}, esperado "
                f"{tipo.__name__} — confira o OptionType declarado"
            )
        return valor

    # ------------------------------------------------------------------
    # Getters de entidade — resolvem por `data.resolved`
    # ------------------------------------------------------------------
    #
    # O Discord manda o id como `value` e o objeto completo em
    # `resolved`. Buscar o objeto é olhar os dois — e é por isso que
    # `Member`/`Role` não precisam de `guild_id` no modelo (0008): quem
    # resolve sabe a guild, e aqui ela não entra.

    def get_user(self, nome: str) -> User | None:
        return cast("User | None", self._resolve(nome, "users", User))

    def get_member(self, nome: str) -> Member | None:
        """O `Member`, com o `User` que o Discord manda separado.

        Em `resolved`, ``members[id]`` vem **sem** `user` — ele está em
        ``users[id]``. O discord.js funde como ``{...member, user}``;
        fundir os campos no mesmo nível faria `from_payload` devolver
        `None`, e o bug apareceria longe da causa.
        """
        valor = self._valores.get(nome)
        if valor is None:
            return None
        membros = self._resolvidos.get("members") or {}
        bruto = membros.get(str(valor))
        if not isinstance(bruto, Mapping):
            return None
        usuarios = self._resolvidos.get("users") or {}
        usuario = usuarios.get(str(valor))
        fundido = dict(bruto)
        if isinstance(usuario, Mapping):
            fundido["user"] = usuario
        return Member.from_payload(fundido)

    def get_role(self, nome: str) -> Role | None:
        return cast("Role | None", self._resolve(nome, "roles", Role))

    def get_channel(self, nome: str) -> Channel | None:
        return cast("Channel | None", self._resolve(nome, "channels", Channel))

    def get_attachment(self, nome: str) -> Attachment | None:
        return cast("Attachment | None", self._resolve(nome, "attachments", Attachment))

    def get_mentionable(self, nome: str) -> User | Role | None:
        """Opção `MENTIONABLE`: pode ser usuário ou cargo.

        O Discord decide qual pelo `resolved` onde o id aparece. É
        union porque a opção é union — estreitar para um dos dois
        obrigaria o handler a apostar.
        """
        valor = self._valores.get(nome)
        if valor is None:
            return None
        for tabela, modelo in (("users", User), ("roles", Role)):
            bruto = (self._resolvidos.get(tabela) or {}).get(str(valor))
            if bruto is not None:
                return cast("User | Role", modelo.from_payload(dict(bruto)))
        return None

    def _resolve(self, nome: str, tabela: str, modelo: Any) -> Any:
        """Busca o objeto completo em `resolved` pelo id que veio em `value`."""
        valor = self._valores.get(nome)
        if valor is None:
            return None
        bruto = (self._resolvidos.get(tabela) or {}).get(str(valor))
        if bruto is None:
            return None
        return modelo.from_payload(dict(bruto))


#: `ApplicationCommandType` → classe entregue ao handler. O payload do
#: Discord traz o tipo, e o tipo decide a classe — nunca a anotação.
CLASSES_COMANDO: dict[ApplicationCommandType, type[CommandInteraction]] = {
    ApplicationCommandType.CHAT_INPUT: CommandInteraction,
    ApplicationCommandType.USER: UserCommandInteraction,
    ApplicationCommandType.MESSAGE: MessageCommandInteraction,
    ApplicationCommandType.PRIMARY_ENTRY_POINT: EntryPointInteraction,
}


def classe_de_comando(tipo: ApplicationCommandType) -> type[CommandInteraction]:
    """A classe de interação para um tipo de comando.

    Tipo novo do Discord cai em `CommandInteraction` — a superfície
    comum existe justamente para o caso em que o Discord anda à frente.
    """
    return CLASSES_COMANDO.get(tipo, CommandInteraction)


__all__ = [
    "CLASSES_COMANDO",
    "CommandInteraction",
    "EntryPointInteraction",
    "MessageCommandInteraction",
    "OptionsAccessor",
    "UserCommandInteraction",
    "classe_de_comando",
]
