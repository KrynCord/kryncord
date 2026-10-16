"""Estado de domínio da conexão: quem eu sou e o que o gateway entregou.

Este é o `client.cache`. Duas decisões travadas na escolha do nome:

## Não é a sessão do Gateway

`gateway/session.py` já tem `SessionInfo` (session_id, sequence,
resume_url) — é estado de **transporte**, existe para o `RESUME`
funcionar, e pertence ao transporte. Duplicar aqui seria a segunda fonte
de verdade que a arquitetura §1 proíbe: um `session_id` divergindo entre
os dois módulos seria o bug menos diagnosticável da biblioteca.

Aqui é outra coisa. `SessionInfo` responde "de onde continuo?"; isto
responde "quem eu sou, e o que já chegou". Estado de domínio, não de
conexão no sentido de socket.

## Leitura e escrita no mesmo objeto

`get_*` e `put_*` convivem porque são a mesma questão vista dos dois
lados: o que está guardado. `event_updates.py` decide *o que* um evento
significa; este módulo sabe *onde* aquilo entra — a chave, o agrupamento
e a política. Separar em dois objetos repartiria o conhecimento da
chave, e a chave errada não é um erro que se vê: é um `get` que devolve
`None` sempre, parecendo política desligada.

## O `me` não é item de cache

É o único dado aqui que **não** pode sumir. O `users` é LRU — sem
evento de remoção no Discord, só o limite resolve —, e numa sessão longa
o próprio bot seria derrubado por cem mil mensagens de terceiros.
`me` fica em campo próprio, fora do repositório, e não passa pelo LRU
porque "quem eu sou" não é uma pergunta que pode ter resposta vazia.

É também o que dá sentido ao nome do arquivo: é estado da conexão no
sentido de *quem está conectado*.
"""

from __future__ import annotations

from typing import Any

from kryncord.cache.keys import (
    CacheKind,
    channel_key,
    guild_key,
    member_key,
    message_key,
    role_key,
    user_key,
    voice_state_key,
)
from kryncord.cache.memory import MemoryCache
from kryncord.cache.policy import CachePolicy
from kryncord.cache.protocol import CacheProtocol
from kryncord.cache.stats import CacheStats
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.role import Role
from kryncord.models.user import User
from kryncord.models.voice import VoiceState
from kryncord.state.guild_state import GuildState


