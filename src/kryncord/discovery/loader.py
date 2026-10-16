"""Do padrão de importação aos nomes de módulo — e só depois o import.

Dois passos separados, e a separação é o ponto (`0027` §2):

| Passo | Função | Efeito |
|---|---|---|
| Resolver | `resolve(padrao)` | **nenhum** |
| Carregar | `importa(nome, padrao)` | executa o módulo |

Resolver é puro de verdade, e não "quase puro": a base é localizada com
`find_spec`, e os filhos são varridos com `pkgutil.iter_modules` sobre
**diretórios**, um nível por vez. Nenhum dos dois executa o módulo que
casou — ou seja, a varredura não roda `__init__.py` dos pacotes que o
padrão não casa, que era o problema do `pkgutil.walk_packages`.

O caminho de diretorio a diretorio existe por um motivo que só aparece
quando o padrão tem neto: `find_spec("mybot.a.b.c")` importa `mybot.a.b`
para achar `c`. Com `pacote_teste.**`, isso importaria `pacote_teste.sub`
durante a **resolução** — e o import executado antes da fase de import
quebraria a garantia de ordem do `0019`, que é justamente o que existe
para garantir. `iter_modules` sobre o diretório do pai não tem esse
efeito, e ainda assim lista o mesmo conjunto.

O que a resolução pode executar é o **ancestral** da base, quando a base
é um submódulo — `mybot.tools` não existe sem que `mybot` tenha sido
importado, e isso é como o Python funciona, não efeito colateral nosso.

## `.py` é sintaxe, não caminho

`mybot.tools.*_mod.py` perde o `.py` **antes** de qualquer parse, e o que
sobra é um padrão de módulo com curinga de um segmento. O padrão é sempre
de **ponto de importação**, nunca de caminho — o `K5` proíbe a barra
justamente porque `bot testes/` tem espaço e não vira pacote nunca. O
loader internamente percorre diretório para não importar nada, mas isso
é como ele faz, e não o que o usuário escreve.

Ver `0027` §3 para a tabela de sintaxe completa.
"""

from __future__ import annotations

import fnmatch
import importlib
import importlib.util
import os
import pkgutil
import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec

from kryncord.logging import get_logger

_log = get_logger("kryncord.discovery.loader")


def resolve(padrao: str) -> tuple[str, ...]:
    """Os nomes de módulo que o padrão casou — **sem importar nada**.

    Puro: mesma entrada, mesma saída, sem `sys.modules` mutado pelo que
    a varredura descobre. É o que permite cobrir a sintaxe do glob num
    teste unitário, que é o que a ideia 01 §8 pede.

    Levanta `ModuleNotFoundError` quando a **base** do padrão não existe
    — é erro de digitação, e o loader sabe o nome (`0027` §8). Devolver
    `()` nesse caso esconderia o typo atrás de um bot que simplesmente
    não registrou nada.

    Devolve `()` quando a base existe mas nenhum filho casa: é o caso
    legítimo do `*_mod.py` (`B1`), onde o glob existe para poder ser
    agressivo sem arrastar módulo errado — obrigar a criar um arquivo
    vazio seria punir quem usou o recurso direito.
    """
    alvo = _sem_py(padrao)
    partes = alvo.split(".")
    primeiro_curinga = next(
        (i for i, parte in enumerate(partes) if parte == "**" or "*" in parte),
        len(partes),
    )
    base = ".".join(partes[:primeiro_curinga])

    espec = _spec_de(base, padrao)

    # Padrão exato: existe → é ele; não existe → o `_spec_de` já
    # levantou. Não há varredura a fazer.
    if primeiro_curinga == len(partes):
        return (base,)

    if not espec.submodule_search_locations:
        # A base é um módulo, não pacote: não tem filhos para casar.
        # `()` e não erro — `mybot.main.*` não ter filho é informação,
        # não falha.
        return ()

    # `set` porque `**` alcança o mesmo nó por mais de um caminho quando o
    # padrão tem curinga depois dele. A ordenação sai de graça do
    # `sorted` — e ordem estável é o que o `bootstrap` precisa.
    resultado = _expande(
        base,
        list(espec.submodule_search_locations),
        partes[primeiro_curinga:],
    )
    return tuple(sorted(set(resultado)))


