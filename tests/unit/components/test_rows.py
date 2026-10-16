"""`ActionRow`, `create_row` e as fachadas de montagem — ideia 17 §1.

O fio: a regra "botão **ou** select" é do protocolo. O Discord rejeita
a mistura com erro genérico que não diz qual item conflitou; aqui o
erro carrega o índice.
"""

from __future__ import annotations

import pytest

from kryncord.components import (
    ActionRow,
    Button,
    ChannelSelectMenu,
    StringSelectMenu,
    TextDisplay,
    UserSelectMenu,
    create_components,
    create_components_rows,
    create_link_button,
    create_row,
)
from kryncord.enums import ButtonStyle
from kryncord.errors import ComponentError


def _botao(label: str = "Ok") -> Button:
    return Button(custom_id=f"/{label.lower()}", label=label, style=ButtonStyle.PRIMARY)


def _select() -> StringSelectMenu:
    return StringSelectMenu(custom_id="/fruits", options=[("Maçã", "apple")])


class TestCreateRow:
    def test_botoes_e_link_juntos(self) -> None:
        row = create_row(
            Button(custom_id="/confirm", label="Confirmar", style=ButtonStyle.SUCCESS),
            Button(custom_id="/cancel", label="Cancelar", style=ButtonStyle.DANGER),
            create_link_button("Docs", "https://docs.exemplo.com"),
        )

        assert len(row.components) == 3

    def test_none_e_false_filtram_condicional(self) -> None:
        """`cond and Button(...)` é o layout condicional da ideia 13 §6 —
        o mais barato que existe, e o filtro é o que faz funcionar."""
        row = create_row(_botao(), None, False, _botao("Dois"))

        assert len(row.components) == 2

    def test_str_na_row_e_erro_nas_duas_geracoes(self) -> None:
        with pytest.raises(ComponentError, match="texto na row não existe"):
            create_row(_botao(), "um texto")

    def test_true_e_int_sao_condicional_que_vazou(self) -> None:
        with pytest.raises(ComponentError, match="item 1 é bool"):
            create_row(_botao(), True)

        with pytest.raises(ComponentError, match="item 1 é int"):
            create_row(_botao(), 5)

    def test_row_vazia_depois_do_filtro(self) -> None:
        with pytest.raises(ComponentError, match="tudo filtrado"):
            create_row(None, False)

    def test_seis_botoes_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="máximo 5"):
            create_row(*[_botao(f"b{i}") for i in range(6)])

    def test_select_ocupa_a_row_inteira(self) -> None:
        with pytest.raises(ComponentError, match="ocupa a row inteira"):
            create_row(_select(), _botao())

    def test_text_display_nao_e_item_de_row(self) -> None:
        with pytest.raises(ComponentError, match="row aceita botão e select"):
            create_row(TextDisplay("texto"))

    def test_desconhecido_aponta_o_indice(self) -> None:
        with pytest.raises(ComponentError, match="item 1"):
            create_row(_botao(), object())


class TestActionRow:
    def test_select_sozinho_e_valido(self) -> None:
        row = ActionRow(components=(_select(),))

        assert row.components[0].type is StringSelectMenu.type

    def test_row_vazia_direto_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="vazia"):
            ActionRow(components=())

    def test_mistura_direta_na_classe_tambem_erro(self) -> None:
        with pytest.raises(ComponentError, match="ocupa a row inteira"):
            ActionRow(components=(_select(), _botao()))


class TestCreateComponentsRows:
    def test_filtra_e_aplica_o_teto(self) -> None:
        rows = create_components_rows(
            create_row(_botao()),
            None,
            False,
            create_row(_select()),
            create_row(_botao("A")),
            create_row(_botao("B")),
        )

        assert len(rows) == 4

    def test_seis_rows_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="máximo 5"):
            create_components_rows(*[create_row(_botao(str(i))) for i in range(6)])

    def test_botao_solto_ganha_row(self) -> None:
        rows = create_components_rows(_botao())

        assert isinstance(rows[0], ActionRow)

    def test_text_display_e_rejeitado_aqui(self) -> None:
        """A lista V1 é de rows — texto solto é árvore V2 (ou erro)."""
        with pytest.raises(ComponentError, match="TextDisplay"):
            create_components_rows(TextDisplay("oi"))


class TestCreateComponents:
    """A tabela de normalização da ideia 13 §6, linha a linha."""

    def test_str_vira_text_display(self) -> None:
        arvore = create_components("# Título", "Corpo")

        assert all(c.type is TextDisplay.type for c in arvore)
        assert arvore[0].content == "# Título"

    def test_none_e_false_filtram(self) -> None:
        admin = False
        arvore = create_components("a", None, admin and TextDisplay("área admin"), False)

        assert len(arvore) == 1

    def test_botao_e_envolvido_em_row(self) -> None:
        arvore = create_components(_botao())

        assert isinstance(arvore[0], ActionRow)

    def test_actionrow_passa_direto(self) -> None:
        row = create_row(_botao())
        arvore = create_components(row)

        assert arvore[0] is row

    def test_select_e_envolvido(self) -> None:
        arvore = create_components(UserSelectMenu(custom_id="/party"))

        assert isinstance(arvore[0], ActionRow)

    def test_attachment_vira_galeria(self) -> None:
        class AnexoFalso:
            url = "https://cdn.exemplo.com/a.png"

        arvore = create_components(AnexoFalso())

        assert arvore[0].type is __import__("kryncord").components.MediaGallery.type

    def test_true_e_int_sao_erro_com_indice(self) -> None:
        with pytest.raises(ComponentError, match="item 1 é bool"):
            create_components(TextDisplay("a"), True)

    def test_int_com_caminho_de_indice(self) -> None:
        with pytest.raises(ComponentError, match="item 0 é int"):
            create_components(42)

    def test_text_display_cru_passa(self) -> None:
        td = TextDisplay("solto")
        arvore = create_components(td)

        assert arvore[0] is td

    def test_str_com_channel_select_sozinho(self) -> None:
        arvore = create_components(ChannelSelectMenu(custom_id="/canal"))

        assert isinstance(arvore[0], ActionRow)
