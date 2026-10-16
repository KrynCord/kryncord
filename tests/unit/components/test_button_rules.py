"""A tabela style × campo do `Button` — ideia 17 §2.

Cada linha da tabela é um teste: `custom_id` em `LINK` é erro, `url`
em `PRIMARY` é erro, `PREMIUM` sem `sku_id` é erro. E a linha que não
está na tabela é a mais importante: **sem `custom_id` não há botão**
(B5) — id gerado some no submit, e não há como debugar um id que
ninguém escreveu.
"""

from __future__ import annotations

import pytest

from kryncord.components import Button, create_link_button
from kryncord.enums import ButtonStyle
from kryncord.errors import ComponentError


class TestInterativos:
    @pytest.mark.parametrize(
        "style",
        [ButtonStyle.PRIMARY, ButtonStyle.SECONDARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER],
    )
    async def test_custom_id_obrigatorio(self, style: ButtonStyle) -> None:
        with pytest.raises(ComponentError, match="sem custom_id"):
            Button(label="Ok", style=style)

    @pytest.mark.parametrize(
        "style",
        [ButtonStyle.PRIMARY, ButtonStyle.SECONDARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER],
    )
    async def test_url_e_sku_proibidos(self, style: ButtonStyle) -> None:
        with pytest.raises(ComponentError, match="não aceita url/sku_id"):
            Button(custom_id="/a", label="Ok", style=style, url="https://x.com")

        with pytest.raises(ComponentError, match="não aceita url/sku_id"):
            Button(custom_id="/a", label="Ok", style=style, sku_id=99)


class TestLink:
    def test_custom_id_proibido(self) -> None:
        with pytest.raises(ComponentError, match="link não dispara interação"):
            Button(label="Site", url="https://exemplo.com", style=ButtonStyle.LINK, custom_id="/x")

    def test_sem_url_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem url"):
            Button(label="Site", style=ButtonStyle.LINK)

    def test_com_url_valida(self) -> None:
        botao = Button(label="Site", url="https://exemplo.com", style=ButtonStyle.LINK)

        assert botao.style is ButtonStyle.LINK

    def test_url_sem_style_link_aponta_o_caminho(self) -> None:
        """Quem escreve `Button(url=…)` e esqueceu o style precisa da
        dica do style — não de uma reclamação de custom_id."""
        with pytest.raises(ComponentError, match=r"style=ButtonStyle\.LINK"):
            Button(label="Site", url="https://exemplo.com")


class TestPremium:
    def test_sem_sku_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem sku_id"):
            Button(style=ButtonStyle.PREMIUM)

    def test_label_proibido(self) -> None:
        with pytest.raises(ComponentError, match="não aceita label"):
            Button(style=ButtonStyle.PREMIUM, sku_id=99, label="Comprar")

    def test_custom_id_e_url_proibidos(self) -> None:
        with pytest.raises(ComponentError, match="não aceita custom_id"):
            Button(style=ButtonStyle.PREMIUM, sku_id=99, custom_id="/x")

        with pytest.raises(ComponentError, match="não aceita custom_id"):
            Button(style=ButtonStyle.PREMIUM, sku_id=99, url="https://x")


class TestVisibilidade:
    def test_sem_label_e_sem_emoji(self) -> None:
        with pytest.raises(ComponentError, match="invisível"):
            Button(custom_id="/a")

    def test_emoji_sozinho_passa(self) -> None:
        """O "ou emoji sozinho" da tabela (17 §2)."""
        botao = Button(custom_id="/a", emoji="🔥")

        assert botao.label is None


class TestLimites:
    def test_label_acima_de_80(self) -> None:
        with pytest.raises(ComponentError, match="80"):
            Button(custom_id="/a", label="x" * 81)

    def test_custom_id_acima_de_100(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            Button(custom_id="/a" + "b" * 100, label="Ok")

    def test_url_acima_de_512(self) -> None:
        with pytest.raises(ComponentError, match="512"):
            Button(label="Site", url="https://x.com/" + "a" * 512)


class TestCreateLinkButton:
    def test_posicional_como_nas_ideias(self) -> None:
        botao = create_link_button("Documentação", "https://docs.exemplo.com")

        assert botao.style is ButtonStyle.LINK
        assert botao.label == "Documentação"

    def test_sem_url_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem url"):
            create_link_button("Docs")

    def test_emoji_kwarg_passa(self) -> None:
        botao = create_link_button("Docs", "https://x.com", emoji="📄")

        assert botao.emoji == "📄"


class TestSerializacao:
    def test_dict_do_botao_interativo(self) -> None:
        assert Button(custom_id="/ok", label="Ok", style=ButtonStyle.SUCCESS).to_dict() == {
            "type": 2,
            "style": 3,
            "custom_id": "/ok",
            "label": "Ok",
        }

    def test_dict_do_link(self) -> None:
        botao = create_link_button("Docs", "https://x.com")

        assert botao.to_dict() == {"type": 2, "style": 5, "label": "Docs", "url": "https://x.com"}

    def test_style_e_inteiro_no_payload(self) -> None:
        assert Button(custom_id="/a", label="X", emoji="✅").to_dict()["style"] == 1

    def test_emoji_str_vira_objeto_nome(self) -> None:
        payload = Button(custom_id="/a", label="X", emoji="🔥").to_dict()

        assert payload["emoji"] == {"name": "🔥"}

    def test_sku_id_vira_str(self) -> None:
        payload = Button(style=ButtonStyle.PREMIUM, sku_id=123).to_dict()

        assert payload["sku_id"] == "123"

    def test_disabled_somente_quando_true(self) -> None:
        assert "disabled" not in Button(custom_id="/a", label="X").to_dict()
        assert Button(custom_id="/a", label="X", disabled=True).to_dict()["disabled"] is True
