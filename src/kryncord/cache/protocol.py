"""A interface que toda implementação de cache precisa cumprir.

Síncrono, e é uma decisão, não uma omissão. Um `await` em `get()` seria
o preço de permitir Redis, e o custo seria cobrado em **todo** handler
do bot — inclusive nos que nunca vão usar backend remoto — além de
pôr I/O no caminho do dispatcher, que hoje é só parse e dict.

Quem quiser Redis constrói a camada de estado dele por fora, como
discord.js e discord.py fazem: o protocolo cobre o que é em memória,
que é o que a biblioteca entrega. Se um dia houver um segundo backend,
a superfície já existe — mas não se paga o `await` hoje por uma
promessa de amanhã.

## Dois formatos de leitura, de propósito

`values()` devolve tudo de um tipo; `group_values()` devolve só os de
uma guild. Sem a segunda, "membros desta guild" seria uma varredura em
todas as chaves de membro de todos os servidores — o custo de uma guild
de cem mil membros pagando por todas as outras. Com ela, o backend
resolve direto (Redis: um `SMEMBERS`).

## `None` significa "não está guardado"

Ninguém grava `None`: o que se guarda é modelo parseado, e modelo que
não parseou não existe. Então `get()` devolvendo `None` é falta, sem
ambiguidade — não há `None` legítimo para confundir.

`stats` faz parte do protocolo porque métrica é responsabilidade de
quem guarda: quem lê não tem como saber se um `None` foi falta de
chave ou de política.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from kryncord.cache.keys import CacheKind
from kryncord.cache.policy import CachePolicy
from kryncord.cache.stats import CacheStats


@runtime_checkable
class CacheProtocol(Protocol):
    """Armazenamento de cache por tipo e chave."""

    @property
    def policy(self) -> CachePolicy:
        """A política que este armazenamento obedece.

        Faz parte do protocolo porque a política **é** o armazenamento
        dizendo o que aceita. Tirá-la daqui faria `ConnectionState`
        perguntar ao chamador "está ligado?" — e com um cache trocado,
        a resposta viria do lugar errado.
        """
        ...

    @property
    def stats(self) -> CacheStats:
        """Métrica viva de acertos, faltas, remoções e tamanho."""
        ...

    def get(self, kind: CacheKind, key: str) -> Any | None:
        """Devolve o valor, ou `None` se não estiver guardado.

        Sempre conta acerto ou falta — inclusive quando a política
        desligou o tipo. Quem chama `get_member()` recebeu `None`, e a
        métrica tem que dizer isso: um `hit_rate` ruim porque a
        política não cobre o tipo é o sintoma certo, e some assim que
        alguém ligar o campo.
        """
        ...

    def set(self, kind: CacheKind, key: str, value: Any, *, group: str | None = None) -> None:
        """Guarda um valor.

        `group` é a guild de origem, para `group_values()` depois.
        `None` (como nas contas e nos canais de DM) é o caso de quem
        não pertence a guild nenhuma — e é o valor, não a ausência.

        Se a política desligar o tipo, a chamada é ignorada: gravar é
        trabalho de quem decide o que entra, e a decisão é da política.
        """
        ...

    def pop(self, kind: CacheKind, key: str) -> Any | None:
        """Remove e devolve, ou `None` se não estava lá.

        Não conta falta: apagar algo que não existia é a resposta certa
        para `MESSAGE_DELETE` de mensagem que nunca foi cacheada, e
        puni-lo como falha faria a métrica dizer que o cache está ruim
        quando ele está apenas incompleto — que é o estado normal.
        """
        ...

    def values(self, kind: CacheKind) -> tuple[Any, ...]:
        """Todos os valores de um tipo, em ordem interna.

        Para tipos com teto (LRU), a ordem é do menos ao mais
        recentemente usado. Quem quer histórico de mensagem usa a REST,
        com cursor — o cache é para *estado*, não para arquivo.
        """
        ...

    def group_values(self, kind: CacheKind, group: str) -> tuple[Any, ...]:
        """Valores de um tipo dentro de um grupo (uma guild)."""
        ...

    def clear(self, kind: CacheKind | None = None) -> None:
        """Esvazia um tipo, ou tudo quando `kind` é `None`.

        Contadores ficam: esvaziar o cache não é esquecer o que ele
        acertou.
        """
        ...
