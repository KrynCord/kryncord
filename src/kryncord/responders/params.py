"""`Params` — o que a rota extraiu, imutável e por atributo.

`params["user_id"]` e `params.user_id` são a mesma pergunta, e as duas
formas já estavam escritas nas ideias (08 §1 usa `[]`, o acesso por
atributo é o que o handler nomeado pede). Um contêiner só, imutável:

- imutável porque o valor veio do `custom_id` — "alterar" um param é
  mentir para si mesmo sobre o que o usuário clicou;
- `Mapping` porque `dict(params)` já tem que funcionar, e herdar de
  `dict` congelado de verdade não dá.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping


class Params(Mapping[str, str]):
    """Valores crus extraídos da rota, em ordem de leitura só."""

    __slots__ = ("_valores",)

    def __init__(self, valores: Mapping[str, str] | None = None) -> None:
        #: Cópia na construção — quem passou o dict continua dono do
        #: original, e mutar lá fora não muda o que já foi extraído.
        self._valores: dict[str, str] = dict(valores or {})

    def __getitem__(self, nome: str) -> str:
        try:
            return self._valores[nome]
        except KeyError:
            raise KeyError(
                f"param {nome!r} não está nesta rota; extraídos: {sorted(self._valores)}"
            ) from None

    def __contains__(self, nome: object) -> bool:
        return nome in self._valores

    def __iter__(self) -> Iterator[str]:
        return iter(self._valores)

    def __len__(self) -> int:
        return len(self._valores)

    def __getattr__(self, nome: str) -> str:
        """`params.user_id` — `AttributeError` para o que não existe.

        `AttributeError`, não `KeyError`: quem escreveu
        ``params.user_ld`` (typo) errou um **nome**, e o traceback deve
        apontar a linha como erro de atributo — igual a qualquer
        attribute access do Python.
        """
        try:
            return self._valores[nome]
        except KeyError:
            raise AttributeError(
                f"param {nome!r} não está nesta rota; extraídos: {sorted(self._valores)}"
            ) from None

    def __repr__(self) -> str:
        return f"Params({self._valores!r})"