def importa(nome: str, padrao: str) -> None:
    """Executa um módulo, com o padrão de origem na mensagem de falha.

    Dois erros diferentes, e as duas mensagens dizem coisas
    diferentes (`0027` §5 e §6):

    * falha comum → `ImportError` citando **módulo e padrão**, com
      `from exc` para o traceback original continuar na cadeia;
    * circular → o apontamento do `0019`, que sugere a ordem explícita.
      Não é auto-correção: é mostrar a saída.
    """
    try:
        importlib.import_module(nome)
    except Exception as exc:
        raise _falha(nome, padrao, exc) from exc


def resolve_todos(padroes: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    """Resolve todos os padrões e devolve `(nomes ordenados, origem)`.

    A origem é `nome → padrão` — sem ela, uma falha num `**` de 40
    módulos não diria qual dos 40 falhou nem qual padrão o trouxe.

    A ordenação é por profundidade com desempate alfabético
    (`0027` §4): pai antes de filho é a garantia do `0019`, e o
    desempate é o que faz o `load_logs` ser estável entre execuções —
    sem ele, dois irmãos trocariam de lugar e o log pareceria mudar
    sem motivo.
    """
    nomes: set[str] = set()
    origem: dict[str, str] = {}

    for padrao in padroes:
        achados = resolve(padrao)
        if not achados:
            _log.debug("padrão %r não casou módulo algum", padrao)
        for nome in achados:
            nomes.add(nome)
            origem.setdefault(nome, padrao)

    ordenados = sorted(nomes, key=lambda n: (n.count("."), n))
    return ordenados, origem


# ---------------------------------------------------------------------------
# A varredura
# ---------------------------------------------------------------------------


def _expande(
    nome: str,
    diretorios: Sequence[str],
    segmentos: list[str],
) -> list[str]:
    """Nomes sob `nome` (com seus diretórios) que casam `segmentos`.

    Curinga fechado (`0027` §3):

    * `**` = **zero ou mais** segmentos. Zero é `nome` mesmo; um ou mais
      é descer em cada filho e tentar de novo com `**` ainda ativo — é
      assim que `mybot.commands.**` inclui o próprio pacote e tudo
      abaixo dele.
    * `*` (e `*_mod`) = **um** segmento, casado por `fnmatch`. Não
      inclui o pacote: ele é "os filhos", e incluir o pai duplicaria
      tudo que o `**` já traz.
    * literal = o segmento tem que existir de fato.

    Filho sem diretório é módulo: ele não tem o que varrer, e passar
    `[]` é o que faz `mybot.main.*` devolver `()` sem precisar de um
    caso especial no fim.
    """
    if not segmentos:
        return [nome]

    atual, *resto = segmentos
    filhos = _filhos(nome, diretorios)

    if atual == "**":
        # Zero segmentos: o próprio nó casa com o resto.
        saida = _expande(nome, diretorios, resto)
        # Um ou mais: desce com `**` ainda ativo.
        for completo, _curto, diretorios_do_filho in filhos:
            saida.extend(_expande(completo, diretorios_do_filho, segmentos))
        return saida

    saida = []
    for completo, curto, diretorios_do_filho in filhos:
        if "*" in atual:
            if fnmatch.fnmatch(curto, atual):
                saida.extend(_expande(completo, diretorios_do_filho, resto))
        elif curto == atual:
            saida.extend(_expande(completo, diretorios_do_filho, resto))
    return saida


def _filhos(nome: str, diretorios: Sequence[str]) -> list[tuple[str, str, list[str]]]:
    """`(nome completo, nome curto, diretórios dos netos)` dos filhos diretos.

    Varre **diretório**, um nível por vez, e não `find_spec` por nome.
    A diferença não é estética: `find_spec("a.b.c")` importa `a.b` para
    achar `c`, e isso executaria um pacote durante a resolução — antes
    da fase de import, quebra a garantia de ordem do `0019`, que é
    exatamente o que o `sorted` por profundidade existe para garantir.

    Um só `find_spec` acontece em todo o caminho, e é o da base, onde é
    inevitável: `mybot.tools` não existe sem `mybot` importado.

    `iter_modules` sobre `[diretorio]` é o que lista sem importar; ele
    já distingue pacote de módulo, e é esse o bit que decide se o filho
    tem diretório próprio para descer.
    """
    saida: list[tuple[str, str, list[str]]] = []
    for diretorio in diretorios:
        if not os.path.isdir(diretorio):
            continue
        for _finder, completo, pacote in pkgutil.iter_modules([diretorio], prefix=nome + "."):
            curto = completo.rsplit(".", 1)[-1]
            if pacote:
                # O `submodule_search_locations` de um pacote regular é
                # este diretório — calcular na mão evita o `find_spec`
                # que traria o efeito de volta.
                saida.append((completo, curto, [os.path.join(diretorio, curto)]))
            else:
                saida.append((completo, curto, []))
    return saida


def _spec_de(base: str, padrao: str) -> ModuleSpec:
    """A `ModuleSpec` da base, ou `ModuleNotFoundError` citando o padrão.

    A base é a parte do padrão antes do primeiro curinga — o nome que o
    loader **sabe** que existe ou não. Sem ela na mensagem, um typo em
    `mybot.comands.**` viraria um padrão que "não casou nada", que é o
    mesmo sintoma de um pacote legítimo ainda vazio.
    """
    if not base:
        raise ModuleNotFoundError(
            f"padrão {padrao!r} sem nome de pacote base — o padrão precisa "
            "começar por um nome de importação, não por curinga"
        )
    try:
        espec = importlib.util.find_spec(base)
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"padrão {padrao!r}: o pacote base {base!r} não existe — {exc}"
        ) from exc
    except (ImportError, ValueError) as exc:
        # `find_spec` também reclama de nome inválido (`a/b`, vazio),
        # com `ValueError` ou `ImportError` conforme a versão. O que o
        # usuário precisa saber é o mesmo nos dois casos: aquele nome
        # não é um pacote que dá para localizar.
        raise ModuleNotFoundError(
            f"padrão {padrao!r}: o pacote base {base!r} não é um nome de importação válido — {exc}"
        ) from exc
    if espec is None:
        raise ModuleNotFoundError(f"padrão {padrao!r}: o pacote base {base!r} não existe")
    return espec


