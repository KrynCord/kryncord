"""O que entra no cache, e quanto cabe.

A arquitetura pede quatro políticas: desativado, mínimo, configurado
por entidade, e padrão com limites documentados. Este módulo é as
quatro — `disabled()`, o construtor padrão, os campos, e os números
abaixo.

## A divisão entre `bool` e `int`

Este é o ponto que decide a forma da classe, e não é estética:

* **`bool`** — a entidade tem **evento de remoção no gateway.**
  `GUILD_DELETE`, `CHANNEL_DELETE`, `GUILD_ROLE_DELETE`,
  `GUILD_MEMBER_REMOVE`. O Discord avisa quando algo deixa de existir,
  então o limite é a própria sessão: enquanto o bot estiver logado, o
  cache guarda, e quando o evento chegar, some. Colocar um número em
  cima jogaria fora memória que o gateway acabou de confirmar como
  válida.

* **`int`** — a entidade **não tem evento de remoção**, ou não adianta
  ter. Dois casos:

  - **`users`: não existe `USER_DELETE`.** Um usuário que mandou
    mensagem hoje continua existindo amanhã — e no cache ele não tem
    fim. Só o limite resolve.
  - **`messages`: existe `MESSAGE_DELETE`, mas ele quase nunca chega.**
    Mensagem não é apagada na proporção em que é criada. Sem limite,
    um servidor ativo cresce sem parar, que é exatamente o que a
    arquitetura §11 proíbe.

`0` como limite significa **desligado**, não "espaço para zero". É o
jeito de dizer "não guarda isto" sem inventar um quinto campo.

## O default

`members` e `messages` começam desligados, e é uma escolha, não
esquecimento: são os dois que crescem com o servidor. Um guild de cem
mil membros custa cem mil objetos de uma vez, e mensagem é a única
coisa que só entra. Quem precisa liga com uma linha::

    Config(intents=..., cache=CachePolicy(members=True, messages=2000))

O que **nunca** muda: `enabled=False` desliga tudo, sem importar os
campos. Um flag que os campos individuais sobrescrevem não é um flag —
é sugestão.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from kryncord.cache.keys import CacheKind

#: Quantos usuários ficam no cache. Sem evento de remoção, este é o
#: único teto — e 5000 cobre os autores recentes de um servidor ativo
#: sem virar uma lista de todo mundo que o bot já viu.
DEFAULT_USER_LIMIT = 5_000


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Quais entidades o cache guarda, e com que teto.

    Congelada: uma política que muda no meio do uso derrubaria itens já
    guardados sem avisar quem estava contando com eles.
    """

    #: Se tudo isto vale alguma coisa. `False` anula os campos abaixo.
    enabled: bool = True

    # ------------------------------------------------------------------
    # `bool` — invalidados por evento do gateway.
    # ------------------------------------------------------------------

    #: Servidores. Sai por `GUILD_DELETE`.
    guilds: bool = True

    #: Canais. Sai por `CHANNEL_DELETE`.
    channels: bool = True

    #: Cargos. Sai por `GUILD_ROLE_DELETE`.
    roles: bool = True

    #: Membros. Sai por `GUILD_MEMBER_REMOVE`.
    #:
    #: **Desligado por padrão**, e é o maior consumidor do cache: o
    #: `GUILD_CREATE` entrega a lista inteira de uma vez, e num guild
    #: grande são dezenas de milhares de objetos. `Member` é o que
    #: alguém quer resolver mais rápido (`get_member`), então ligar é
    #: uma linha — mas é quem decide pagar a memória.
    members: bool = False

    #: Estados de voz. Sai por `VOICE_STATE_UPDATE` com canal nulo.
    #:
    #: **Ligado por padrão**, ao contrário de `members`: o volume é a
    #: ocupação real de voz do guild (um por usuário em canal), não a
    #: base de membros — que é o que `GUILD_CREATE` entrega de uma vez.
    #: E é o único caminho em que `voice_state_update -> (old, new)` não
    #: mente (`0025` §6): sem guardar o estado anterior, `old` seria
    #: `None` para sempre dentro de uma assinatura que promete
    #: `VoiceState | None`.
    voice_states: bool = True

    # ------------------------------------------------------------------
    # `int` — sem evento de remoção, precisa de teto.
    # ------------------------------------------------------------------

    #: Contas, em quantidade. LRU: sai a mais antiga quando enche.
    users: int = DEFAULT_USER_LIMIT

    #: Mensagens, em quantidade. **`0` = não guarda.**
    #:
    #: Desligado por padrão pelo mesmo motivo de `members`, e por um
    #: segundo: mensagem é a única entidade que só chega. Um servidor
    #: com cem mensagens por minuto encheria qualquer número fixo.
    messages: int = 0

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    @classmethod
    def disabled(cls) -> Self:
        """Nada é guardado.

        O caminho de quem quer zero custo de memória, e o de teste —
        sem cache, nenhum teste depende do que ficou de uma rodada
        anterior.
        """
        return cls(enabled=False)

    @classmethod
    def full(cls) -> Self:
        """Tudo ligado, com teto documentado.

        `members=True` porque é o que se busca ao ligar isto, e
        `messages=2_000` porque o default é 0 e "full" sem mensagem não
        é full. O teto existe mesmo aqui: a arquitetura proíbe guardar
        indefinidamente, e "full" não é exceção.
        """
        return cls(members=True, messages=2_000)

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def limit_for(self, kind: CacheKind) -> int | None:
        """Teto de um tipo: número, ou `None` para "sem teto".

        `None` **não** é "desligado" — é a resposta para as entidades
        invalidadas por evento, cujo limite é a sessão. Desligado é
        `0`, e é o único valor que `allows` trata como falso.

        Um campo `bool` vira `None` (ligado, sem teto) ou `0`
        (desligado). Um campo `int` passa direto — é ele próprio o teto.
        """
        if not self.enabled:
            return 0
        value = self._field_for(kind)
        if isinstance(value, bool):
            return None if value else 0
        return value

    def allows(self, kind: CacheKind) -> bool:
        """Se o tipo é guardado.

        `limit_for(...) != 0`: `None` (sem teto) passa, `0` (desligado)
        não, número positivo passa. É uma pergunta, não uma aritmética
        — o `0` é o caso desligado, não um teto de zero lugares.
        """
        return self.limit_for(kind) != 0

    def _field_for(self, kind: CacheKind) -> bool | int:
        """O campo desta política que corresponde ao tipo."""
        if kind is CacheKind.GUILD:
            return self.guilds
        if kind is CacheKind.CHANNEL:
            return self.channels
        if kind is CacheKind.ROLE:
            return self.roles
        if kind is CacheKind.MEMBER:
            return self.members
        if kind is CacheKind.VOICE_STATE:
            return self.voice_states
        if kind is CacheKind.USER:
            return self.users
        return self.messages
