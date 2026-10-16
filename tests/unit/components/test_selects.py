"""Selects — limites e `SelectOption` — ideia 17 §3.

Cada limite da tabela vira um teste, e a normalização das três formas
de opção é o que faz o `options=[{"label": ...}]` das ideias funcionar
sem conversão à mão.
"""

from __future__ import annotations

import pytest

from kryncord.components import (
    ChannelSelectMenu,
    MentionableSelectMenu,
    RoleSelectMenu,
    SelectOption,
    StringSelectMenu,
    UserSelectMenu,
    create_channel_select,
    create_string_select,
)
from kryncord.enums import ChannelType
from kryncord.errors import ComponentError


class TestSelectOption:
    def test_classe_passa(self) -> None:
        opcao = SelectOption(label="Maçã", value="apple")

        assert opcao.to_dict() == {"label": "Maçã", "value": "apple"}

    def test_dict_normaliza(self) -> None:
        opcao = SelectOption.de({"label": "Maçã", "value": "apple", "emoji": "🍎"})

        assert opcao.emoji == "🍎"

    def test_tuple_posicional(self) -> None:
        opcao = SelectOption.de(("Melancia", "melon"))

        assert opcao.label == "Melancia"

    def test_dict_sem_label_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem label/value"):
            SelectOption.de({"value": "x"})

    def test_descricao_e_default_no_payload(self) -> None:
        payload = SelectOption("A", "a", description="d", default=True).to_dict()

        assert payload["description"] == "d"
        assert payload["default"] is True


class TestStringSelect:
    def test_options_dict_na_construcao(self) -> None:
        menu = StringSelectMenu(
            custom_id="/fruits",
            options=[{"label": "Maçã", "value": "apple"}, ("Melancia", "melon")],
        )

        assert tuple(menu.options) == (
            SelectOption("Maçã", "apple"),
            SelectOption("Melancia", "melon"),
        )

    def test_sem_options_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem options"):
            StringSelectMenu(custom_id="/fruits")

    def test_vinte_e_seis_options_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="máximo 25"):
            StringSelectMenu(custom_id="/x", options=[(f"o{i}", str(i)) for i in range(26)])

    def test_opcao_com_label_gigante(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            StringSelectMenu(custom_id="/x", options=[("a" * 101, "v")])

    def test_placeholder_acima_de_150(self) -> None:
        with pytest.raises(ComponentError, match="150"):
            StringSelectMenu(custom_id="/x", options=[("a", "b")], placeholder="p" * 151)

    def test_custom_id_acima_de_100(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            StringSelectMenu(custom_id="/x" + "y" * 100, options=[("a", "b")])

    def test_min_max_fora_da_faixa(self) -> None:
        opcoes = [("a", "b")]
        with pytest.raises(ComponentError, match="min_values"):
            StringSelectMenu(custom_id="/x", options=opcoes, min_values=-1)

        with pytest.raises(ComponentError, match="max_values"):
            StringSelectMenu(custom_id="/x", options=opcoes, max_values=26)

    def test_min_acima_do_max(self) -> None:
        with pytest.raises(ComponentError, match="mínimo não pode passar"):
            StringSelectMenu(custom_id="/x", options=[("a", "b")], min_values=3, max_values=2)

    def test_payload_completo(self) -> None:
        payload = StringSelectMenu(
            custom_id="/starter",
            placeholder="Escolha",
            min_values=1,
            max_values=3,
            options=[("Bulba", "bulbasaur")],
        ).to_dict()

        assert payload["type"] == 3
        assert payload["custom_id"] == "/starter"
        assert payload["placeholder"] == "Escolha"
        assert payload["max_values"] == 3
        assert payload["options"] == [{"label": "Bulba", "value": "bulbasaur"}]
        #: min_values == 1 é default — não vai no payload (ideia 17 §4).
        assert "min_values" not in payload


class TestOutrosSelects:
    def test_user_select_sem_options(self) -> None:
        payload = UserSelectMenu(custom_id="/party").to_dict()

        assert payload == {"type": 5, "custom_id": "/party"}

    def test_role_select(self) -> None:
        assert RoleSelectMenu(custom_id="/r").to_dict()["type"] == 6

    def test_mentionable_select(self) -> None:
        assert MentionableSelectMenu(custom_id="/m").to_dict()["type"] == 7

    def test_channel_select_com_filtro_de_tipo(self) -> None:
        payload = ChannelSelectMenu(
            custom_id="/c", channel_types=(ChannelType.GUILD_TEXT, ChannelType.GUILD_VOICE)
        ).to_dict()

        assert payload["type"] == 8
        assert payload["channel_types"] == [0, 2]


class TestFabricas:
    def test_create_string_select(self) -> None:
        menu = create_string_select(custom_id="/s", options=[("a", "b")], placeholder="Escolha")

        assert isinstance(menu, StringSelectMenu)

    def test_sem_custom_id_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem custom_id"):
            create_string_select(options=[("a", "b")])

    def test_create_channel_select_converte_tipos(self) -> None:
        menu = create_channel_select(custom_id="/c", channel_types=[ChannelType.GUILD_FORUM])

        assert menu.channel_types == (15,)
