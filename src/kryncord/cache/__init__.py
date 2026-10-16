"""Cache opcional e política configurável.

O cache nunca assume que tem tudo — essa é a primeira frase da seção
correspondente na arquitetura, e é o que organiza o resto:

- **`protocol.py`** define a interface mínima que qualquer
  implementação precisa cumprir. Síncrona, de propósito: um `await` em
  `get()` seria cobrado de todo handler, e o dispatcher ganharia I/O no
  caminho que hoje é só parse e dict.
- **`memory.py`** é a implementação inicial — `OrderedDict` por tipo,
  teto LRU nos que precisam e índice por guild para enumeração sair em
  O(1) em vez de varrer tudo.
- **`policy.py`** decide o que entra. A divisão entre campo `bool` e
  campo `int` não é estética: `bool` é entidade que o gateway invalida
  sozinho, `int` é entidade que não tem evento de remoção e precisa de
  teto.
- **`keys.py`** cria as chaves — string, não tupla, para atravessar um
  backend que não seja dict.
- **`stats.py`** é a métrica: acertos, faltas, remoções e tamanho.

Um método REST continua funcionando quando a entidade não está aqui,
sempre que a API oficial permitir a operação. `None` de um `get` não é
erro: é o cache incompleto, que é o estado normal dele.
"""

from kryncord.cache.keys import (
    CacheKind,
    channel_key,
    guild_group,
    guild_key,
    member_key,
    message_key,
    role_key,
    user_key,
)
from kryncord.cache.memory import MemoryCache
from kryncord.cache.policy import DEFAULT_USER_LIMIT, CachePolicy
from kryncord.cache.protocol import CacheProtocol
from kryncord.cache.stats import CacheStats

__all__ = [
    "DEFAULT_USER_LIMIT",
    "CacheKind",
    "CachePolicy",
    "CacheProtocol",
    "CacheStats",
    "MemoryCache",
    "channel_key",
    "guild_group",
    "guild_key",
    "member_key",
    "message_key",
    "role_key",
    "user_key",
]