class ConnectionState:
    """O que o bot sabe sobre o Discord, sem perguntar de novo.

    Leituras (`get_*`, iterações, `stats`) e escritas (`put_*`, `drop_*`)
    estão juntas por serem a mesma questão — o que está guardado. Quem
    só lê nunca vê os `put_*`; quem escreve (`event_updates`) nunca
    reimplementa a chave.
    """

    __slots__ = ("_cache", "_me")

    def __init__(
        self,
        cache: CacheProtocol | None = None,
        *,
        policy: CachePolicy | None = None,
    ) -> None:
        """Um cache pronto, ou uma política para construir o nosso.

        Os dois juntos são erro, não preferência: quem passa um `cache`
        já embutiu a política dentro dele, e ignorar o `policy` faria uma
        configuração do usuário não efeito nenhum — o tipo de falha que
        só aparece quando alguém já confou no resultado.
        """
        if cache is not None and policy is not None:
            raise ValueError(
                "passe `cache` ou `policy`, nunca os dois: a política de "
                "um cache pronto já vive dentro dele"
            )
        self._cache: CacheProtocol = cache if cache is not None else MemoryCache(policy)
        self._me: User | None = None

    # ------------------------------------------------------------------
    # O armazenamento
    # ------------------------------------------------------------------

    @property
    def cache(self) -> CacheProtocol:
        """A implementação por baixo — para quem for trocá-la ou inspecionar."""
        return self._cache

    @property
    def policy(self) -> CachePolicy:
        """A política que este cache obedece."""
        return self._cache.policy

    @property
    def enabled(self) -> bool:
        """Se algo está sendo guardado.

        A pergunta de um `log.info` ou de um guarda em código de
        usuário. `policy.enabled` é o caminho longo para a mesma
        resposta, e errar um dos dois nomes seria deixar dois jeitos de
        perguntar com respostas diferentes.
        """
        return self._cache.policy.enabled

    @property
    def stats(self) -> CacheStats:
        """Acertos, faltas, remoções e tamanho — do armazenamento."""
        return self._cache.stats

    @property
    def me(self) -> User | None:
        """O próprio bot, ou `None` antes do `READY`.

        Fora do repositório de usuários de propósito: `users` é LRU, e
        ele não pode ser derrubado. Só o `READY` preenche.
        """
        return self._me

    def set_me(self, user: User) -> None:
        """Grava quem o bot é — chamado pelo `READY` e pelo `USER_UPDATE`."""
        self._me = user

    # ------------------------------------------------------------------
    # Leitura pontual
    # ------------------------------------------------------------------

    def get_guild(self, guild_id: int | str) -> Guild | None:
        """Um servidor, ou `None`.

        `None` antes do `GUILD_CREATE` é o normal: o `READY` manda só
        ``id`` e ``unavailable``, e o objeto completo vem logo depois.
        """
        return self._cache.get(CacheKind.GUILD, guild_key(guild_id))

    def get_channel(self, channel_id: int | str) -> Channel | None:
        """Um canal, ou `None`. ID global — não precisa de guild.

        Canal de DM entra aqui normalmente (`guild_id=None`), e é a
        única leitura que serve para ele.
        """
        return self._cache.get(CacheKind.CHANNEL, channel_key(channel_id))

    def get_user(self, user_id: int | str) -> User | None:
        """Uma conta, ou `None`.

        LRU com teto — não existe `USER_DELETE` no Discord, então sem
        limite esta lista cresceria para sempre. Quem não está aqui
        pode ser antigo, não necessariamente inexistente.
        """
        return self._cache.get(CacheKind.USER, user_key(user_id))

    def get_message(self, message_id: int | str) -> Message | None:
        """Uma mensagem, ou `None`.

        Pode simplesmente não estar, mesmo recém-chegada: `messages`
        começa desligado (`0`) por ser a única entidade que só chega.
        """
        return self._cache.get(CacheKind.MESSAGE, message_key(message_id))

    def get_member(self, guild_id: int | str, user_id: int | str) -> Member | None:
        """Quem é este usuário **nesta** guild, ou `None`.

        O lookup mais usado do cache — "quem mandou esta mensagem?" —
        e direto: a chave carrega as duas pontas, não há varredura.

        `None` significa qualquer uma das três coisas: a política
        desligou `members` (é o default), o gateway ainda não entregou,
        ou a pessoa não é membro. O `stats` diz qual.
        """
        return self._cache.get(CacheKind.MEMBER, member_key(guild_id, user_id))

    def get_role(self, guild_id: int | str, role_id: int | str) -> Role | None:
        """Um cargo desta guild, ou `None`.

        Não confundir com o cargo `@everyone`, cujo ID **é** o ID da
        guild — ele existe como cargo, mas raramente é cacheado.
        """
        return self._cache.get(CacheKind.ROLE, role_key(guild_id, role_id))

    def get_voice_state(self, guild_id: int | str, user_id: int | str) -> VoiceState | None:
        """Onde este usuário está na voz **desta** guild, ou `None`.

        `None` com um estado que existiu (ele estava na voz e saiu) é o
        caso que a política cobre: `channel_id` nulo é "saiu da voz", e o
        estado continua cacheado justamente para o próximo
        `voice_state_update` devolver este como `old` (`0025` §6).

        Fora disso: a política desligou `voice_states`, o gateway ainda
        não entregou, ou o usuário nunca entrou em voz.
        """
        return self._cache.get(CacheKind.VOICE_STATE, voice_state_key(guild_id, user_id))

    def guild(self, guild_id: int | str) -> GuildState | None:
        """Visão de uma guild, ou `None` se ela não está cacheada.

        `None` é o sinal de que não há o que olhar: a visão só existe
        se o servidor existir aqui. Devolver uma visão vazia para uma
        guild inexistente faria `state.members` parecer "servidor sem
        membros", que é outra afirmação — e falsa.
        """
        if self.get_guild(guild_id) is None:
            return None
        return GuildState(self._cache, int(guild_id))

    # ------------------------------------------------------------------
    # Leitura geral
    # ------------------------------------------------------------------

    @property
    def guilds(self) -> tuple[Guild, ...]:
        """Todos os servidores cacheados.

        Antes dos `GUILD_CREATE`, vêm só os stubs do `READY` —
        ``id`` + ``unavailable``, sem nome.
        """
        return self._cache.values(CacheKind.GUILD)

    @property
    def channels(self) -> tuple[Channel, ...]:
        """Todos os canais, **incluindo** os de DM.

        `guild_state.channels` é o recorte por servidor; este é o
        conjunto inteiro.
        """
        return self._cache.values(CacheKind.CHANNEL)

    @property
    def users(self) -> tuple[User, ...]:
        """Contas vistas — com teto LRU, e sem o próprio bot (`me`)."""
        return self._cache.values(CacheKind.USER)

    @property
    def messages(self) -> tuple[Message, ...]:
        """Mensagens em cache, da menos à mais recentemente usada.

        Não é histórico. Quer história, é a REST com cursor — este é o
        estado que sobrou de eventos recentes.
        """
        return self._cache.values(CacheKind.MESSAGE)

    @property
    def voice_states(self) -> tuple[VoiceState, ...]:
        """Estados de voz, de todos os servidores.

        Quem quer o recorte de uma guild usa `get_voice_state`; este é o
        conjunto inteiro, para quem quer listar "quem está em voz".
        """
        return self._cache.values(CacheKind.VOICE_STATE)

    def clear(self, kind: CacheKind | None = None) -> None:
        """Esvazia um tipo, ou tudo.

        `me` fica: apagar a memória não faz o bot esquecer quem ele é.
        Os contadores de `stats` também ficam — esvaziar dados não apaga
        o histórico de acertos.
        """
        self._cache.clear(kind)

    # ------------------------------------------------------------------
    # Escrita — o que `event_updates` chama
    #
    # Privadas com `_` de propósito: não é API de usuário. Quem mexer
    # aqui por fora está reescrevendo o que o gateway disse, e aí o
    # próximo evento conserta em cima de dado inventado.
    # ------------------------------------------------------------------

    def _put_guild(self, guild: Guild) -> None:
        """Grava um servidor (stub ou completo)."""
        self._cache.set(CacheKind.GUILD, guild_key(guild.id), guild)

    def _put_channel(self, channel: Channel) -> None:
        """Grava um canal, agrupado pela guild dele.

        DM tem `guild_id=None` e grupo `None` — não pertence a guild
        nenhuma, e é o valor, não a ausência. Só dá para enumerar por
        guild o que tem guild.
        """
        group = str(channel.guild_id) if channel.guild_id is not None else None
        self._cache.set(CacheKind.CHANNEL, channel_key(channel.id), channel, group=group)

    def _put_user(self, user: User) -> None:
        """Grava uma conta."""
        self._cache.set(CacheKind.USER, user_key(user.id), user)

    def _put_member(self, guild_id: int | str, member: Member) -> None:
        """Grava um membro numa guild.

        `guild_id` vem do **payload**, não do modelo: `Member` não tem
        esse campo, porque dentro de um `GUILD_CREATE` a lista de
        membros não traz de qual guild veio — é o array inteiro dentro
        do próprio objeto do servidor. O Discord completa com
        `guild_id` nos eventos soltos (`GUILD_MEMBER_ADD` etc), e em
        ambos os casos quem sabe é quem leu o evento.
        """
        self._cache.set(
            CacheKind.MEMBER,
            member_key(guild_id, member.user.id),
            member,
            group=str(guild_id),
        )

    def _put_role(self, guild_id: int | str, role: Role) -> None:
        """Grava um cargo numa guild.

        Mesmo motivo do membro: `Role` não tem `guild_id` — o objeto de
        cargo não carrega, quem entrega é o evento ou a guild.
        """
        self._cache.set(
            CacheKind.ROLE,
            role_key(guild_id, role.id),
            role,
            group=str(guild_id),
        )

    def _put_message(self, message: Message) -> None:
        """Grava uma mensagem.

        Sem grupo: mensagem não se enumera por guild, e o histórico vem
        da REST com cursor. Agrupar aqui seria índice sem leitor.
        """
        self._cache.set(CacheKind.MESSAGE, message_key(message.id), message)

    def _drop_guild(self, guild_id: int | str) -> None:
        """Tira um servidor do cache."""
        self._cache.pop(CacheKind.GUILD, guild_key(guild_id))

    def _drop_channel(self, channel_id: int | str) -> None:
        """Tira um canal (ou thread) do cache."""
        self._cache.pop(CacheKind.CHANNEL, channel_key(channel_id))

    def _drop_member(self, guild_id: int | str, user_id: int | str) -> None:
        """Tira um membro de uma guild — `GUILD_MEMBER_REMOVE`."""
        self._cache.pop(CacheKind.MEMBER, member_key(guild_id, user_id))

    def _drop_role(self, guild_id: int | str, role_id: int | str) -> None:
        """Tira um cargo de uma guild — `GUILD_ROLE_DELETE`."""
        self._cache.pop(CacheKind.ROLE, role_key(guild_id, role_id))

    def _drop_message(self, message_id: int | str) -> None:
        """Tira uma mensagem — `MESSAGE_DELETE`/`MESSAGE_DELETE_BULK`."""
        self._cache.pop(CacheKind.MESSAGE, message_key(message_id))

    def _put_voice_state(self, state: VoiceState) -> None:
        """Grava o estado de voz de um usuário numa guild.

        `VoiceState` **tem** `guild_id`, ao contrário de `Member` e
        `Role` — o payload de `VOICE_STATE_UPDATE` traz, e o do
        `GUILD_CREATE` não, que é por isso que ele vem agrupado na
        guild que o semeou.

        Sem `guild_id` não é gravado: voz só existe dentro de um
        servidor, e um estado sem guild não tem chave — guardá-lo sob um
        sentinela criaria uma entrada que ninguém consulta nem remove.
        """
        if state.guild_id is None:
            return
        self._cache.set(
            CacheKind.VOICE_STATE,
            voice_state_key(state.guild_id, state.user_id),
            state,
            group=str(state.guild_id),
        )

    def _drop_voice_state(self, guild_id: int | str, user_id: int | str) -> None:
        """Tira o estado de voz — o usuário saiu ou a guild sumiu."""
        self._cache.pop(CacheKind.VOICE_STATE, voice_state_key(guild_id, user_id))

    def _drop_guild_children(self, guild_id: int | str) -> None:
        """Tira tudo que pertence a uma guild: membros, cargos, canais, voz.

        Chamado junto com `_drop_guild` quando o bot **saiu** do
        servidor, e só nesse caso. Quando o `GUILD_DELETE` vem com
        ``unavailable: true`` é uma indisponibilidade temporária — o
        servidor continua existindo, e apagar os membros jogaria fora
        dados que o gateway não mandou de novo.

        Os canais saem porque a guild sumiu, não porque algum canal foi
        apagado: não há `CHANNEL_DELETE` para os canais de um servidor
        que deixou de existir para nós.
        """
        for member in self._cache.group_values(CacheKind.MEMBER, str(guild_id)):
            self._drop_member(guild_id, member.user.id)
        for role in self._cache.group_values(CacheKind.ROLE, str(guild_id)):
            self._drop_role(guild_id, role.id)
        for channel in self._cache.group_values(CacheKind.CHANNEL, str(guild_id)):
            self._drop_channel(channel.id)
        for voice_state in self._cache.group_values(CacheKind.VOICE_STATE, str(guild_id)):
            self._drop_voice_state(guild_id, voice_state.user_id)

    # ------------------------------------------------------------------
    # Inspeção
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Entradas guardadas, somando todos os tipos.

        `me` não conta: não é uma entrada, é a identificação de quem
        está conectado.
        """
        return self.stats.total_size

    def __repr__(self) -> str:
        """O que importa ao inspecionar: ligado, e quanto tem."""
        return f"{type(self).__name__}(enabled={self.enabled}, entries={len(self)})"

    def as_dict(self) -> dict[str, Any]:
        """Retrato dos dados, para log e depuração.

        Não é para serializar estado de volta — é para alguém ver o que
        o cache tem sem imprimir os modelos inteiros.
        """
        stats = self.stats
        return {
            "enabled": self.enabled,
            "me": self._me.id if self._me is not None else None,
            "guilds": len(self.guilds),
            "channels": len(self.channels),
            "users": len(self.users),
            "messages": len(self.messages),
            "voice_states": len(self.voice_states),
            "hit_rate": stats.hit_rate,
            "evictions": stats.total_evictions,
        }
