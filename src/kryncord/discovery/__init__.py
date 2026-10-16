"""Carregamento opcional de módulos do usuário.

Descoberta automática **nunca** é obrigatória. `import mybot.commands`
tem que continuar funcionando e registrando tudo. O `bootstrap` com glob
é açúcar para quem não quer escrever `__init__.py` gigante.

Dois módulos, e a divisão é o ponto (`0027` §2):

| Módulo | Papel |
|---|---|
| `loader` | `resolve` (puro, nenhum import) e `importa` (executa) |
| `bootstrap` | o `async def` público: imports → `before_load` → devolve |

`resolve` é puro de propósito: é o que faz a sintaxe do glob coberta por
teste unitário, sem `sys.path` e sem `sys.modules` mutado.

Ver `docs/decisions/0019-discovery-bootstrap.md` para o contrato e
`0027` para as correções que fecharam o que o `0019` deixou em aberto.
"""

from kryncord.discovery.bootstrap import bootstrap
from kryncord.discovery.loader import importa, resolve, resolve_todos

__all__ = ["bootstrap", "importa", "resolve", "resolve_todos"]
