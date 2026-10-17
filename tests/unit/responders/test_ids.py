"""`ids.py` — a sintaxe de rota: parse e construção (0013, K11).

O fio dos testes: **o que se valida na importação não quebra no
clique**. Rota inválida, parâmetro ausente, valor com `/` — tudo isso
tem que sair antes de existir botão publicado.
"""

from __future__ import annotations

import pytest

from kryncord.errors import ResponderDefinitionError
from kryncord.responders.ids import (
    LITERAL,
    OPCIONAL,
    PARAM,
    WILDCARD,
    build_custom_id,
    parse_rota,
)


class TestParseRota:
    def test_rota_literal(self) -> None:
        segmentos = parse_rota("/system/confirm")

        assert [s.tipo for s in segmentos] == [LITERAL, LITERAL]
        assert [s.nome for s in segmentos] == ["system", "confirm"]

    def test_param_e_opcional(self) -> None:
        segmentos = parse_rota("/page/{?number}")

        assert segmentos[0].tipo == LITERAL
        assert segmentos[1].tipo == OPCIONAL
        assert segmentos[1].nome == "number"
        assert segmentos[1].e_param

    def test_params_multiplos(self) -> None:
        segmentos = parse_rota("/manage/user/{user_id}/{action}")

        assert [s.tipo for s in segmentos] == [LITERAL, LITERAL, PARAM, PARAM]
        assert [s.nome for s in segmentos] == ["manage", "user", "user_id", "action"]

    def test_wildcard_no_fim(self) -> None:
        segmentos = parse_rota("/giveaway/**")

        assert segmentos[-1].tipo == WILDCARD
        assert segmentos[-1].nome == ""

    def test_wildcard_nomeado(self) -> None:
        segmentos = parse_rota("/giveaway/**{args}")

        assert segmentos[-1].tipo == WILDCARD
        assert segmentos[-1].nome == "args"

    def test_sem_barra_inicial_normaliza(self) -> None:
        """A ideia 08 §7 pediu normalização com aviso, não recusa."""
        assert parse_rota("system/confirm") == parse_rota("/system/confirm")

    def test_trailing_slash_e_a_mesma_rota(self) -> None:
        assert parse_rota("/system/confirm/") == parse_rota("/system/confirm")

    # ------------------------------------------------------------------
    # Erros — todos na importação
    # ------------------------------------------------------------------

    def test_segmento_vazio_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match="segmento vazio"):
            parse_rota("/a//b")

    def test_rota_vazia_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match="rota vazia"):
            parse_rota("")

    def test_wildcard_no_meio_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match=r"\*\* no meio"):
            parse_rota("/a/**/b")

    def test_wildcard_malformado_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match="inválido"):
            parse_rota("/a/**x")

    def test_param_sem_nome_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match="identificador"):
            parse_rota("/a/{}")

    def test_param_nome_invalido_e_erro(self) -> None:
        """O nome vira argumento nomeado do handler — precisa ser
        identificador, ou a injeção não tem como acontecer."""
        with pytest.raises(ResponderDefinitionError, match="identificador"):
            parse_rota("/a/{nome-com-traco}")

    def test_param_duplicado_e_erro(self) -> None:
        with pytest.raises(ResponderDefinitionError, match="duas vezes"):
            parse_rota("/a/{x}/{x}")


class TestPesos:
    """A tabela de pesos da 0013 — literal 3, `{p}` 2, `{?p}` 1, `**` 0."""

    def test_pesos_na_ordem_da_decisao(self) -> None:
        assert parse_rota("/a/{b}")[0].peso == 3
        assert parse_rota("/a/{b}")[1].peso == 2
        assert parse_rota("/a/{?b}")[1].peso == 1
        assert parse_rota("/a/**")[1].peso == 0


class TestBuildCustomId:
    def test_monta_na_ordem_da_rota(self) -> None:
        assert build_custom_id("/manage/user/{user_id}/{action}", user_id=123, action="ban") == (
            "/manage/user/123/ban"
        )

    def test_param_ausente_e_erro_com_nome(self) -> None:
        """Sem o nome na mensagem, o usuário caça qual dos cinco faltou."""
        with pytest.raises(ValueError, match="parâmetro ausente: action"):
            build_custom_id("/manage/user/{user_id}/{action}", user_id=123)

    def test_opcional_ausente_omite_o_segmento(self) -> None:
        assert build_custom_id("/page/{?number}") == "/page"
        assert build_custom_id("/page/{?number}", number=2) == "/page/2"

    def test_opcional_none_omite(self) -> None:
        assert build_custom_id("/page/{?number}", number=None) == "/page"

    def test_obrigatorio_none_e_erro(self) -> None:
        with pytest.raises(ValueError, match="parâmetro ausente: x"):
            build_custom_id("/a/{x}", x=None)

    def test_valor_com_barra_e_erro(self) -> None:
        """`/` criaria segmento a mais — a rota nunca mais casaria."""
        with pytest.raises(ValueError, match="contém '/'"):
            build_custom_id("/a/{x}", x="1/2")

    def test_param_fora_da_rota_e_erro(self) -> None:
        """Parâmetro que a rota não declara é nome digitado errado."""
        with pytest.raises(ValueError, match="fora da rota"):
            build_custom_id("/a/{user_id}", user_id=1, usr_id=2)

    def test_wildcard_e_erro(self) -> None:
        with pytest.raises(ValueError, match="wildcard é para casar"):
            build_custom_id("/a/**")

    def test_limite_de_100_caracteres(self) -> None:
        """O limite é do Discord — descobrir na criação do componente,
        não na hora do clique."""
        with pytest.raises(ValueError, match="limite"):
            build_custom_id("/" + "a" * 101)

    def test_valor_datetime_iso_passa(self) -> None:
        """ISO tem `:`, não `/` — a 0013 garante que é dado, não sintaxe."""
        custom_id = build_custom_id("/remember/{date}", date="2024-01-01T10:00:00")
        assert custom_id == "/remember/2024-01-01T10:00:00"
