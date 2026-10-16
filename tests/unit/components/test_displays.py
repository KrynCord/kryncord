"""Components V2 — árvore, limites e serialização — ideias 13 e 18 §5.

Os tetos de 40 e 4000 são os que o Discord aplica **em silêncio**:
sem validação, o render corta sem dizer onde. Validar na montagem
(via `walk()`) é o que move o erro para o autor.
"""

from __future__ import annotations

import pytest

from kryncord.components import (
    AccentColor,
    Button,
    Container,
    File,
    MediaGallery,
    Section,
    Separator,
    SeparatorSize,
    TextDisplay,
    Thumbnail,
    create_container,
    create_section,
    create_separator,
    parse_color,
    random_color,
    validate_components,
)
from kryncord.enums import ButtonStyle
from kryncord.errors import ComponentError


class TestTextDisplay:
    def test_payload(self) -> None:
        assert TextDisplay("oi").to_dict() == {"type": 10, "content": "oi"}

    def test_vazio_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="vazio"):
            TextDisplay("")


class TestSeparator:
    def test_default_tem_divisor_pequeno(self) -> None:
        assert Separator.default().to_dict() == {"type": 14, "spacing": 1, "divider": True}

    def test_large(self) -> None:
        """O exemplo literal da ideia 13 §8."""
        assert Separator.large().to_dict() == {"type": 14, "divider": True, "spacing": 2}

    def test_small_e_so_espaco(self) -> None:
        """ "Espaço pequeno" = spacing sem linha — o divisor é que
        faz a linha existir."""
        assert Separator.small().to_dict() == {"type": 14, "spacing": 1, "divider": False}

    def test_create_separator(self) -> None:
        assert create_separator(large=True).spacing is SeparatorSize.LARGE


class TestSection:
    def test_payload(self) -> None:
        section = Section(
            TextDisplay("**Status**\nOnline"), accessory=Thumbnail(url="https://x.com/a.png")
        )

        assert section.to_dict() == {
            "type": 9,
            "components": [{"type": 10, "content": "**Status**\nOnline"}],
            "accessory": {"type": 11, "media": {"url": "https://x.com/a.png"}},
        }

    def test_sem_accessory_e_erro_com_saida(self) -> None:
        with pytest.raises(ComponentError, match="use TextDisplay solto"):
            Section(TextDisplay("a"))

    def test_quatro_textos_e_erro(self) -> None:
        with pytest.raises(ComponentError, match=r"1\.\.3"):
            Section(
                *[TextDisplay(str(i)) for i in range(4)],
                accessory=Thumbnail(url="https://x.com/a.png"),
            )

    def test_accessory_que_nao_e_thumbnail_nem_botao(self) -> None:
        with pytest.raises(ComponentError, match="accessory File"):
            Section(TextDisplay("a"), accessory=File(url="attachment://doc.pdf"))

    def test_botao_como_accessory(self) -> None:
        section = Section(
            TextDisplay("a"),
            accessory=Button(custom_id="/detalhes", label="Detalhes", style=ButtonStyle.PRIMARY),
        )

        assert section.to_dict()["accessory"]["type"] == 2

    def test_str_vira_text_display(self) -> None:
        section = create_section("texto como str", accessory=Thumbnail(url="https://x.com/a.png"))

        assert section.components[0].content == "texto como str"

    def test_componente_estranho_como_texto(self) -> None:
        with pytest.raises(ComponentError, match="é o texto da seção"):
            Section(Separator.default(), accessory=Thumbnail(url="https://x.com/a.png"))


class TestThumbnail:
    def test_payload_com_descricao_e_spoiler(self) -> None:
        payload = Thumbnail(url="https://x.com/a.png", description="logo", spoiler=True).to_dict()

        assert payload == {
            "type": 11,
            "media": {"url": "https://x.com/a.png"},
            "description": "logo",
            "spoiler": True,
        }

    def test_url_acima_de_2048(self) -> None:
        with pytest.raises(ComponentError, match="2048"):
            Thumbnail(url="https://x.com/" + "a" * 2048)


