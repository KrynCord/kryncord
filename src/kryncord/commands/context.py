"""Contexto entregue ao handler de um comando.

`CommandContext` **compõe**, não herda. O `InteractionContext` é o dono
de responder; este objeto é o dono dos campos do comando. A separação
existe porque os dois mudam por ritmos diferentes — o estado da resposta
muda a cada chamada, os campos do comando nunca mudam depois do
dispatch.

`ctx.reply(...)` é delegação, não reimplementação: um só
`InteractionContext` por dispatch significa que `ctx.reply()` e
`ctx.interaction` nunca discordam sobre o que já foi respondido.

`ctx.options` é um accessor tipado, não um dict — porque quem escreve
`ctx.options.get_int("pontos")` quer o erro na linha, não um `None`
silencioso quando o campo não existe.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from kryncord.interactions.response import InteractionContext, InteractionState
from kryncord.models.attachment import Attachment
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.role import Role
from kryncord.models.user import User


class CommandContext:
    """Contexto de execução de um comando."""

    __slots__ = (
        "_args",
        "_channel",
        "_client",
        "_guild",
        "_interaction_ctx",
        "_member",
        "_state",
        "_user",
    )

    def __init__(
        self,
        interaction_ctx: InteractionContext,
        *,
        guild: Guild | None = None,
        channel: Channel | None = None,
        user: User | None = None,
        member: Member | None = None,
        client: Any = None,
        state: dict[str, Any] | None = None,
        args: list[Any] | None = None,
    ) -> None:
        self._interaction_ctx = interaction_ctx
        self._guild = guild
        self._channel = channel
        self._user = user
        self._member = member
        self._client = client
        #: Por dispatch, compartilhado com middleware — e com o
        #: `EventContext` do mesmo `INTERACTION_CREATE` (`0026` §6).
        #: Nasce vazio quando o chamador não repassa, que é o caso do
        #: contexto montado à mão em teste.
        self._state: dict[str, Any] = state if state is not None else {}
        #: Lista viva — a mutação propaga para os próximos handlers no
        #: modo `sequential`, e é por design.
        self._args: list[Any] = list(args) if args is not None else []

    # ------------------------------------------------------------------
    # Quem e onde
    # ------------------------------------------------------------------

    @property
    def interaction(self) -> Interaction:
        """O payload, dado puro. Para ler `data`, `id`, `token`…"""
        return self._interaction_ctx.interaction

    @property
    def interaction_context(self) -> InteractionContext:
        """O dono do estado. `ctx.reply()` já delega; exposto para
        quem precisa do objeto — testes e extensões."""
        return self._interaction_ctx

    @property
    def guild(self) -> Guild | None:
        """Do cache local. `None` em interação de DM."""
        return self._guild

    @property
    def channel(self) -> Channel | None:
        return self._channel

    @property
    def user(self) -> User | None:
        """Quem invocou. Em guild vem do `member.user`; em DM vem do
        `user` da interação."""
        return self._user

    @property
    def member(self) -> Member | None:
        """`None` em DM — membros só existem em guild."""
        return self._member

    @property
    def client(self) -> Any:
        """O `Client` que despachou. `None` em teste unitário."""
        return self._client

    @property
    def state(self) -> dict[str, Any]:
        """Espaço por dispatch, compartilhado com as middlewares.

        `ctx.state["chave"]` é a forma de uma middleware passar dado a
        um handler sem adicionar atributo ao contexto. Não vaza entre
        dispatches — nasce vazio a cada um.
        """
        return self._state

    @property
    def args(self) -> list[Any]:
        """Argumentos posicionais, mutáveis.

        A mutação **propaga** para os próximos handlers no modo
        `sequential` — é o recurso documentado da `10` §8 para
        reordenar ou substituir argumentos entre handlers.
        """
        return self._args

    # ------------------------------------------------------------------
    # Resposta — delegação pura
    # ------------------------------------------------------------------

    @property
    def state_resposta(self) -> InteractionState:
        """Estado da máquina, para quem quer consultar sem perguntar."""
        return self._interaction_ctx.state

    def is_responded(self) -> bool:
        """Já houve qualquer resposta — defer inclusive."""
        return self._interaction_ctx.is_responded()

    def is_deferred(self) -> bool:
        return self._interaction_ctx.is_deferred()

    def is_answered(self) -> bool:
        return self._interaction_ctx.is_answered()

    async def reply(self, content: str | None = None, **kwargs: Any) -> None:
        await self._interaction_ctx.reply(content, **kwargs)

    async def defer(self, *, ephemeral: bool = False) -> None:
        await self._interaction_ctx.defer(ephemeral=ephemeral)

    async def defer_update(self) -> None:
        await self._interaction_ctx.defer_update()

    async def update(self, content: str | None = None, **kwargs: Any) -> None:
        await self._interaction_ctx.update(content, **kwargs)

    async def ack(self) -> None:
        await self._interaction_ctx.ack()

    async def edit(
        self,
        content: str | None = None,
        *,
        message_id: str | int = "@original",
        **kwargs: Any,
    ) -> None:
        await self._interaction_ctx.edit(content, message_id=message_id, **kwargs)

    async def delete(self, *, message_id: str | int = "@original") -> None:
        await self._interaction_ctx.delete(message_id=message_id)

    async def fetch_reply(self, *, message_id: str | int = "@original") -> Any:
        return await self._interaction_ctx.fetch_reply(message_id=message_id)

    async def follow_up(self, content: str | None = None, **kwargs: Any) -> Any:
        return await self._interaction_ctx.follow_up(content, **kwargs)

    async def send_modal(self, modal: Any) -> None:
        await self._interaction_ctx.send_modal(modal)

    async def launch_activity(self) -> None:
        await self._interaction_ctx.launch_activity()

    # ------------------------------------------------------------------
    # Opções
    # ------------------------------------------------------------------

    @property
    def options(self) -> OptionsAccessor:
        """As opções declaradas, já convertidas pelo conversor."""
        return OptionsAccessor(self.interaction)

    # ------------------------------------------------------------------
    # Context menu — 0022
    # ------------------------------------------------------------------

    @property
    def target_user(self) -> User:
        """Alvo do menu USER. `AttributeError` em CHAT_INPUT — o
        alvo de menu vem do clique, e slash não tem alvo."""
        return cast("User", self._exige_menu("target_user"))

    @property
    def target_member(self) -> Member | None:
        """Alvo do menu USER, se o cache tiver o membro."""
        return cast("Member | None", self._exige_menu("target_member"))

    @property
    def target_message(self) -> Message:
        """Alvo do menu MESSAGE."""
        return cast("Message", self._exige_menu("target_message"))

    def _exige_menu(self, campo: str) -> Any:
        data = self.interaction.data or {}
        resolved = data.get("resolved", {})

        if campo == "target_user":
            alvos = resolved.get("users") or {}
        elif campo == "target_member":
            alvos = resolved.get("members") or {}
        elif campo == "target_message":
            alvos = resolved.get("messages") or {}
        else:
            alvos = {}

        if not alvos:
            raise AttributeError(
                f"{campo} não existe em comando CHAT_INPUT — o alvo vem do clique em "
                f"menu USER/MESSAGE, e /comando não tem alvo"
            )
        return next(iter(alvos.values()))


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
    ``/grupo sub op:1``, ``ctx.options["op"]`` funciona — sem o
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
        """`ctx.options.pontos` só para opção declarada.

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
