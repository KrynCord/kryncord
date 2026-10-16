"""Modal, `Label` e os campos — ideias 14 §6 e 15 §6.

A regra que atravessa tudo: o sistema novo (`Label` + campo) é o único
caminho público. `ActionRow` + `TextInput` legado é só via `raw`, e o
builder nem oferece — dois caminhos de modal são duas fontes de
divergência.
"""

from __future__ import annotations

import pytest

from kryncord.components import (
    Button,
    Checkbox,
    CheckboxGroup,
    FileUpload,
    Label,
    Modal,
    RadioGroup,
    StringSelectMenu,
    TextDisplay,
    TextInput,
    TextInputStyle,
    create_label,
    create_modal,
    create_modal_fields,
    create_text_input,
)
from kryncord.errors import ComponentError


def _campo(custom_id: str = "name") -> TextInput:
    return TextInput(custom_id=custom_id)


class TestTextInput:
    def test_payload_minimo(self) -> None:
        assert TextInput(custom_id="name").to_dict() == {"type": 4, "custom_id": "name"}

    def test_paragraph_vai_no_payload_short_nao(self) -> None:
        curto = TextInput(custom_id="a").to_dict()
        longo = TextInput(custom_id="a", style=TextInputStyle.PARAGRAPH).to_dict()

        assert "style" not in curto
        assert longo["style"] == 2

    def test_limites_no_construtor(self) -> None:
        with pytest.raises(ComponentError, match="min_length"):
            TextInput(custom_id="a", min_length=-1)

        with pytest.raises(ComponentError, match="max_length"):
            TextInput(custom_id="a", max_length=4001)

    def test_custom_id_acima_de_100(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            TextInput(custom_id="x" * 101)

    def test_label_nao_e_campo(self) -> None:
        """O `label` do próprio TextInput está deprecated — não é campo
        aqui de propósito (ideia 15 §1). Passar é erro de digitação
        que aparece, não silêncio."""
        with pytest.raises(TypeError):
            TextInput(custom_id="a", label="Nome")  # type: ignore[call-arg]

    def test_create_text_input(self) -> None:
        assert (
            create_text_input("bio", style=TextInputStyle.PARAGRAPH).style
            is TextInputStyle.PARAGRAPH
        )


class TestLabel:
    def test_payload(self) -> None:
        payload = Label("Nome", _campo(), description="Seu nome completo").to_dict()

        assert payload == {
            "type": 18,
            "label": "Nome",
            "component": {"type": 4, "custom_id": "name"},
            "description": "Seu nome completo",
        }

    def test_sem_campo_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="Label aceita"):
            Label("Nome", None)  # type: ignore[arg-type]

    def test_text_display_dentro_e_rejeitado(self) -> None:
        """L6: `TextDisplay` é top-level do modal, não rótulo."""
        with pytest.raises(ComponentError, match="TextDisplay é top-level"):
            Label("Título", TextDisplay("x"))  # type: ignore[arg-type]

    def test_campo_sem_custom_id_e_erro(self) -> None:
        class CampoSemId:
            type = __import__("kryncord").enums.ComponentType.TEXT_INPUT
            custom_id = ""

        with pytest.raises(ComponentError, match="sem custom_id"):
            Label("Nome", CampoSemId())  # type: ignore[arg-type]

    def test_label_acima_de_45(self) -> None:
        with pytest.raises(ComponentError, match="45"):
            Label("x" * 46, _campo())

    def test_descricao_acima_de_100(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            Label("Nome", _campo(), description="d" * 101)

    def test_select_dentro_de_label_e_valido(self) -> None:
        menu = StringSelectMenu(custom_id="/fruits", options=[("Maçã", "apple")])

        assert Label("Frutas", menu).component is menu


class TestCreateLabel:
    def test_forma_a_descricao_posicional(self) -> None:
        label = create_label("Nome", "Seu nome completo", _campo())

        assert label.label == "Nome"
        assert label.description == "Seu nome completo"

    def test_forma_b_descricao_keyword(self) -> None:
        label = create_label("Idade", _campo(), description="Anos")

        assert label.description == "Anos"

    def test_forma_c_dict(self) -> None:
        label = create_label(
            {"label": "Username", "component": _campo("user"), "description": "Nick"}
        )

        assert label.component.custom_id == "user"

    def test_dict_com_outros_args_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="não mistura"):
            create_label({"label": "x", "component": _campo()}, description="d")

    def test_descricao_duas_vezes_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="duas vezes"):
            create_label("Nome", "desc", _campo(), description="outra")

    def test_primeiro_argumento_invalido(self) -> None:
        with pytest.raises(ComponentError, match="str"):
            create_label(42, _campo())  # type: ignore[arg-type]

    def test_forma_que_nao_casa(self) -> None:
        with pytest.raises(ComponentError, match="não casa forma nenhuma"):
            create_label("Nome", "desc", "mais desc")


