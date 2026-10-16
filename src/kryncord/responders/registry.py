"""Registry de responders — registro na importação, conflito na cara.

Dois padrões que casam o mesmo id com tipos sobrepostos é um bug que
só dá para apontar **na importação**, quando os dois módulos ainda
estão carregando e o usuário está olhando (0013). No clique, seria
"às vezes responde um, às vezes o outro" — o pior tipo de bug, porque
não falha nunca, só erra.

`types` é filtro, não prioridade: o mesmo padrão com `MODAL_SUBMIT` e
com `BUTTON` são dois registros legítimos — o mesmo id em dois lugares
diferentes da interface. O que não pode é os dois brigando pelo mesmo
tipo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from kryncord.enums import ResponderType
from kryncord.errors import ResponderDefinitionError
from kryncord.logging import get_logger
from kryncord.responders.patterns import Padrao, conflitam

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResponderEntry:
    """Um responder registrado — tudo o que o dispatcher precisa."""

    padrao: Padrao
    handler: Callable[..., Any]
    types: frozenset[ResponderType]
    cache: str = "any"
    parse: Callable[..., Any] | None = None
    middleware: tuple[Callable[..., Any], ...] = ()
    module: str = ""

    @property
    def rota(self) -> str:
        return self.padrao.rota


@dataclass(frozen=True, slots=True)
class Match:
    """Resultado de um match: a entrada e os params crus extraídos."""

    entrada: ResponderEntry
    params: dict[str, str]


class ResponderRegistry:
    """Guarda padrões e encontra o responder de um `custom_id`."""

    __slots__ = ("_entradas",)

    def __init__(self) -> None:
        #: Sempre ordenada — reconstruída a cada `register` (0013). O
        #: custo é tempo de import, acontece uma vez, e não há risco
        #: de "registrei e o router não viu".
        self._entradas: tuple[ResponderEntry, ...] = ()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(
        self,
        rota: str,
        handler: Callable[..., Any],
        *,
        types: Iterable[ResponderType],
        cache: str = "any",
        parse: Callable[..., Any] | None = None,
        middleware: Iterable[Callable[..., Any]] = (),
    ) -> ResponderEntry:
        """Registra e devolve a entrada. Conflito é erro aqui, não no clique."""
        entrada = ResponderEntry(
            padrao=Padrao(rota),
            handler=handler,
            types=frozenset(types),
            cache=cache,
            parse=parse,
            middleware=tuple(middleware),
            module=getattr(handler, "__module__", "") or "<desconhecido>",
        )
        if not entrada.types:
            raise ResponderDefinitionError(
                f"responder {rota!r} sem types — sem filtro de tipo ele casa "
                f"qualquer interação, inclusive as que não existem ainda"
            )

        self._confere_conflitos(entrada)
        #: Ordenada por `Padrao.__lt__` — o mais específico casa
        #: primeiro, e o `match` só percorre na ordem.
        self._entradas = tuple(sorted((*self._entradas, entrada), key=lambda e: e.padrao))
        _log.debug("responder registrado: %s (%s)", rota, sorted(t.value for t in entrada.types))
        return entrada

    def _confere_conflitos(self, novo: ResponderEntry) -> None:
        """Mesmo id possível + tipos sobrepostos = os dois brigando."""
        for existente in self._entradas:
            if not (existente.types & novo.types):
                continue  # tipos disjuntos: dois lugares diferentes da UI
            if not conflitam(existente.padrao, novo.padrao):
                continue  # nunca casam o mesmo id: rotas distintas
            raise ResponderDefinitionError(
                f"responder {novo.rota!r} conflita com {existente.rota!r} "
                f"(types {sorted(t.value for t in novo.types)}) já registrado em "
                f"{existente.module} — os dois casam o mesmo custom_id e o clique "
                f"atenderia a quem chegasse por último. Rotas com mesmo peso "
                f"precisam de um literal que as separe."
            )

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------

    def match(self, custom_id: str, tipo: ResponderType | None = None) -> Match | None:
        """O responder mais específico que casa este id.

        `tipo=None` ignora o filtro — é o caminho do teste unitário.
        No dispatch real, o tipo sempre vem, e quem o passa é quem sabe
        qual interação chegou.
        """
        for entrada in self._entradas:
            if tipo is not None and tipo not in entrada.types:
                continue
            params = entrada.padrao.casa(custom_id)
            if params is not None:
                return Match(entrada=entrada, params=params)
        return None

    def entries(self) -> tuple[ResponderEntry, ...]:
        """Todas as entradas, na ordem de prioridade."""
        return self._entradas

    def por_tipo(self, tipo: ResponderType) -> tuple[ResponderEntry, ...]:
        return tuple(e for e in self._entradas if tipo in e.types)

    def __len__(self) -> int:
        return len(self._entradas)

    def __iter__(self) -> Iterator[ResponderEntry]:
        return iter(self._entradas)

    def limpa(self) -> None:
        """Zera — existe para o teste unitário, não para produção.

        Registry global compartilhado entre testes é contaminação de
        estado que aparece como falha num outro teste qualquer (K12).
        """
        self._entradas = ()
