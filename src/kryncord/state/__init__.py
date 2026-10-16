"""Estado local do bot — o que o gateway já contou, guardado.

Três papéis, três arquivos, e a divisão não é de acaso:

- **`connection_state.py`** — `ConnectionState`, que é o `client.cache`.
  Quem eu sou (`me`), o que existe (`get_*`, iterações) e onde cada
  coisa entra (`put_*`, `drop_*`). Estado de domínio, **não** a sessão
  do Gateway: `gateway/session.py` tem `SessionInfo`, que responde "de
  onde continuo" para o `RESUME`, e é estado de transporte. Duas fontes
  para o mesmo dado seria o bug menos diagnosticável da biblioteca.

- **`guild_state.py`** — `GuildState`, a visão de uma guild já
  escopada. `members`, `roles`, `channels` só fazem sentido dentro de
  um servidor, então ficam aqui em vez de virarem `members(gid)` no
  objeto grande — dois nomes para a mesma coisa seria uma divergência
  esperando acontecer.

- **`event_updates.py`** — `EventUpdater`, que decide **o que** um
  evento significa e delega o **para onde** ao estado. Guardar sem
  reimplementar a chave, que é o erro que não se vê: um `get` que
  devolve `None` sempre, parecendo política desligada.

O armazenamento por baixo é `kryncord.cache` — aqui é só leitura,
escrita e semântica de evento.
"""

from kryncord.state.connection_state import ConnectionState
from kryncord.state.event_updates import EventUpdater
from kryncord.state.guild_state import GuildState

__all__ = [
    "ConnectionState",
    "EventUpdater",
    "GuildState",
]
