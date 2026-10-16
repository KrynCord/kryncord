"""Autocomplete — contexto, normalização e despacho (`0021`).

O fio: a ordem de resolução **termina em resposta vazia** — o
fallback legítimo. Exceção aqui fecharia a janela de sugestão com
erro, que é o pior resultado para uma sugestão.
"""

from __future__ import annotations

import pytest

from kryncord.commands.autocomplete import (
    MAX_ESCOLHAS,
    AutocompleteContext,
    dispatch_autocomplete,
    foco_de,
    normalize_choices,
)
from kryncord.commands.definition import CommandDefinition
from kryncord.commands.instance import CommandInstance
from kryncord.errors import InteractionStateError
from kryncord.models.interaction import Interaction


class ApiFalsa:
    def __init__(self) -> None:
        self.respostas: list = []

    async def autocomplete(self, interaction, choices):
        self.respostas.append(choices)


def _payload_autocomplete(focado: str = "termo", valor: str = "dig") -> dict:
    return {
        "id": "1",
        "application_id": "1",
        "type": 4,
        "token": "t",
        "data": {
            "id": "9",
            "name": "buscar",
            "type": 1,
            "options": [
                {"name": "termo", "type": 3, "value": valor, "focused": True},
                {"name": "outro", "type": 3, "value": "x"},
            ],
        },
    }


class TestFocoDe:
    def test_extrai_nome_e_valor(self) -> None:
        interacao = Interaction.from_payload(_payload_autocomplete())

        assert foco_de(interacao) == ("termo", "dig")

    def test_sem_foco_e_none(self) -> None:
        bruto = _payload_autocomplete()
        bruto["data"]["options"][0]["focused"] = False
        interacao = Interaction.from_payload(bruto)

        assert foco_de(interacao) is None

    def test_tipo_errado_e_none(self) -> None:
        interacao = Interaction(id=1, application_id=1, type=2, token="t")

        assert foco_de(interacao) is None


class TestNormalizeChoices:
    def test_tuplas_nome_valor(self) -> None:
        assert normalize_choices([("Ana", 1), ("Bia", 2)]) == [
            {"name": "Ana", "value": 1},
            {"name": "Bia", "value": 2},
        ]

    def test_dicts(self) -> None:
        assert normalize_choices([{"name": "Ana", "value": 1}]) == [{"name": "Ana", "value": 1}]

    def test_choice_do_kryncord(self) -> None:
        from kryncord.commands.option import choice

        assert normalize_choices([choice("Ana", 1)]) == [{"name": "Ana", "value": 1}]

    def test_none_e_lista_vazia(self) -> None:
        assert normalize_choices(None) == []

    def test_item_invalido_e_ignorado(self) -> None:
        assert normalize_choices([("Ana", 1), 42]) == [{"name": "Ana", "value": 1}]

    def test_corta_em_25(self) -> None:
        saida = normalize_choices([(f"n{i}", i) for i in range(40)])

        assert len(saida) == MAX_ESCOLHAS
        assert saida[0] == {"name": "n0", "value": 0}

    def test_nome_cortado_em_100(self) -> None:
        saida = normalize_choices([("a" * 150, 1)])

        assert len(saida[0]["name"]) == 100


class TestAutocompleteContext:
    def test_focused_e_o_nome_focused_value_o_digitado(self) -> None:
        """ "`focused` é o nome da opção; `focused_value`, o que foi
        digitado — o contrato da `0021`, que corrigiu a ideia 06."""
        ctx = AutocompleteContext(focused="termo", focused_value="dig")

        assert ctx.focused == "termo"
        assert ctx.focused_value == "dig"

    async def test_respond_normaliza_e_marca(self) -> None:
        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())
        ctx = AutocompleteContext(focused="t", focused_value="v", interaction=interacao, api=api)

        await ctx.respond([("Ana", 1)])

        assert api.respostas == [[{"name": "Ana", "value": 1}]]
        assert ctx.is_responded() is True

    async def test_respond_duas_vezes_e_erro(self) -> None:
        """A interação aceita uma sugestão só — a segunda viraria 400
        genérico do Discord, sem dizer qual chamada saiu de ordem."""
        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())
        ctx = AutocompleteContext(focused="t", interaction=interacao, api=api)

        await ctx.respond([])
        with pytest.raises(InteractionStateError, match="uma sugestão só"):
            await ctx.respond([])

    async def test_sem_api_e_erro_claro(self) -> None:
        ctx = AutocompleteContext(focused="t")

        with pytest.raises(RuntimeError, match="api"):
            await ctx.respond([])

    async def test_sem_reply_no_contexto(self) -> None:
        """0012: autocomplete **só** responde com escolhas — o ajuste
        que o juiz pediu. `reply` não pode nem existir aqui."""
        assert not hasattr(AutocompleteContext, "reply")


class TestDispatchAutocomplete:
    def _instancia(self) -> CommandInstance:
        return CommandInstance(
            CommandDefinition(name="buscar", description="busca"), lambda ctx: None
        )

    async def test_handler_da_opcao_atende(self) -> None:
        instance = self._instancia()
        recebido: dict = {}

        @instance.autocomplete("termo")
        async def sugere(ctx):
            recebido["focused"] = ctx.focused
            recebido["valor"] = ctx.focused_value
            return [("Ana", 1)]

        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())

        ok = await dispatch_autocomplete(interacao, api, instance)

        assert ok is True
        assert recebido == {"focused": "termo", "valor": "dig"}
        assert api.respostas == [[{"name": "Ana", "value": 1}]]

    async def test_handler_generico_cobre_qualquer_opcao(self) -> None:
        instance = self._instancia()

        @instance.autocomplete()
        async def generico(ctx):
            return [("x", 1)]

        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())

        ok = await dispatch_autocomplete(interacao, api, instance)

        assert ok is True
        assert api.respostas == [[{"name": "x", "value": 1}]]

    async def test_sem_handler_responde_vazio(self) -> None:
        """O fallback da ordem de resolução: lista vazia é legal, e o
        Discord mostra "nenhum resultado" sem reclamar."""
        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())

        ok = await dispatch_autocomplete(interacao, api, self._instancia())

        assert ok is False
        assert api.respostas == [[]]

    async def test_handler_sem_responder_e_respondido_pelo_dispatch(self) -> None:
        """Handler que só calcula e esquece do `respond` não deixa a
        janela pendurada — o dispatch responde o que calculou."""
        instance = self._instancia()

        @instance.autocomplete("termo")
        async def calcula(ctx):
            return [("Ana", 1)]

        api = ApiFalsa()
        interacao = Interaction.from_payload(_payload_autocomplete())

        await dispatch_autocomplete(interacao, api, instance)

        assert api.respostas == [[{"name": "Ana", "value": 1}]]
