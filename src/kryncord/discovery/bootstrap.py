"""`bootstrap` — monta o registry e devolve o `Client`, sem ligar nada.

A ordem é a do `0019`, corrigida pelo `0027` §1: **imports →
`before_load` → devolve**. O chamador é quem chama `client.start()` —
o ciclo de vida é dele (`K4`: sem sync automático, e o `bootstrap` não
sobe o bot nem publica comando nenhum.

```python
client = await bootstrap(
    modules=["mybot.commands.**", "mybot.events"],
    load_logs=True,
    before_load=antes,
)
await client.start()
```

`bootstrap` é `async` porque `before_load` aceita função assíncrona, e
um `bootstrap` síncrono não tem onde esperá-la. Esse hook é justamente o
caso de uso que existe: preparar banco, aquecer cache, carregar config
externa — tudo `await`, tudo antes do `ready`.

## O que ele **não** faz

| Não faz | Por quê |
|---|---|
| `client.start()` | o ciclo de vida é do chamador (`01` §6) |
| `sync()` de comandos | `K4` — sync explícito, e são 2/hora por escopo |
| Relatório de retorno | `client.commands.instances()` já responde (`0019`) |
| Auto-corrigir circular | magia; o usuário precisa ver a pilha (`0027` §6) |

## Descoberta nunca é obrigatória

`import mybot.commands` continua registrando tudo. O `bootstrap` é açúcar
para quem não quer escrever `__init__.py` gigante.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any

from kryncord.client import Client
from kryncord.config import Config
from kryncord.discovery.loader import importa, resolve_todos
from kryncord.intents import Intents
from kryncord.logging import get_logger

#: Logger do `load_logs`. É `kryncord.discovery` — e não `__name__` —,
#: porque a decisão (`0027` §7) amarra a saída a esse nome: é o que faz
#: `logging.getLogger("kryncord.discovery").setLevel(...)` configurável
#: de fora, sem o usuário ter que descobrir qual submódulo emite.
_log = get_logger("kryncord.discovery")

BeforeLoad = Callable[[Client], Any]


async def bootstrap(
    *,
    modules: Sequence[str] = (),
    load_logs: bool = True,
    before_load: BeforeLoad | None = None,
    client: Client | None = None,
) -> Client:
    """Importa os módulos do padrão, roda `before_load` e devolve o `Client`.

    | Parâmetro | Padrão | Significado |
    |---|---|---|
    | `modules` | `()` | padrões de **ponto de importação** |
    | `load_logs` | `True` | conta o que entrou, por módulo |
    | `before_load` | `None` | roda **depois** dos imports, com o `Client` |
    | `client` | `None` | o seu, se quiser construir. Senão um `Client(Config())` |

    O `Client` criado por omissão vem com `Config(intents=Intents.default())`
    — ou seja, sem token. É proposital: `client.run(token)` preenche
    `Config.token` quando está vazio (`0026` §9), então o fluxo curto é
    `bootstrap(...)` → `client.run(os.environ["DISCORD_TOKEN"])`. Quem já
    tem um `Config` montado passa `client=Client(config)`.

    Falha de import **propaga**, com o padrão de origem e a causa na
    cadeia (`0027` §5). Um `**` de 40 módulos não pode falhar em silêncio
    nem apontar o módulo errado.
    """
    alvo = client if client is not None else Client(Config(intents=Intents.default()))

    nomes, origem = resolve_todos(modules)
    for nome in nomes:
        importa(nome, origem[nome])

    if before_load is not None:
        resultado = before_load(alvo)
        if inspect.isawaitable(resultado):
            await resultado

    if load_logs:
        _registra(nomes, alvo)

    return alvo


def _registra(nomes: Sequence[str], cliente: Client) -> None:
    """O `load_logs` — conta por módulo, **depois** de tudo (`0027` §7).

    Agrupar depois, e não contar delta antes/depois de cada import, é o
    que sobrevive a um módulo que registra com o handler definido em
    outro — re-export comum em `__init__.py`. Contagem por delta
    atribuiria o comando a quem importou, não a quem o escreveu.

    Módulo que registrou **zero** continua aparecendo: "não apareceu" é
    a informação que o `0019` quis dar, e ela só existe quando a linha
    existe com o zero nela.
    """
    contagem: dict[str, list[int]] = {}
    for nome in nomes:
        contagem[nome] = [0, 0]

    for instancia in cliente.commands.instances():
        modulo = _modulo_do_comando(instancia)
        contagem.setdefault(modulo, [0, 0])[0] += 1

    for entrada in cliente.responders.entries():
        modulo = _modulo(entrada.handler)
        contagem.setdefault(modulo, [0, 0])[1] += 1

    total_comandos = 0
    total_responders = 0
    for modulo in sorted(contagem):
        comandos, responders = contagem[modulo]
        total_comandos += comandos
        total_responders += responders
        _log.info(
            "[%s] %s, %s",
            modulo,
            _plural(comandos, "comando"),
            _plural(responders, "responder"),
        )

    _log.info(
        "carregados %s, %s, %s",
        _plural(len(nomes), "módulo"),
        _plural(total_comandos, "comando"),
        _plural(total_responders, "responder"),
    )


def _plural(quantidade: int, singular: str) -> str:
    """`1 comando`, `3 comandos` — o log é lido por gente.

    `plural` do Python faria `1 comandos`, e um log que erra o próprio
    texto ensina a desconfiar do resto.
    """
    if quantidade == 1:
        return f"{quantidade} {singular}"
    return f"{quantidade} {singular}s"


def _modulo(func: Any) -> str:
    """De qual módulo este handler veio.

    `handler.__module__`, e não o módulo que estava importando quando o
    registro aconteceu — a diferença é exatamente o caso do
    `__init__.py` que só re-exporta (`0027` §7).
    """
    modulo = getattr(func, "__module__", None)
    if not isinstance(modulo, str) or not modulo:
        return "<sem módulo>"
    return modulo


def _modulo_do_comando(instancia: Any) -> str:
    """O módulo de um comando — o do handler da raiz, se ele existe.

    A raiz é o que o dispatcher chama primeiro, e é o que o usuário
    escreveu como "o comando". Sem raiz (a âncora legítima da ideia
    04 §6), cai no primeiro filho que existir: o comando continua sendo
    daquele módulo, mesmo que a função esteja noutra parte da árvore.
    """
    candidatos = [instancia.handler, *instancia.subcommands.values()]
    for grupo in instancia.groups.values():
        candidatos.extend(grupo.values())

    for candidato in candidatos:
        if candidato is not None:
            return _modulo(candidato)
    return "<sem handler>"


__all__ = ["bootstrap"]
