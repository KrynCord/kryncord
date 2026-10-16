"""Aplica eventos do gateway no cache, respeitando dados parciais.

É aqui que a arquitetura pede "atualiza modelos/cache a partir de
eventos, respeitando dados parciais", e a segunda metade da frase é a
que custa.

## O merge: presente no payload, não "diferente de default"

`GUILD_UPDATE`, `MESSAGE_UPDATE` e `GUILD_MEMBER_UPDATE` podem vir sem
todos os campos — edição que mexe só no embed manda os campos do embed,
não o objeto inteiro. Gravar o que veio por cima do que já tinha
apagaria os campos que o Discord não mencionou, e a regra para decidir
não pode ser "se o valor parseou diferente de zero".

`from_payload` **não** distingue ausente de default: campo que não veio
vira `False`, `()` ou `None`. Então quem compara modelo-com-modelo só
veria a diferença e concluiria que um campo apagado foi alterado.

Quem compara é o **payload bruto**: campo cujo nome está no JSON é
campo que o Discord falou; os outros ficam como estavam. É a mesma
regra de sempre — ausente não é valor —, aplicada do lado de dentro da
atualização em vez do lado do parsing.

## E quando o campo tem outro nome

O model não é o payload. `Message.edited_at` lê `edited_timestamp`,
`Role.positions_new` lê `positions` — mesmas coisas, nomes diferentes,
e um merge que procurasse `edited_at` no JSON não o acharia nunca,
deixando a data da edição antiga para sempre num campo que quase todo
código olha.

`_RENOMES` traduz só isso: onde procurar. Quem decide continua sendo o
payload. Ficam de fora os campos que vêm de **nó aninhado**
(`Channel.archived` sai de `thread_metadata`): aqueles não têm outro
nome, têm outro lugar — e saber a árvore exigiria que cada model
declarasse como o payload é estruturado, que é conhecimento que não
temos.

## Por que os parsers são nossos e não o `REGISTRY`

`events/dispatcher.py::REGISTRY` decide **o que o handler recebe**, e é
um contrato de entrega que não muda porque o cache passou a guardar
coisa. Aqui é o contrário: `GUILD_MEMBER_ADD` não está no `REGISTRY`
(handlers recebem o dict cru, decisão do 0006) mas o cache precisa do
`Member`. Dois mapas com interesses diferentes, e misturar os dois faria
o cache parar de funcionar no dia em que um evento ganhar ou perder
parser lá.

## Payload que não é `Mapping` é ignorado

Dispatch que não veio como objeto não descreve entidade nenhuma. Não é
erro — é o caso de "não há o que guardar".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from typing import Any, TypeVar, cast

from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.ready import Ready
from kryncord.models.role import Role
from kryncord.models.user import User
from kryncord.models.voice import VoiceState
from kryncord.state.connection_state import ConnectionState

T = TypeVar("T")

_RENOMES: dict[str, str] = {
    # campo do model -> chave no payload do Discord
    "edited_at": "edited_timestamp",
    "positions_new": "positions",
}
"""Onde Discord e model discordam do nome do mesmo campo.

