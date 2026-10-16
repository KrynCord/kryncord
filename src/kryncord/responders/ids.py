"""A sintaxe de rota do `custom_id` — parse e construção no mesmo lugar.

É o que o K11 pediu: um arquivo define o formato. Parser aqui e
construtor noutro lugar é como os dois divergem — o router aceitando
uma sintaxe que o `build_custom_id` não produz, ou o contrário.

A sintaxe:

    /manage/user/:user_id/:action     literal, `:param`, `:param`
    /page/?:number                    `?:param` — opcional
    /giveaway/**                      wildcard no fim, casa 0 ou mais
    /giveaway/**:args                 wildcard nomeado, casa 1 ou mais

O `custom_id` é **dado, não autorização**. Quem constrói é a gente, mas
quem dispara é quem clica — e o id é forjável. Parâmetro extraído é
alvo, nunca permissão.
"""

from __future__ import annotations

from dataclasses import dataclass
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

#: Peso de cada segmento na prioridade do roteador (0013). Literal pesa
#: mais porque restringe mais; wildcard pesa zero porque casa tudo.
_PESOS = {LITERAL: 3, PARAM: 2, OPCIONAL: 1, WILDCARD: 0}


@dataclass(frozen=True, slots=True)
class Segmento:
    """Um pedaço da rota, já classificado.

    `nome` é o texto do literal, ou o nome do parâmetro. Wildcard sem
    nome guarda o resto em ``params["_"]``; nomeado, no próprio nome.
    """

    tipo: str
    nome: str

    @property
    def peso(self) -> int:
        return _PESOS[self.tipo]

    @property
    def e_param(self) -> bool:
        return self.tipo in (PARAM, OPCIONAL)

    def __str__(self) -> str:
        if self.tipo == LITERAL:
            return self.nome
        if self.tipo == PARAM:
            return f":{self.nome}"
        if self.tipo == OPCIONAL:
            return f"?:{self.nome}"
        return f"**:{self.nome}" if self.nome else "**"


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

        if seg.e_param or seg.tipo == WILDCARD:
            if seg.nome and seg.nome in nomes:
                raise ResponderDefinitionError(
                    f"rota {original!r} declara {seg.nome!r} duas vezes — params de nomes "
                    f"iguais não têm como ser distinguidos na injeção"
                )
            if seg.nome:
                nomes.add(seg.nome)

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

    `**` só no fim e `?:`/`:` só no começo são regras da 0013: `:` no
    meio de valor não é sintaxe, é dado — `2024-01-01T10:00` casa com
    `:date` porque a comparação é segmento inteiro.
    """
    if parte.startswith("**"):
        if not ultimo:
            raise ResponderDefinitionError(
                f"rota {rota!r} tem ** no meio ({parte!r}) — wildcard só no fim"
            )
        if parte == "**":
            return Segmento(WILDCARD, "")
        if parte.startswith("**:"):
            nome = parte[3:]
            _valida_nome(nome, rota=rota)
            return Segmento(WILDCARD, nome)
        raise ResponderDefinitionError(
            f"segmento {parte!r} inválido na rota {rota!r} — ** ou **:nome"
        )

    if parte.startswith("?:"):
        nome = parte[2:]
        _valida_nome(nome, rota=rota)
        return Segmento(OPCIONAL, nome)
    if parte.startswith(":"):
        nome = parte[1:]
        _valida_nome(nome, rota=rota)
        return Segmento(PARAM, nome)

    return Segmento(LITERAL, parte)


def _valida_nome(nome: str, *, rota: str) -> None:
    """Nome de param precisa ser identificador Python.

    Não é preciosismo: o nome vira argumento nomeado do handler
    (`fn(ctx, user_id=...)`), e um nome que não é identificador não tem
    como ser injetado. Descobrir isso na importação é a única chance.
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

        build_custom_id("/manage/user/:user_id/:action", user_id=123, action="ban")
        # "/manage/user/123/ban"

        build_custom_id("/manage/user/:user_id/:action", user_id=123)
        # ValueError: parâmetro ausente: action

    Três validações que o Discord não faria por nós:

    - **parâmetro ausente** — o Discord aceitaria um custom_id com o
      literal vazio colado, e o clique casaria com nada;
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
        if seg.tipo == LITERAL:
            partes.append(seg.nome)
            continue
        if seg.nome not in params:
            if seg.tipo == OPCIONAL:
                continue
            raise ValueError(
                f"parâmetro ausente: {seg.nome} — a rota {rota!r} exige, e custom_id "
                f"montado sem ele nunca casaria de volta"
            )
        #: Opcional ausente/None é escolha **desta** chamada — marcar como
        #: usado impede que o detector de "fora da rota" acuse um param
        #: que a rota conhece e a chamada decidiu omitir.
        usados.add(seg.nome)
        valor = params[seg.nome]
        if valor is None:
            if seg.tipo == OPCIONAL:
                continue
            raise ValueError(
                f"parâmetro {seg.nome} é None — obrigatório não aceita None; "
                f"use opcional (?:) na rota se ele pode faltar"
            )
        partes.append(_valor(seg.nome, valor))

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


def _valor(nome: str, valor: Any) -> str:
    """String do valor, recusando `/` — quebraria a segmentação."""
    texto = str(valor)
    if "/" in texto:
        raise ValueError(
            f"valor de {nome!r} contém '/' ({texto!r}) — vira segmento a mais e a "
            f"rota nunca mais casa. Timestamps ISO com ':' passam; '/' não."
        )
    return texto
