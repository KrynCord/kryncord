"""A sintaxe de rota do `custom_id` — parse e construção no mesmo lugar.

É o que o K11 pediu: um arquivo define o formato. Parser aqui e
construtor noutro lugar é como os dois divergem — o router aceitando
uma sintaxe que o `build_custom_id` não produz, ou o contrário.

A sintaxe (`0031`):

    /manage/user/{user_id}/{action}   literal, param, param
    /page/{?number}                   `{?param}` — opcional
    /giveaway/**                      wildcard no fim, casa 0 ou mais
    /giveaway/**{args}                wildcard nomeado, casa 1 ou mais
    /produto:{product_id}:comprar     param embutido no segmento

Params embutidos são a diferença para a sintaxe antiga (`:param` só no
começo do segmento, `2024-01-01T10:00` era literal): `{product_id}` no
meio de um segmento casa contra o texto do segmento inteiro, e o valor
capturado não pode conter `/` — que é o separador de segmento. Chaves
não casam nada: `:param` e `?:param` não existem mais, e a rota que
ainda os usa recebe erro citando a troca, na importação.

O `custom_id` é **dado, não autorização**. Quem constrói é a gente, mas
quem dispara é quem clica — e o id é forjável. Parâmetro extraído é
alvo, nunca permissão.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kryncord.errors import ResponderDefinitionError
from kryncord.logging import get_logger

_log = get_logger(__name__)

#: O limite do Discord. Passou, o componente é recusado na criação —
#: descobrir no clique seria descobrir depois de publicar.
MAX_CUSTOM_ID = 100

LITERAL = "literal"
PARAM = "param"
OPCIONAL = "opcional"
WILDCARD = "wildcard"
MISTO = "misto"

#: Peso de cada segmento na prioridade do roteador (0013). Literal pesa
#: mais porque restringe mais; wildcard pesa zero porque casa tudo.
#: Misto pesa como param: `produto:{id}` restringe menos que o literal
#: `produto:comprar`, que pode virar amanhã — e pesos iguais aos de
#: literal fariam a ordenação tratar os dois como empate.
_PESOS = {LITERAL: 3, PARAM: 2, OPCIONAL: 1, WILDCARD: 0, MISTO: 2}

#: O que o param captura: qualquer coisa sem `/`. Não-ganancioso para o
#: literal seguinte decidir onde o valor termina — em
#: `produto:{id}:comprar`, o id de `produto:12:34:comprar` é `12:34`.
_PARAM_RX = "(?P<{nome}>[^/]+?)"


@dataclass(frozen=True, slots=True)
class Segmento:
    """Um pedaço da rota, já classificado.

    `nome` é o texto do literal, o nome do parâmetro, ou o segmento
    bruto no caso misto. `pecas` só existe no misto: a sequência de
    (tipo, texto) que o segmento é. `rx` é o regex compilado na hora do
    parse — derivado, então fora de `eq`/`repr`.
    """

    tipo: str
    nome: str
    pecas: tuple[tuple[str, str], ...] = ()
    rx: str = field(default="", compare=False, repr=False)

    @property
    def peso(self) -> int:
        return _PESOS[self.tipo]

    @property
    def e_param(self) -> bool:
        return self.tipo in (PARAM, OPCIONAL)

    @property
    def nomes(self) -> tuple[str, ...]:
        """Nomes de parâmetro que este segmento extrai."""
        if self.tipo == PARAM or self.tipo == OPCIONAL:
            return (self.nome,)
        if self.tipo == WILDCARD:
            return (self.nome,) if self.nome else ()
        if self.tipo == MISTO:
            return tuple(v for t, v in self.pecas if t != LITERAL)
        return ()

    @property
    def opcionais(self) -> tuple[str, ...]:
        """Desses nomes, os que podem faltar."""
        if self.tipo == OPCIONAL:
            return (self.nome,)
        if self.tipo == MISTO:
            return tuple(v for t, v in self.pecas if t == OPCIONAL)
        return ()

    @property
    def literais(self) -> tuple[str, ...]:
        """Textos fixos do segmento — o que separa duas rotas de mesmo peso.

        Vazio nos segmentos que não têm literal nenhum. É o que o
        `conflitam` compara para dizer "estes dois nunca casam o mesmo
        id, são rotas diferentes".
        """
        if self.tipo == LITERAL:
            return (self.nome,)
        if self.tipo == MISTO:
            return tuple(v for t, v in self.pecas if t == LITERAL)
        return ()

    def casa(self, parte: str) -> dict[str, str] | None:
        """Params que este segmento extrai de `parte`, ou `None`.

        Literal compara igualdade exata — `custom_id` é gerado por nós,
        não digitado por humano, e case-folding seria trabalho sem
        cliente (0013). Os demais casam pelo `rx`; grupos que não
        participaram (opção ausente) ficam **fora** do dict — ausente é
        o que a anotação `T | None` espera, `None` capturado seria.
        """
        if self.tipo == LITERAL:
            return {} if parte == self.nome else None
        achado = re.fullmatch(self.rx, parte)
        if achado is None:
            return None
        return {k: v for k, v in achado.groupdict().items() if v is not None}

    def preenche(self, params: Mapping[str, Any]) -> str | None:
        """O segmento concreto com estes params. `None` = omitir.

        Omitir existe porque `{?x}` ausente não vira segmento vazio —
        `/a/{?x}` com `x` faltando é `/a`, não `/a/`.
        """
        if self.tipo == LITERAL:
            return self.nome
        if self.tipo == PARAM:
            return _obrigatorio(self.nome, params)
        if self.tipo == OPCIONAL:
            return _opcional(self.nome, params)
        if self.tipo == MISTO:
            saida: list[str] = []
            for ptipo, pvalor in self.pecas:
                if ptipo == LITERAL:
                    saida.append(pvalor)
                elif ptipo == PARAM:
                    saida.append(_obrigatorio(pvalor, params))
                else:
                    texto = _opcional(pvalor, params)
                    if texto is not None:
                        saida.append(texto)
            return "".join(saida)
        raise ValueError(  # pragma: no cover - WILDCARD barrado no build
            "wildcard não se preenche — é para casar, não para construir"
        )

    def __str__(self) -> str:
        if self.tipo == LITERAL:
            return self.nome
        if self.tipo == PARAM:
            return f"{{{self.nome}}}"
        if self.tipo == OPCIONAL:
            return f"{{?{self.nome}}}"
        if self.tipo == MISTO:
            return "".join(
                texto
                if ptipo == LITERAL
                else (f"{{{texto}}}" if ptipo == PARAM else f"{{?{texto}}}")
                for ptipo, texto in self.pecas
            )
        return f"**{{{self.nome}}}" if self.nome else "**"


def parse_rota(rota: str) -> tuple[Segmento, ...]:
    """Decompõe e valida. `ResponderDefinitionError` em tudo que não casa.

    Toda a validação acontece **aqui**, na importação — nunca no clique.
    Rota errada descoberta no clique é descoberta depois de publicar o
    botão, quando o usuário já vê um botão que não faz nada.
    """
    original = rota
    rota = _normaliza(rota)
    partes = rota.split("/")[1:]

    if not partes or any(not p for p in partes):
        raise ResponderDefinitionError(f"rota {original!r} tem segmento vazio — /a//b não é rota")

    segmentos: list[Segmento] = []
    nomes: set[str] = set()
    for i, parte in enumerate(partes):
        ultimo = i == len(partes) - 1
        seg = _segmento(parte, rota=original, ultimo=ultimo)

        for nome in seg.nomes:
            if nome in nomes:
                raise ResponderDefinitionError(
                    f"rota {original!r} declara {nome!r} duas vezes — params de nomes "
                    f"iguais não têm como ser distinguidos na injeção"
                )
            nomes.add(nome)

        segmentos.append(seg)

    return tuple(segmentos)


def _normaliza(rota: str) -> str:
    """`/foo/` == `/foo`; sem barra inicial, prependa e avisa.

    O aviso é debug, não erro: a ideia 08 §7 pediu normalização com
    aviso, e recusar seria quebrar o exemplo mais comum por um detalhe.
    """
    if not isinstance(rota, str) or not rota.strip():
        raise ResponderDefinitionError("rota vazia — custom_id precisa de pelo menos um segmento")
    if not rota.startswith("/"):
        _log.debug("rota %r sem '/' inicial — normalizada para '/%s'", rota, rota)
        rota = "/" + rota
    while len(rota) > 1 and rota.endswith("/"):
        rota = rota[:-1]
    return rota


def _segmento(parte: str, *, rota: str, ultimo: bool) -> Segmento:
    """Classifica um segmento, validando a sintaxe.

    `**` só no fim (0013). Params embutidos valem para qualquer outro
    segmento: `{a}` inteiro é param puro, `{a}` com texto em volta é
    misto, e `{?a}` embutido é opcional dentro do próprio segmento —
    `a{?b}c` casa com `ac` e com `abc`.
    """
    if parte.startswith("**"):
        return _wildcard(parte, rota=rota, ultimo=ultimo)

    _barras_sintaxe_antiga(parte, rota=rota)

    pecas = _pecas(parte, rota=rota)
    if not pecas:
        return Segmento(LITERAL, parte, rx=re.escape(parte))
    if len(pecas) == 1:
        ptipo, pvalor = pecas[0]
        return Segmento(ptipo, pvalor, rx=_PARAM_RX.format(nome=pvalor))

    if not any(t == LITERAL and v for t, v in pecas):
        raise ResponderDefinitionError(
            f"segmento {parte!r} da rota {rota!r} junta params sem literal entre eles — "
            f"{{a}}{{b}} não tem como separar os dois valores; ponha texto fixo no meio"
        )
    return Segmento(MISTO, parte, pecas=pecas, rx=_rx_de(pecas, rota=rota))


def _wildcard(parte: str, *, rota: str, ultimo: bool) -> Segmento:
    if not ultimo:
        raise ResponderDefinitionError(
            f"rota {rota!r} tem ** no meio ({parte!r}) — wildcard só no fim"
        )
    if parte == "**":
        return Segmento(WILDCARD, "")
    if parte.startswith("**{") and parte.endswith("}"):
        nome = parte[3:-1]
        _valida_nome(nome, rota=rota)
        return Segmento(WILDCARD, nome)
    if parte.startswith("**:"):
        raise ResponderDefinitionError(
            f"rota {rota!r}: `**:{parte[3:]}` é a sintaxe antiga — o nomeado "
            f"agora é `**{{{parte[3:]}}}`"
        )
    raise ResponderDefinitionError(
        f"segmento {parte!r} inválido na rota {rota!r} — wildcard é `**` ou `**{{nome}}`"
    )


def _barras_sintaxe_antiga(parte: str, *, rota: str) -> None:
    """`{param}` é a sintaxe; `:param`/`?:param` não existem mais (`0031`).

    Tratá-los como literal seria pior que recusar: a rota registraria,
    o handler nunca casaria, e o clique cairia no `on_not_found` sem
    dica nenhuma de que a rota está escrita com a gramática de 2025.
    """
    if parte.startswith("?:") and parte[2:].isidentifier():
        raise ResponderDefinitionError(
            f"rota {rota!r}: `{parte}` é a sintaxe antiga — o opcional agora é `{{?{parte[2:]}}}`"
        )
    if parte.startswith(":") and parte[1:].isidentifier():
        raise ResponderDefinitionError(
            f"rota {rota!r}: `{parte}` é a sintaxe antiga — o param agora é `{{{parte[1:]}}}`"
        )


def _pecas(parte: str, *, rota: str) -> tuple[tuple[str, str], ...]:
    """Decompõe um segmento em (literal|param|opcional, texto).

    Chave fechada sem aberta, chave aberta sem fechada e nome que não é
    identificador são todos erro aqui — na importação, apontando a
    chave errada.
    """
    pecas: list[tuple[str, str]] = []
    texto: list[str] = []
    i = 0
    while i < len(parte):
        char = parte[i]
        if char == "}":
            raise ResponderDefinitionError(
                f"segmento {parte!r} da rota {rota!r} tem '}}' sem '{{' — "
                f"params são {{nome}} e {{?nome}}"
            )
        if char != "{":
            texto.append(char)
            i += 1
            continue

        if texto:
            pecas.append((LITERAL, "".join(texto)))
            texto = []
        fim = parte.find("}", i)
        if fim == -1:
            raise ResponderDefinitionError(
                f"segmento {parte!r} da rota {rota!r} tem '{{' sem '}}' — "
                f"params são {{nome}} e {{?nome}}"
            )
        conteudo = parte[i + 1 : fim]
        if conteudo.startswith("?"):
            pecas.append((OPCIONAL, conteudo[1:]))
        else:
            pecas.append((PARAM, conteudo))
        _valida_nome(conteudo[1:] if conteudo.startswith("?") else conteudo, rota=rota)
        i = fim + 1

    if texto:
        pecas.append((LITERAL, "".join(texto)))
    return tuple(pecas)


def _rx_de(pecas: tuple[tuple[str, str], ...], *, rota: str) -> str:
    """O regex de um segmento misto.

    Opcional vira grupo aninhado (`a{?b}c` casa `ac` e `abc`) — aqui o
    opcional é dentro do segmento, e pular o segmento inteiro não é
    opção porque junto iria o literal que o precede e o que vem depois.
    """
    pedacos: list[str] = []
    for ptipo, pvalor in pecas:
        if ptipo == LITERAL:
            pedacos.append(re.escape(pvalor))
        elif ptipo == OPCIONAL:
            pedacos.append(f"(?:{_PARAM_RX.format(nome=pvalor)})?")
        else:
            pedacos.append(_PARAM_RX.format(nome=pvalor))
    return "".join(pedacos)


def _valida_nome(nome: str, *, rota: str) -> None:
    """Nome de param precisa ser identificador Python.

    Não é preciosismo: o nome vira argumento nomeado do handler
    (`fn(interaction, user_id=...)`), e um nome que não é identificador
    não tem como ser injetado. Descobrir isso na importação é a única
    chance.
    """
    if not nome.isidentifier():
        raise ResponderDefinitionError(
            f"nome de parâmetro {nome!r} na rota {rota!r} não é identificador — "
            f"ele vira argumento nomeado do handler, então precisa ser um nome Python válido"
        )


def build_custom_id(rota: str, /, **params: Any) -> str:
    """Monta o `custom_id` a partir da rota, validando antes de mandar.

    É o helper que torna o padrão seguro — sem ele, todo mundo monta
    string na mão e erra o nome do parâmetro em runtime.

        build_custom_id("/manage/user/{user_id}/{action}", user_id=123, action="ban")
        # "/manage/user/123/ban"

        build_custom_id("/produto:{product_id}:comprar", product_id=42)
        # "/produto:42:comprar"

        build_custom_id("/manage/user/{user_id}/{action}", user_id=123)
        # ValueError: parâmetro ausente: action

    Quatro validações que o Discord não faria por nós:

    - **parâmetro ausente** — o Discord aceitaria um custom_id com o
      literal vazio colado, e o clique casaria com nada;
    - **valor vazio** — mesmo efeito, pelo mesmo motivo;
    - **`/` no valor** — criaria segmento a mais e a rota não casaria
      mais, nunca;
    - **100 caracteres** — o limite dele, descoberto na criação do
      componente e não na hora do clique.

    `**` é erro aqui: wildcard é para **casar**, e montar id concreto
    com wildcard é não saber o que se está montando.
    """
    segmentos = parse_rota(rota)
    partes: list[str] = []
    usados: set[str] = set()

    for seg in segmentos:
        if seg.tipo == WILDCARD:
            raise ValueError(
                f"rota {rota!r} tem ** — wildcard é para casar, não para construir. "
                f"Monte o id concreto: os segmentos que o ** casaria têm que vir de você."
            )
        texto = seg.preenche(params)
        #: Marcado todo nome que a rota conhece e a chamada tocou — o
        #: opcional ausente é escolha **desta** chamada, e marcar
        #: impede o detector de "fora da rota" acusar um param que a
        #: rota declara e a chamada decidiu omitir.
        usados.update(seg.nomes)
        if texto is not None:
            partes.append(texto)

    nao_usados = set(params) - usados
    if nao_usados:
        raise ValueError(
            f"parâmetros fora da rota {rota!r}: {sorted(nao_usados)} — "
            f"parâmetro que a rota não declara é nome digitado errado"
        )

    custom_id = "/" + "/".join(partes)
    if len(custom_id) > MAX_CUSTOM_ID:
        raise ValueError(
            f"custom_id de {len(custom_id)} caracteres passa o limite de "
            f"{MAX_CUSTOM_ID} do Discord — a rota {rota!r} com esses valores "
            f"não cabe; encurte os nomes ou os valores"
        )
    return custom_id


def _obrigatorio(nome: str, params: Mapping[str, Any]) -> str:
    if nome not in params or params[nome] is None:
        raise ValueError(
            f"parâmetro ausente: {nome} — a rota exige, e custom_id "
            f"montado sem ele nunca casaria de volta"
        )
    return _valor(nome, params[nome], obrigatorio=True)


def _opcional(nome: str, params: Mapping[str, Any]) -> str | None:
    valor = params.get(nome)
    if valor is None or valor == "":
        return None
    return _valor(nome, valor, obrigatorio=False)


def _valor(nome: str, valor: Any, *, obrigatorio: bool) -> str:
    """String do valor, recusando `/` e vazio — os dois quebram o match.

    `/` vira segmento a mais; vazio deixa o segmento sem o que o param
    precisa capturar (`{x}` exige pelo menos um caractere). Timestamps
    ISO com ':' passam; os dois não.
    """
    texto = str(valor)
    if "/" in texto:
        raise ValueError(
            f"valor de {nome!r} contém '/' ({texto!r}) — vira segmento a mais e a "
            f"rota nunca mais casa. Timestamps ISO com ':' passam; '/' não."
        )
    if obrigatorio and not texto:
        raise ValueError(
            f"parâmetro {nome!r} é vazio — o param exige pelo menos um caractere, "
            f"e um segmento vazio nunca casaria de volta"
        )
    return texto