Só os que existem de verdade, e a lista é curta porque os dois lados
vêm do mesmo contrato. Derivados de nó aninhado (``Channel.archived``,
que sai de ``thread_metadata``) **não** entram aqui: aqueles não são
outro nome, são outro lugar — e sabê-los exigiria que cada model
declarasse a árvore do payload, que é conhecimento que não temos.
"""


class EventUpdater:
    """Traduz um evento do Discord em escrita (ou remoção) no cache.

    Sem estado próprio: guarda só a referência ao `ConnectionState`.
    Dois eventos seguidos não conversam entre si — cada um é avaliado
    pelo que chegou, e a memória é do estado, não dele.
    """

    __slots__ = ("_state",)

    def __init__(self, state: ConnectionState) -> None:
        self._state = state

    def apply(self, name: str, payload: Any) -> None:
        """Aplica um dispatch ao cache.

        Nunca apaga por engano e nunca levanta por payload estranho dos
        nossos parsers (eles devolvem `None`, não lançam). Pode levantar
        se houver bug nosso — e quem chama (`Client._dispatch`) é que
        decide se isso derruba o bot. Guarde e engoliu aqui dentro seria
        um erro invisível para sempre.
        """
        if not isinstance(payload, Mapping):
            return

        if name == "READY":
            self._ready(payload)
        elif name == "USER_UPDATE":
            self._user_update(payload)
        elif name == "GUILD_CREATE":
            self._guild_create(payload)
        elif name == "GUILD_UPDATE":
            self._guild_update(payload)
        elif name == "GUILD_DELETE":
            self._guild_delete(payload)
        elif name == "GUILD_MEMBER_ADD":
            self._member_add(payload)
        elif name == "GUILD_MEMBER_UPDATE":
            self._member_update(payload)
        elif name == "GUILD_MEMBER_REMOVE":
            self._member_remove(payload)
        elif name == "GUILD_ROLE_CREATE":
            self._role_create(payload)
        elif name == "GUILD_ROLE_UPDATE":
            self._role_update(payload)
        elif name == "GUILD_ROLE_DELETE":
            self._role_delete(payload)
        elif name in ("CHANNEL_CREATE", "THREAD_CREATE"):
            self._channel_create(payload)
        elif name in ("CHANNEL_UPDATE", "THREAD_UPDATE"):
            self._channel_update(payload)
        elif name in ("CHANNEL_DELETE", "THREAD_DELETE"):
            self._channel_delete(payload)
        elif name == "MESSAGE_CREATE":
            self._message_create(payload)
        elif name == "MESSAGE_UPDATE":
            self._message_update(payload)
        elif name == "MESSAGE_DELETE":
            self._message_delete(payload)
        elif name == "MESSAGE_DELETE_BULK":
            self._message_delete_bulk(payload)
        elif name == "VOICE_STATE_UPDATE":
            self._voice_state_update(payload)

    # ------------------------------------------------------------------
    # Conexão
    # ------------------------------------------------------------------

    def _ready(self, payload: Mapping[str, Any]) -> None:
        """Quem o bot é, e os stubs de guild ainda indisponíveis.

        O `READY` traz `guilds` como `{id, unavailable}` — é o Discord
        dizendo "você está nestes servidores, ainda não vou te contar
        nada deles". Guardar o stub é o que faz `get_guild(id)` achar
        antes dos `GUILD_CREATE` chegarem, e é a razão de `Guild.name`
        poder ser `None` sem ser bug.
        """
        pronto = Ready.from_payload(payload)
        if pronto.user is not None:
            self._state.set_me(pronto.user)
        for bruto in _lista(payload, "guilds"):
            stub = Guild.from_payload(bruto)
            if stub is not None:
                self._state._put_guild(stub)

    def _user_update(self, payload: Mapping[str, Any]) -> None:
        """O usuário mudou — e esse evento só vem para o próprio bot.

        Não é `USER_DELETE` inexistente com outro nome: o Discord manda
        `USER_UPDATE` apenas quando o dono trocou avatar ou nome. É por
        isso que `users` precisa de LRU — nenhum evento remove conta de
        terceiro, e sem teto a lista só cresce.
        """
        user = User.from_payload(payload)
        if user is None:
            return
        self._state.set_me(user)

    # ------------------------------------------------------------------
    # Guild
    # ------------------------------------------------------------------

    def _guild_create(self, payload: Mapping[str, Any]) -> None:
        """O servidor chega inteiro — e traz junto membros, cargos e canais.

        É o evento mais denso do gateway. Cada array vira entradas
        próprias no cache porque `Guild` guarda só os **IDs** de cargo
        e emoji: um `Guild` com `roles=(1, 2, 3)` não tem os cargos, tem
        referências a eles. Guardar o array no cache sem tirar cada item
        deixaria `get_role()` sempre `None` para o servidor recém-chegado.

        `threads` entra junto: thread **é** `Channel` (tipos 10/11/12),
        não há model separado, e o Discord manda no mesmo nível de
        `channels`.
        """
        guild = Guild.from_payload(payload)
        if guild is None:
            return
        self._state._put_guild(guild)
        guild_id = guild.id

        for bruto in _lista(payload, "roles"):
            role = Role.from_payload(bruto)
            if role is not None:
                self._state._put_role(guild_id, role)

        for campo in ("channels", "threads"):
            for bruto in _lista(payload, campo):
                channel = _canal_no_guild(bruto, guild_id)
                if channel is not None:
                    self._state._put_channel(channel)

        for bruto in _lista(payload, "members"):
            member = Member.from_payload(bruto)
            if member is None:
                continue
            self._state._put_member(guild_id, member)
            # A conta vem dentro do membro e é a mesma em toda guild.
            self._state._put_user(member.user)

        # Voz vem junto — e é o que faz a primeira mudança de canal de
        # alguém ter `old`. Sem semear aqui, `voice_state_update(old, new)`
        # entregaria `None` no primeiro evento de cada usuário, que é
        # justamente o que o `0025` §6 decidiu que não pode acontecer.
        for bruto in _lista(payload, "voice_states"):
            voice_state = _voz_no_guild(bruto, guild_id)
            if voice_state is not None:
                self._state._put_voice_state(voice_state)

    def _guild_update(self, payload: Mapping[str, Any]) -> None:
        """Servidor mudou — payload sem `members`, `channels` nem `threads`.

        É o motivo do merge existir. `GUILD_UPDATE` é um objeto de
        guild comum, e os arrays de organização **não vêm nele** (vêm no
        `GUILD_CREATE`). Gravar por cima manteria `name` etc., mas o que
        importa aqui é o contrário: `roles` e `emojis`, que são IDs e
        vêm sim, são relidos, e nada do que faltou é apagado.
        """
        novo = Guild.from_payload(payload)
        if novo is None:
            return
        antigo = self._state.get_guild(novo.id)
        if antigo is not None:
            novo = _merge(antigo, novo, payload)
        self._state._put_guild(novo)

    def _guild_delete(self, payload: Mapping[str, Any]) -> None:
        """Indisponível (`unavailable: true`) ou saiu de vez — são diferentes.

        Na indisponibilidade o servidor continua existindo: o Discord
        te tira por causa de um outage e manda `GUILD_CREATE` de volta.
        Apagar membros e canais aqui jogaria fora dados que ninguém vai
        reenviar antes de você precisar deles.

        Sem `unavailable`, você **saiu**. Aí os filhos vão junto — não
        há `CHANNEL_DELETE` para canais de um servidor que sumiu para
        nós, e deixar `members` órfãos seria memória de um lugar onde
        o bot não está mais.
        """
        guild_id = _id(payload)
        if guild_id is None:
            return

        if payload.get("unavailable") is True:
            novo = Guild.from_payload(payload)
            if novo is None:
                return
            antigo = self._state.get_guild(guild_id)
            if antigo is not None:
                novo = _merge(antigo, novo, payload)
            self._state._put_guild(novo)
            return

        self._state._drop_guild(guild_id)
        self._state._drop_guild_children(guild_id)

    # ------------------------------------------------------------------
    # Membros
    # ------------------------------------------------------------------

    def _member_add(self, payload: Mapping[str, Any]) -> None:
        """Alguém entrou — e o payload traz `guild_id`, ao contrário do array.

        Nosso `Member` não tem `guild_id` porque dentro do `GUILD_CREATE`
        a lista vem **dentro** do objeto da guild e não diz de qual é.
        Aqui o Discord completa. Quem lê o evento é quem sabe.
        """
        guild_id = _payload_guild_id(payload)
        member = Member.from_payload(payload)
        if guild_id is None or member is None:
            return
        self._state._put_member(guild_id, member)
        self._state._put_user(member.user)

    def _member_update(self, payload: Mapping[str, Any]) -> None:
        """Membro mudou — cargo, apelido ou timeout.

        Merge porque `deaf?` e `mute?` vêm marcados como opcionais: um
        payload sem eles não significa "não está surdo", significa "não
        mudou".
        """
        guild_id = _payload_guild_id(payload)
        novo = Member.from_payload(payload)
        if guild_id is None or novo is None:
            return
        antigo = self._state.get_member(guild_id, novo.user.id)
        if antigo is not None:
            novo = _merge(antigo, novo, payload)
        self._state._put_member(guild_id, novo)
        self._state._put_user(novo.user)

    def _member_remove(self, payload: Mapping[str, Any]) -> None:
        """Saiu do servidor (saiu, foi kickado ou banido).

        Só o membro vai: a **conta** continua existindo em outras guilds.
        `users` não tem evento de remoção nenhum, e achar que este é um
        seria apagar alguém que está em outro lugar.
        """
        guild_id = _payload_guild_id(payload)
        user = payload.get("user")
        if guild_id is None or not isinstance(user, Mapping):
            return
        user_id = _id(user)
        if user_id is not None:
            self._state._drop_member(guild_id, user_id)

    # ------------------------------------------------------------------
    # Cargos
    # ------------------------------------------------------------------

    def _role_create(self, payload: Mapping[str, Any]) -> None:
        """Cargo novo — `{guild_id, role}`."""
        guild_id = _payload_guild_id(payload)
        bruto = payload.get("role")
        if guild_id is None or not isinstance(bruto, Mapping):
            return
        role = Role.from_payload(bruto)
        if role is not None:
            self._state._put_role(guild_id, role)

    def _role_update(self, payload: Mapping[str, Any]) -> None:
        """Cargo mudou — nome, cor ou permissões.

        O merge é com o **objeto do cargo**, não com o envelope: os
        nomes de campo (`name`, `color`) vivem dentro de `role`, e
        comparar com o envelope `{guild_id, role}` não encontraria
        nenhum e manteria tudo velho.
        """
        guild_id = _payload_guild_id(payload)
        bruto = payload.get("role")
        if guild_id is None or not isinstance(bruto, Mapping):
            return
        novo = Role.from_payload(bruto)
        if novo is None:
            return
        antigo = self._state.get_role(guild_id, novo.id)
        if antigo is not None:
            novo = _merge(antigo, novo, bruto)
        self._state._put_role(guild_id, novo)

    def _role_delete(self, payload: Mapping[str, Any]) -> None:
        """Cargo apagado — `{guild_id, role_id}`.

        `role_id` e não `role`: o Discord manda só o ID, não o objeto.
        """
        guild_id = _payload_guild_id(payload)
        role_id = payload.get("role_id")
        if guild_id is None:
            return
        if isinstance(role_id, str) and role_id.isdigit():
            self._state._drop_role(guild_id, int(role_id))
        elif isinstance(role_id, int) and not isinstance(role_id, bool):
            self._state._drop_role(guild_id, role_id)

    # ------------------------------------------------------------------
    # Canais e threads
    # ------------------------------------------------------------------

    def _channel_create(self, payload: Mapping[str, Any]) -> None:
        """Canal ou thread novo — o payload é o próprio canal.

        `THREAD_CREATE` manda o mesmo objeto de canal, com um
        `newly_created` a mais que não é campo dele. Tratar os dois igual
        é correto porque a thread **é** um canal: não existe `Thread` no
        `models/`, e inventar um faria `get_channel()` não achar thread.
        """
        channel = Channel.from_payload(payload)
        if channel is not None:
            self._state._put_channel(channel)

    def _channel_update(self, payload: Mapping[str, Any]) -> None:
        """Canal ou thread mudou.

        `THREAD_UPDATE` é o que torna o merge necessário de fato: ele
        traz `thread_metadata` (um objeto aninhado), e os campos que
        dele saem — `archived`, `locked`, `auto_archive_duration` — não
        estão no payload em cima. Com merge, os que estão no nível de
        cima são relidos e os que faltam ficam; sem merge, tudo seria
        relido e `name` sumiria de um thread cujo payload só trouxe
        metadata.

        Limite conhecido: `archived` e `locked` vêm **de baixo** de
        `thread_metadata`, então não estão no nível de cima do payload e
        o merge os mantém como estavam. Consertar isso exigiria que cada
        modelo declarasse qual campo ele deriva de qual nó — conhecimento
        que não temos e que inventar seria pior que uma leitura
        desatualizada. O campo certo é possível de ler direto do payload
        bruto, e é o que se recomenda para quem precisa dele.
        """
        novo = Channel.from_payload(payload)
        if novo is None:
            return
        antigo = self._state.get_channel(novo.id)
        if antigo is None:
            self._state._put_channel(novo)
            return
        # O merge pode mudar `guild_id` (não muda na prática, mas o
        # agrupamento é calculado a partir dele) — por isso remontamos a
        # partir do resultado do merge, e não guardamos o `novo` cru.
        fundido = _merge(antigo, novo, payload)
        self._state._put_channel(fundido)

    def _channel_delete(self, payload: Mapping[str, Any]) -> None:
        """Canal ou thread apagado.

        `THREAD_DELETE` manda só `{id, guild_id, parent_id, type}` — um
        recorte. Ainda assim o ID está lá, que é tudo que remover
        precisa.
        """
        channel_id = _id(payload)
        if channel_id is not None:
            self._state._drop_channel(channel_id)

    # ------------------------------------------------------------------
    # Mensagens
    # ------------------------------------------------------------------

    def _message_create(self, payload: Mapping[str, Any]) -> None:
        """Mensagem nova — e de brinde, o autor e a aparência dele na guild.

        `put_user` do autor: é como a maioria das contas entra no cache,
        e é o que faz uma menção virar nome.

        O `member` dentro da mensagem (a face do autor **naquela** guild)
        também entra, quando existe e a política permite. `MESSAGE_CREATE`
        é a via mais comum de membro chegar para quem não ligou o intent
        `GUILD_MEMBERS` — e não é dado inventado, veio no payload.
        """
        message = Message.from_payload(payload)
        if message is None:
            return
        self._state._put_message(message)

        if message.author is not None:
            self._state._put_user(message.author)

        if message.member is not None and message.guild_id is not None:
            self._state._put_member(message.guild_id, message.member)

    def _message_update(self, payload: Mapping[str, Any]) -> None:
        """Mensagem editada — o caso mais famoso de payload parcial.

        Editar só o embed numa mensagem com conteúdo manda o payload
        **sem** `content`. Gravar por cima apagaria a mensagem inteira e
        deixaria o texto vazio — numa edição que nem mexeu nele. O merge
        mantém o que não veio, que é exatamente o que não mudou.
        """
        novo = Message.from_payload(payload)
        if novo is None:
            return
        antigo = self._state.get_message(novo.id)
        if antigo is None:
            # Nunca vimos — não dá para juntar com o que não temos, e
            # guardar só o que chegou é honesto: é o que se sabe.
            self._state._put_message(novo)
        else:
            self._state._put_message(_merge(antigo, novo, payload))

        if novo.author is not None:
            self._state._put_user(novo.author)
        if novo.member is not None and novo.guild_id is not None:
            self._state._put_member(novo.guild_id, novo.member)

    def _message_delete(self, payload: Mapping[str, Any]) -> None:
        """Mensagem apagada — só o ID importa.

        Sem falta na métrica se não estava guardada (`messages` começa
        desligado): apagar algo que nunca foi cacheado é o caso normal,
        não uma falha do cache.
        """
        message_id = _id(payload)
        if message_id is not None:
            self._state._drop_message(message_id)

    def _message_delete_bulk(self, payload: Mapping[str, Any]) -> None:
        """`MESSAGE_DELETE_BULK` — limpeza de canal, um `ids` com vários."""
        ids = payload.get("ids")
        if not isinstance(ids, list):
            return
        for bruto in ids:
            if isinstance(bruto, str) and bruto.isdigit():
                self._state._drop_message(int(bruto))
            elif isinstance(bruto, int) and not isinstance(bruto, bool):
                self._state._drop_message(bruto)

    # ------------------------------------------------------------------
    # Voz
    # ------------------------------------------------------------------

    def _voice_state_update(self, payload: Mapping[str, Any]) -> None:
        """Alguém entrou, saiu ou mudou de canal de voz.

        A entrada **não** é removida quando o usuário sai — `channel_id`
        vira nulo, que é "fora da voz", e o estado continua guardado. É
        o que permite o próximo evento devolver este como `old` e o
        handler ver de qual canal ele saiu (`0025` §6).

        Remoção só quando a guild sai do bot: `_drop_guild_children`
        faz isso, porque não há `VOICE_STATE_REMOVE` — voz se comunica
        pelo mesmo `VOICE_STATE_UPDATE`, e apagar a entrada cedo
        demais faria `old` virar `None` no meio de uma sessão.
        """
        voice_state = VoiceState.from_payload(payload)
        if voice_state is None:
            return
        self._state._put_voice_state(voice_state)


# ----------------------------------------------------------------------
# Auxiliares
# ----------------------------------------------------------------------


def _canal_no_guild(bruto: Mapping[str, Any], guild_id: int) -> Channel | None:
    """Um canal de dentro do `GUILD_CREATE`, completando a guild pelo contexto.

    **Não é defesa — é o caminho real.** Confirmado ao vivo contra o
    gateway do Discord: `24/24` canais de um `GUILD_CREATE` vieram sem
    `guild_id`. O array está dentro do objeto da guild e o Discord não
    repete a pergunta.

    Sem isto, todos os canais iriam para o cache agrupados como `None`
    e a guild apareceria com **zero canais** num evento que os manda
    todos de uma vez — que parece (e é tratado como) política
    desligada, que é o sintoma de erro mais confuso desta camada.

    Só preenche quando faltou: um `guild_id` que veio é a verdade, e
    sobrescrevê-lo seria decidir contra o payload.
    """
    channel = Channel.from_payload(bruto)
    if channel is None:
        return None
    if channel.guild_id is None:
        return replace(channel, guild_id=guild_id)
    return channel


def _voz_no_guild(bruto: Mapping[str, Any], guild_id: int) -> VoiceState | None:
    """Um estado de voz de dentro do `GUILD_CREATE`, completando a guild.

    Mesmo motivo do `_canal_no_guild`, e confirmado da mesma forma: o
    array está dentro do objeto da guild e não diz de qual é. Sem
    preencher, o `_put_voice_state` descartaria o estado (sem guild não
    há chave), e a guild chegaria com zero pessoas em voz num evento que
    traz justamente quem está.

    Só preenche quando faltou — um `guild_id` que veio é a verdade.
    """
    voice_state = VoiceState.from_payload(bruto)
    if voice_state is None:
        return None
    if voice_state.guild_id is None:
        return replace(voice_state, guild_id=guild_id)
    return voice_state


def _merge(antigo: T, novo: T, payload: Mapping[str, Any]) -> T:
    """Junta `novo` em `antigo` usando o payload para decidir o que mudou.

    Só campos **presentes** no JSON são copiados. É a diferença entre
    "o Discord disse que `pinned` é `True`" e "`pinned` não veio e
    parseou como `False`" — a segunda leitura apagaria o estado que se
    tinha, e `from_payload` não guarda a distinção entre ausente e
    falso. O payload guarda.

    `init=False` é pulado porque `dataclasses.replace` não aceita
    gravá-los — e se não dá para reatribuir, não é campo que este merge
    tem poder de mudar.

    Os dois `cast(Any, ...)` são o preço de `T` ser um `TypeVar`
    comum: `fields()` e `replace()` pedem `DataclassInstance`, do
    typeshed, e não existe sintaxe para dizer "`T` é dataclass" em
    Python. É conversão de anotação, não de valor — os modelos entram
    e saem inteiros, e o `cast(T, ...)` de volta mantém cada chamador
    tipado, que é o que o `T` existia para garantir.
    """
    bruto = cast(Any, antigo)
    mudancas: dict[str, Any] = {}
    for campo in fields(bruto):
        if not campo.init:
            continue
        # Nome no JSON pode não ser o nome no model. A regra não muda —
        # o que decide é o payload, e aqui só traduzimos para achar a
        # chave: `edited_timestamp` e `positions` existem, o campo é
        # outro. Sem isto, uma mensagem editada ficaria com
        # `edited_at` antigo para sempre, e é um dos campos que mais se
        # olha.
        origem = _RENOMES.get(campo.name, campo.name)
        if origem in payload:
            mudancas[campo.name] = getattr(novo, campo.name)
    if not mudancas:
        return antigo
    return cast(T, replace(bruto, **mudancas))


def _lista(payload: Mapping[str, Any], chave: str) -> list[Mapping[str, Any]]:
    """Os itens de um array do payload, só os que são objeto.

    Um array malformado não derruba o resto do evento: o guild chegou, e
    descartar tudo porque um cargo veio como string seria trocar dados
    bons por nada.
    """
    bruto = payload.get(chave)
    if not isinstance(bruto, list):
        return []
    return [item for item in bruto if isinstance(item, Mapping)]


def _id(payload: Mapping[str, Any]) -> int | None:
    """O `id` do payload, como int — ou `None` se não houver.

    `bool` é rejeitado antes de `int`, senão `True` vira o ID 1: um
    JSON com `id: true` é JSON quebrado, não um servidor chamado 1.
    """
    bruto = payload.get("id")
    if isinstance(bruto, str) and bruto.isdigit():
        return int(bruto)
    if isinstance(bruto, int) and not isinstance(bruto, bool):
        return bruto
    return None


def _payload_guild_id(payload: Mapping[str, Any]) -> int | None:
    """A guild dos eventos soltos de membro e cargo.

    Existe só no envelope desses eventos, nunca dentro do objeto de
    membro ou cargo — é o Discord dizendo "isto aconteceu aqui", e sem
    ele não há para onde gravar.
    """
    bruto = payload.get("guild_id")
    if isinstance(bruto, str) and bruto.isdigit():
        return int(bruto)
    if isinstance(bruto, int) and not isinstance(bruto, bool):
        return bruto
    return None