class TestModal:
    def test_payload(self) -> None:
        modal = Modal(
            custom_id="/register/form",
            title="Cadastro",
            components=(Label("Nome", _campo()),),
        )

        assert modal.to_dict() == {
            "custom_id": "/register/form",
            "title": "Cadastro",
            "components": [
                {"type": 18, "label": "Nome", "component": {"type": 4, "custom_id": "name"}}
            ],
        }

    def test_text_display_solto_no_topo_e_valido(self) -> None:
        """M5: modal com `TextDisplay` de cabeçalho é o que o Discord
        liberou."""
        modal = Modal(
            custom_id="/f", title="T", components=(TextDisplay("Preencha:"), Label("N", _campo()))
        )

        assert modal.components[0].type is TextDisplay.type

    def test_titulo_acima_de_45(self) -> None:
        with pytest.raises(ComponentError, match="45"):
            Modal(custom_id="/f", title="x" * 46)

    def test_custom_id_acima_de_100(self) -> None:
        with pytest.raises(ComponentError, match="100"):
            Modal(custom_id="x" * 101, title="T")

    def test_seis_top_level(self) -> None:
        labels = tuple(Label(str(i), _campo(str(i))) for i in range(6))

        with pytest.raises(ComponentError, match="5"):
            Modal(custom_id="/f", title="T", components=labels)

    def test_text_input_solto_no_topo_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="mora dentro de Label"):
            Modal(custom_id="/f", title="T", components=(_campo(),))

    def test_action_row_legado_e_rejeitado(self) -> None:
        """M1: `ActionRow` no topo é o caminho deprecated — o builder
        nem constrói `ActionRow` com `TextInput` (a row recusa), e o
        modal recusa a row no top-level. O legado é só via `raw`."""
        from kryncord.components import create_row

        row = create_row(Button(custom_id="/x", label="Ok"))

        with pytest.raises(ComponentError, match="top-level aceita"):
            Modal(custom_id="/f", title="T", components=(row,))

    def test_custom_id_duplicado(self) -> None:
        """14 §6: dois ids iguais → submit ambíguo, sem debug possível."""
        with pytest.raises(ComponentError, match="duplicado"):
            Modal(
                custom_id="/f",
                title="T",
                components=(Label("A", _campo("x")), Label("B", _campo("x"))),
            )

    def test_create_modal(self) -> None:
        modal = create_modal("/f", "T", [Label("N", _campo())])

        assert modal.custom_id == "/f"

    def test_create_modal_fields_filtra_e_normaliza(self) -> None:
        campos = create_modal_fields("Preencha:", None, False, Label("N", _campo()))

        assert campos[0].type is TextDisplay.type
        assert campos[1].type is Label.type

    def test_create_modal_fields_rejeita_campo_solto(self) -> None:
        with pytest.raises(ComponentError, match="top-level"):
            create_modal_fields(_campo())


class TestCamposDeEscolha:
    """`FileUpload`, `RadioGroup`, `CheckboxGroup`, `Checkbox` — os
    quatro filhos de Label que a 0015 não alojava (0024, C1)."""

    def test_file_upload_payload(self) -> None:
        payload = FileUpload(custom_id="doc", max_values=3).to_dict()

        assert payload == {"type": 19, "custom_id": "doc", "max_values": 3}

    def test_file_upload_min_acima_do_max(self) -> None:
        with pytest.raises(ComponentError, match="min_values=3 > max_values=2"):
            FileUpload(custom_id="doc", min_values=3, max_values=2)

    def test_radio_group_payload(self) -> None:
        payload = RadioGroup(
            custom_id="prio", options=[{"label": "Baixa", "value": "low"}]
        ).to_dict()

        assert payload == {
            "type": 21,
            "custom_id": "prio",
            "options": [{"label": "Baixa", "value": "low"}],
        }

    def test_radio_group_sem_options(self) -> None:
        with pytest.raises(ComponentError, match="sem options"):
            RadioGroup(custom_id="prio")

    def test_checkbox_group_payload(self) -> None:
        payload = CheckboxGroup(custom_id="tags", options=(("A", "a"),)).to_dict()

        assert payload["type"] == 22

    def test_checkbox_sem_options_e_payload(self) -> None:
        """L5: `Checkbox` é um só — sem lista, e o leitor devolve bool."""
        assert Checkbox(custom_id="terms", default=True).to_dict() == {
            "type": 23,
            "custom_id": "terms",
            "default": True,
        }

    def test_todos_sao_filhos_validos_de_label(self) -> None:
        assert (
            Label("Anexo", FileUpload(custom_id="f", max_values=1)).component.type
            is FileUpload.type
        )
        assert (
            Label("P", RadioGroup(custom_id="p", options=[("Baixa", "low")])).component.type
            is RadioGroup.type
        )
        assert Label("T", Checkbox(custom_id="terms")).component.type is Checkbox.type

    def test_botao_dentro_de_label_e_rejeitado(self) -> None:
        with pytest.raises(ComponentError, match="Label aceita"):
            Label("Ação", Button(custom_id="/x", label="Ok"))
