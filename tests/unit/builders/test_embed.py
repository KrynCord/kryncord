"""`Embed` — limites, normalização, `create_embed` e serialização (ideia 16).

O limite de 6000 somados é o que mais passa batido: cabem 10 campos de
1024 e ainda estoura — é a única validação que precisa de travessia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

import pytest

from kryncord.builders.embed import (
    MAX_TOTAL,
    ZERO_WIDTH,
    Embed,
    EmbedAuthor,
    EmbedField,
    EmbedFooter,
    EmbedImage,
    create_embed,
    random_color,
)
from kryncord.errors import ComponentError


class TestLimites:
    def test_titulo_acima_de_256(self) -> None:
        with pytest.raises(ComponentError, match="256"):
            Embed(title="x" * 257)

    def test_descricao_acima_de_4096(self) -> None:
        with pytest.raises(ComponentError, match="4096"):
            Embed(description="x" * 4097)

    def test_vinte_e_seis_campos(self) -> None:
        with pytest.raises(ComponentError, match="25"):
            Embed(fields=[(f"f{i}", "v") for i in range(26)])

    def test_campo_gigante(self) -> None:
        with pytest.raises(ComponentError, match="1024"):
            EmbedField("ok", "x" * 1025)

    def test_footer_gigante(self) -> None:
        with pytest.raises(ComponentError, match="2048"):
            EmbedFooter("x" * 2049)

    def test_autor_gigante(self) -> None:
        with pytest.raises(ComponentError, match="256"):
            EmbedAuthor("x" * 257)

    def test_total_de_6000_somado(self) -> None:
        """10 campos de 1024 caberiam — a soma é a que não cabe."""
        campos = [EmbedField(f"c{i}", "v" * 1024) for i in range(5)]

        with pytest.raises(ComponentError, match=str(MAX_TOTAL)):
            Embed(title="t" * 256, description="d" * 4096, fields=campos)


class TestNormalizacao:
    def test_descricao_lista_junta_com_barra_n(self) -> None:
        """E3: `description=[...]` é o que elimina o brBuilder."""
        embed = Embed(description=["Obrigado por entrar!", "", "Leia as regras"])

        assert embed.description == "Obrigado por entrar!\n\nLeia as regras"

    def test_cor_por_nome(self) -> None:
        assert Embed(color="Blurple").color == 5793266

    def test_cor_por_hex(self) -> None:
        assert Embed(color="#5865F2").color == 5793266

    def test_random_na_classe_e_erro(self) -> None:
        """E4: o **mesmo** embed tem que renderizar igual sempre que
        for construído. Quem quer sorte pede — `create_embed`."""
        with pytest.raises(ComponentError, match="renderizaria diferente"):
            Embed(color="Random")

    def test_footer_str_vira_objeto(self) -> None:
        assert Embed(footer="ID: 123").footer == EmbedFooter("ID: 123")

    def test_author_str_vira_objeto(self) -> None:
        assert Embed(author="Bot").author == EmbedAuthor("Bot")

    def test_image_str_vira_dict(self) -> None:
        assert Embed(image="https://x.com/a.png").image == EmbedImage("https://x.com/a.png")

    def test_image_de_attachment(self) -> None:
        class Anexo:
            url = "https://cdn.x.com/a.png"

        assert Embed(image=Anexo()).image.url == Anexo.url

    def test_campo_str_usa_zero_width(self) -> None:
        """E5: campo sem valor é inválido para o Discord — o separador
        de coluna usa o zero-width."""
        embed = Embed(fields=["Separador"])

        assert embed.fields[0].value == ZERO_WIDTH

    def test_campo_tuple_posicional(self) -> None:
        assert Embed(fields=[("Nível", "42")]).fields[0] == EmbedField("Nível", "42")

    def test_campo_dict(self) -> None:
        assert Embed(fields=[{"name": "N", "value": "V", "inline": True}]).fields[0].inline is True

    def test_timestamp_true_e_agora_utc(self) -> None:
        antes = datetime.now(UTC).isoformat()

        marcado = Embed(timestamp=True).timestamp

        assert marcado is not None and marcado >= antes

    def test_timestamp_datetime_converte_utc(self) -> None:
        marcado = Embed(timestamp=datetime(2024, 1, 1, 12, tzinfo=UTC)).timestamp

        assert marcado is not None and marcado.startswith("2024-01-01T12:00:00")

    def test_cor_invalida_lista_nomes(self) -> None:
        with pytest.raises(ComponentError, match="blurple"):
            Embed(color="Laranja")


class TestSerializacao:
    def test_payload_minimo_e_vazio(self) -> None:
        assert Embed().to_dict() == {}

    def test_payload_completo(self) -> None:
        payload = Embed(
            title="Perfil",
            description="Info",
            url="https://x.com",
            color="Blurple",
            timestamp="2024-01-01T00:00:00+00:00",
            footer=EmbedFooter("ID: 1", icon_url="https://x.com/i.png"),
            image="https://x.com/i.png",
            thumbnail="https://x.com/t.png",
            author=EmbedAuthor("Bot", url="https://x.com", icon_url="https://x.com/b.png"),
            fields=[EmbedField("Nível", "42", inline=True)],
        ).to_dict()

        assert payload == {
            "title": "Perfil",
            "description": "Info",
            "url": "https://x.com",
            "color": 5793266,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "footer": {"text": "ID: 1", "icon_url": "https://x.com/i.png"},
            "image": {"url": "https://x.com/i.png"},
            "thumbnail": {"url": "https://x.com/t.png"},
            "author": {"name": "Bot", "url": "https://x.com", "icon_url": "https://x.com/b.png"},
            "fields": [{"name": "Nível", "value": "42", "inline": True}],
        }

    def test_inline_somente_quando_true(self) -> None:
        assert "inline" not in EmbedField("a", "b").to_dict()


class TestCreateEmbed:
    def test_o_exemplo_da_ideia_16(self) -> None:
        embed = create_embed(
            title="Bem-vindo!",
            description=["Obrigado por entrar!", "", "Leia as regras"],
            color="Green",
            timestamp=True,
            footer="Equipe",
        )

        assert embed.color == 0x57F287
        assert embed.footer == EmbedFooter("Equipe")

    def test_random_aqui_e_valido(self) -> None:
        embed = create_embed(title="T", color="Random")

        assert 0 <= embed.color <= 0xFFFFFF

    def test_random_color_pura(self) -> None:
        assert 0 <= random_color() <= 0xFFFFFF

    def test_source_de_message(self) -> None:
        class Mensagem:
            raw: ClassVar[dict] = {"embeds": [{"title": "Original", "description": "d"}]}

        novo = create_embed(source=Mensagem(), index=0, color="Red")

        assert novo.title == "Original"
        assert novo.color == 0xED4245

    def test_source_sem_embeds(self) -> None:
        class Vazia:
            raw: ClassVar[dict] = {}

        with pytest.raises(ComponentError, match="não tem embed 0"):
            create_embed(source=Vazia())

    def test_source_sem_nada(self) -> None:
        """Sem `.embeds` nem `.raw.embeds` — a mensagem diz quantos
        embeds o source tem, que aqui é nenhum."""

        class Nada:
            pass

        with pytest.raises(ComponentError, match="não tem embed 0"):
            create_embed(source=Nada())

    def test_source_com_builder(self) -> None:
        """`source.embeds` quando existe — mensagem que a gente
        montou, não payload cru."""

        class Minha:
            embeds: ClassVar[list] = [Embed(title="Original")]

        ajustado = create_embed(source=Minha(), description="novo")

        assert ajustado.title == "Original"
        assert ajustado.description == "novo"

    def test_kwargs_vencem_o_source(self) -> None:
        class Mensagem:
            raw: ClassVar[dict] = {"embeds": [{"title": "Velho"}]}

        novo = create_embed(source=Mensagem(), title="Novo")

        assert novo.title == "Novo"
