"""Lê a resposta da API como modelo, e reclama quando não dá.

`Model.from_payload` devolve `None` quando falta o campo essencial — o
contrato de `models/`. Num payload de **Gateway** isso é correto:
entrega-se o dict cru e o handler decide.

Numa resposta **REST** o cálculo é outro. O chamador fez `await`,
esperou uma `Message`, e devolver `None` empurraria uma decisão que
ninguém escreveu para dentro do código dele — e esconderia que o
Discord devolveu algo que não era o que pedimos.

Então aqui falta de campo vira `HTTPError`: alto, cedo, e com a rota
na mensagem.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, Self, TypeVar

from kryncord.errors import HTTPError
from kryncord.http.response import Response


class FromPayload(Protocol):
    """O contrato que todo modelo de `models/` cumpre.

    Existe porque `type[T]` não sabe que `T` tem `from_payload` — o
    mypy vê a classe como opaca. O `Protocol` diz o que se espera, e o
    `TypeVar` ligado a ele devolve o modelo certo ao chamador sem `cast`.
    """

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Self | None: ...


T = TypeVar("T", bound=FromPayload)


def expect_model(model: type[T], response: Response, *, route: str) -> T:
    """Converte o corpo da resposta em modelo, ou levanta `HTTPError`.

    `model` é a classe com `from_payload` — `Message`, `Channel`,
    `User`, `Guild`. O `TypeVar` ligado a `FromPayload` faz o chamador
    receber o modelo certo, e não `Any`.
    """
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPError(
            f"{route} devolveu {response.status} sem corpo de objeto — "
            f"esperava JSON com campos, recebi {type(body).__name__}",
            status=response.status,
        )

    parsed: T | None = model.from_payload(body)
    if parsed is None:
        raise HTTPError(
            f"{route} devolveu {response.status} com um corpo que não forma "
            f"{model.__name__} — provavelmente sem o campo essencial. "
            f"Início do corpo: {response.text[:200]!r}",
            status=response.status,
        )
    return parsed


def expect_list(model: type[T], response: Response, *, route: str) -> list[T]:
    """Converte uma resposta de **lista** em modelos.

    A tolerância aqui é maior que a de `expect_model`, e é de propósito:
    `GET /channels/:id/messages` devolve 50 mensagens, e uma entrada
    ruim no meio não pode descartar as outras 49. `from_payload` já
    devolve `None` para o que não deu, e esses são pulados.

    Lista vazia é resposta legítima — canal sem mensagens existe, guild
    sem bans existe. Só corpo que não é lista é erro.
    """
    body = response.json()
    if not isinstance(body, list):
        raise HTTPError(
            f"{route} devolveu {response.status} sem lista — esperava um "
            f"array, recebi {type(body).__name__}",
            status=response.status,
        )

    models: list[T] = []
    for item in body:
        if not isinstance(item, Mapping):
            continue
        parsed = model.from_payload(item)
        if parsed is not None:
            models.append(parsed)
    return models
