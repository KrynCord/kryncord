"""Padrão compilado — um `Padrao` casa um `custom_id` ou devolve `None`.

O match é por segmento, com **backtracking**. É obrigatório, não
elegante: `/a/{?x}/b` casa o id `/a/b` só se o `{?x}` aceitar casar zero
segmentos e deixar `b` para o literal. Sem voltar atrás, a resposta
seria "não casa" — e a rota mais natural deixaria de funcionar.

O casar-um-segmento é o `Segmento.casa` (`0031`): literal compara
igualdade, `{param}`/`{?param}`/segmento misto casam pelo regex do
segmento. Params embutidos (`produto:{id}:comprar`) não mudam nada
aqui — um segmento é um segmento, com o regex que seja.

A recursão é segura no tamanho real: rota tem no máximo
``MAX_CUSTOM_ID / 2`` segmentos, e cada nível consome um segmento do
padrão. Não há explosão exponencial porque opcional tenta "casar um"
antes de "casar zero", e um deles sempre falha rápido.
"""

from __future__ import annotations

from typing import Any

from kryncord.responders.ids import (
    OPCIONAL,
    WILDCARD,
    Segmento,
    parse_rota,
)


class Padrao:
    """Rota compilada, pronta para casar.

    Não é dataclass de propósito: guarda o resultado de `parse_rota`,
    e congelar uma cópia dos segmentos aqui seria pagar slots por nada
    — os segmentos já são imutáveis, e o padrão é dono só da referência.
    """

    __slots__ = ("_rota", "_segmentos")

    def __init__(self, rota: str) -> None:
        self._rota = rota
        self._segmentos = parse_rota(rota)

    @property
    def rota(self) -> str:
        return self._rota

    @property
    def segmentos(self) -> tuple[Segmento, ...]:
        return self._segmentos

    @property
    def pesos(self) -> tuple[int, ...]:
        """Pesos por segmento — a chave de ordenação inteira da 0013."""
        return tuple(s.peso for s in self._segmentos)

    @property
    def nomes(self) -> tuple[str, ...]:
        """Nomes de parâmetro que este padrão extrai."""
        return tuple(nome for s in self._segmentos for nome in s.nomes)

    def casa(self, custom_id: str) -> dict[str, str] | None:
        """Params crus se casa; `None` se não.

        Os valores são **string crua** — conversão por anotação é
        depois, no dispatcher, com o contexto à mão (0014). Aqui é só
        "este id tem a forma desta rota?".
        """
        partes = _partes(custom_id)
        if partes is None:
            return None
        achado = _casa(self._segmentos, partes, 0, 0, {})
        return dict(achado) if achado is not None else None

    def __str__(self) -> str:
        return self._rota

    def __repr__(self) -> str:
        return f"Padrao({self._rota!r})"

    def __lt__(self, other: Padrao) -> bool:
        """Mais específico é **menor** — ordena ascendente e o melhor casa primeiro.

        Peso por peso da esquerda para a direita (0013); quando um peso
        é prefixo do outro, o curto vence: ele termina sem wildcard, e
        o longo só empataria o peso com `**`/`{?x}` — exatamente os que
        casam "qualquer coisa".
        """
        for wx, wy in zip(self.pesos, other.pesos, strict=False):
            if wx != wy:
                return wy < wx
        return len(self.pesos) < len(other.pesos)


def _partes(custom_id: str) -> list[str] | None:
    """Segmentos do id, normalizados como rota. `None` se vazio.

    A mesma normalização do `parse_rota` — sem barra inicial, prependa.
    O id que a gente constrói sempre vem com barra; o que vem do
    Discord pode não vir, e recusar seria recusar botão legítimo.
    """
    if not isinstance(custom_id, str) or not custom_id.strip():
        return None
    texto = custom_id if custom_id.startswith("/") else "/" + custom_id
    while len(texto) > 1 and texto.endswith("/"):
        texto = texto[:-1]
    partes = texto.split("/")[1:]
    return partes or None


def _casa(
    segmentos: tuple[Segmento, ...],
    partes: list[str],
    i: int,
    j: int,
    params: dict[str, str],
) -> dict[str, str] | None:
    """Casa segmentos[i:] contra partes[j:], acumulando params.

    - `literal` exige igualdade exata — `custom_id` é gerido por nós,
      não digitado por humano, e case-folding seria trabalho sem
      cliente (0013);
    - `{param}`/segmento misto consomem exatamente um, com os params
      que o `Segmento.casa` extrair;
    - `{?param}` tenta consumir um, e volta para zero se o resto não
      fecha — o backtracking que faz `/a/{?x}/b` casar `/a/b`;
    - `**` consome todo o resto. Sem nome aceita zero (`params["_"]`
      é `""`); nomeado exige pelo menos um (0013).
    """
    if i == len(segmentos):
        return params if j == len(partes) else None

    seg = segmentos[i]

    if seg.tipo == WILDCARD:
        resto = partes[j:]
        if seg.nome and not resto:
            return None
        params[seg.nome or "_"] = "/".join(resto)
        return params

    if j < len(partes):
        achado = seg.casa(partes[j])
        if achado is not None:
            com_um = _casa(segmentos, partes, i + 1, j + 1, {**params, **achado})
            if com_um is not None:
                return com_um

    if seg.tipo == OPCIONAL:
        # Casou zero: o param fica **ausente**, não vazio. Ausente é o
        # que a anotação `T | None` espera; vazio seria `""`, que é um
        # valor — e converter `""` para int daria erro num param que
        # nem foi enviado.
        return _casa(segmentos, partes, i + 1, j, params)

    return None


def conflitam(a: Padrao, b: Padrao) -> bool:
    """Se dois padrões podem casar o **mesmo** id.

    Regra da 0013: mesmo peso **e** nenhum segmento onde os dois têm
    literais diferentes. `/a/{x}` e `/{y}/b` têm pesos diferentes e
    casam `/a/b` — não conflitam, a ordenação resolve. `/a/{x}` e
    `/{y}` têm o mesmo peso e casam `/a` — conflito. `/a/{x}` e `/b/{y}`
    têm o mesmo peso e nunca casam o mesmo id — não é conflito, são
    duas rotas.

    Segmento misto entra pela mesma porta: `produto:{id}:comprar` e
    `produto:comprar` têm pesos diferentes (misto conta como param);
    dois mistos de mesmo peso com os literais iguais casam o mesmo id e
    conflitam; com literais diferentes, não.

    Chamado no registro, na importação — o único momento em que dá
    para citar os dois módulos e o usuário ainda está olhando.
    """
    if a.pesos != b.pesos:
        return False
    for sa, sb in zip(a.segmentos, b.segmentos, strict=False):
        if sa.literais and sb.literais and sa.literais != sb.literais:
            return False
    return True


def ordena(padroes: Any) -> list[Padrao]:
    """Ordena por especificidade, mais específico primeiro.

    A comparação é o `__lt__` do `Padrao`: peso por peso da esquerda
    para a direita, curto vencendo no empate por prefixo (0013).
    """
    return sorted(padroes)