class TestMediaGallery:
    def test_variadic_como_nas_ideias(self) -> None:
        galeria = MediaGallery("https://x.com/1.png", "https://x.com/2.png")

        assert galeria.to_dict() == {
            "type": 12,
            "items": [
                {"media": {"url": "https://x.com/1.png"}},
                {"media": {"url": "https://x.com/2.png"}},
            ],
        }

    def test_dict_com_spoiler(self) -> None:
        galeria = MediaGallery({"url": "https://x.com/1.png", "spoiler": True})

        assert galeria.items[0].spoiler is True

    def test_onze_imagens_e_erro(self) -> None:
        urls = [f"https://x.com/{i}.png" for i in range(11)]

        with pytest.raises(ComponentError, match="máximo 10"):
            MediaGallery(*urls)

    def test_vazia_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem imagens"):
            MediaGallery()

    def test_item_sem_url(self) -> None:
        with pytest.raises(ComponentError, match="sem url"):
            MediaGallery({"spoiler": True})


class TestFile:
    def test_payload(self) -> None:
        assert File("attachment://documento.pdf").to_dict() == {
            "type": 13,
            "file": {"url": "attachment://documento.pdf"},
        }

    def test_spoiler(self) -> None:
        assert File("attachment://s.pdf", spoiler=True).to_dict()["spoiler"] is True


class TestContainer:
    def test_cor_na_frente_como_nas_ideias(self) -> None:
        container = Container("#5865F2", TextDisplay("# Título"), TextDisplay("Corpo"))

        assert container.accent_color == 5793266
        assert container.to_dict() == {
            "type": 17,
            "accent_color": 5793266,
            "components": [
                {"type": 10, "content": "# Título"},
                {"type": 10, "content": "Corpo"},
            ],
        }

    def test_sem_cor(self) -> None:
        container = Container(TextDisplay("a"))

        assert container.accent_color is None
        assert "accent_color" not in container.to_dict()

    def test_sem_filhos_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="sem filhos"):
            Container("#5865F2")

    def test_container_dentro_de_container(self) -> None:
        interno = Container(TextDisplay("a"))

        with pytest.raises(ComponentError, match="um nível só"):
            Container(TextDisplay("b"), interno)

    def test_create_container(self) -> None:
        container = create_container("Blurple", TextDisplay("a"))

        assert container.accent_color == parse_color("Blurple")


class TestLimitesDaArvore:
    def test_quarenta_componentes_aninhados(self) -> None:
        arvore = [
            Container(
                "Blurple",
                TextDisplay("t"),
                Separator.default(),
                Section("a", accessory=Thumbnail(url="https://x.com/a.png")),
            )
            for _ in range(9)
        ]

        with pytest.raises(ComponentError, match="40"):
            validate_components(arvore)

    def test_quatro_mil_caracteres_somados(self) -> None:
        arvore = [TextDisplay("x" * 2100), TextDisplay("y" * 2100)]

        with pytest.raises(ComponentError, match="4000"):
            validate_components(arvore)

    def test_contagem_e_aninhada(self) -> None:
        """O `walk()` desce a árvore — Section conta os 3 textos e o
        accessory, Container conta tudo que está dentro."""
        arvore = [
            Section("a", "b", "c", accessory=Thumbnail(url="https://x.com/a.png")),
            Container("Blurple", TextDisplay("t"), Separator.default()),
        ]

        total = sum(1 for raiz in arvore for _ in raiz.walk())

        assert total == 8  # section + 3 textos + thumb + container + td + separator


class TestCores:
    def test_hex_com_hashtag(self) -> None:
        assert parse_color("#5865F2") == 5793266

    def test_nome_case_insensitive(self) -> None:
        assert parse_color("Green") == parse_color("green") == AccentColor.GREEN

    def test_inteiro_passa(self) -> None:
        assert parse_color(0xED4245) == 0xED4245

    def test_accent_color_passa(self) -> None:
        assert parse_color(AccentColor.BLURPLE) == 5793266

    def test_desconhecido_lista_os_aceitos(self) -> None:
        with pytest.raises(ComponentError, match="blurple"):
            parse_color("Laranja")

    def test_random_e_sempre_diferente_no_pior_caso(self) -> None:
        assert 0 <= random_color() <= 0xFFFFFF