def _sem_py(padrao: str) -> str:
    """Tira o sufixo `.py`, que marca padrão de arquivo (`0027` §3).

    Sai **antes** de parser: `mybot.tools.*_mod.py` vira
    `mybot.tools.*_mod`, e o que sobra é padrão de módulo com curinga de
    um segmento. `.py` nunca vira caminho — é marcador de sintaxe.
    """
    if padrao.endswith(".py"):
        return padrao[:-3]
    return padrao


def _falha(nome: str, padrao: str, exc: Exception) -> Exception:
    """A exceção certa para um import que falhou, dentro do `except`.

    Construída **aqui**, de dentro do `try`, para a pilha original ficar
    visível na cadeia: `from exc` faz o Python imprimir "The above
    exception was the direct cause" em cima do que aconteceu de fato.
    """
    if _circular(exc):
        raiz = nome.split(".")[0]
        return ImportError(
            f"{nome} está em importação circular, resolvido do padrão "
            f"{padrao!r}. Auto-correção seria magia: quem escreveu o ciclo "
            f'é quem decide a ordem — `bootstrap(modules=["{raiz}.core", ...])` '
            "com o pai antes do filho, que é o que o `bootstrap` ordena "
            "por profundidade."
        )
    return ImportError(f"falha ao importar {nome!r}, resolvido do padrão {padrao!r}: {exc}")


def _circular(exc: BaseException) -> bool:
    """Se o Python está reclamando de import circular (`0027` §6).

    Dois indícios, porque são duas as formas de o Python falar disso:

    * a mensagem que ele dá sozinho — `cannot import name ... from
      partially initialized module`;
    * um `ModuleNotFoundError` cujo nome parcial **já está** em
      `sys.modules`: se está lá e ainda faltou, é porque estava no
      meio do import.
    """
    if "partially initialized module" in str(exc):
        return True
    if isinstance(exc, ModuleNotFoundError):
        parcial = getattr(exc, "name", None)
        if isinstance(parcial, str) and parcial and parcial in sys.modules:
            return True
    return False


__all__ = ["importa", "resolve", "resolve_todos"]
