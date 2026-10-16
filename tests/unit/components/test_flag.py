"""A tabela V1 × V2 (ideia 18 §4), o `era` (X2) e o `ephemeral` corrigido.

Este arquivo é a fronteira onde os dois sistemas se encontram — o único
lugar do código que precisa conhecer os dois. E o teste do `ephemeral`
é a prova do bug real: como chave de payload o Discord **ignora em
silêncio** — a mensagem aparecia para todo mundo.
"""

from __future__ import annotations

import pytest

from kryncord.builders.messages import normalizar_mensagem
from kryncord.components import (
    ActionRow,
    Button,
    Container,
    File,
    Label,
    Modal,
    TextDisplay,
    TextInput,
    create_row,
    parse_flags,
    tem_v2,
    validate_message,
)
from kryncord.enums import MessageFlags
from kryncord.errors import ComponentError


def _row() -> ActionRow:
    return create_row(Button(custom_id="/ok", label="Ok"))


def _v2() -> Container:
    return Container("Blurple", TextDisplay("# Título"))


class TestTabelaDeConvivencia:
    def test_v1_completo_sem_flag(self) -> None:
        validate_message(content="Escolha:", components=(_row(),))

    def test_v2_completo_com_flag(self) -> None:
        validate_message(components=(_v2(),), flags=[MessageFlags.IS_COMPONENTS_V2])

    def test_content_com_flag_v2(self) -> None:
        """O Discord **ignora** o content nessa combinação — o erro
        nosso é o que impede o 'funcionou no teste, não funcionou no
        servidor'."""
        with pytest.raises(ComponentError, match="ignora em silêncio"):
            validate_message(content="oi", components=(_v2(),), flags=MessageFlags.IS_COMPONENTS_V2)

    def test_embeds_com_flag_v2(self) -> None:
        with pytest.raises(ComponentError, match="embeds"):
            validate_message(
                embeds=({"title": "x"},),
                components=(_v2(),),
                flags=MessageFlags.IS_COMPONENTS_V2,
            )

    def test_v2_sem_flag(self) -> None:
        with pytest.raises(ComponentError, match="sem a flag"):
            validate_message(components=(_v2(),))

    def test_flag_sem_components(self) -> None:
        with pytest.raises(ComponentError, match="flag órfã"):
            validate_message(flags=MessageFlags.IS_COMPONENTS_V2)

    def test_campo_de_modal_em_mensagem(self) -> None:
        """`era="modal"` é o que impede TextInput de vazar para
        mensagem — herdar 'both' do pai faria passar."""
        with pytest.raises(ComponentError, match="campo de modal"):
            validate_message(components=(TextInput(custom_id="x"),))

    def test_file_v2_com_flag_valida(self) -> None:
        validate_message(
            components=(File(url="attachment://doc.pdf"),),
            flags=MessageFlags.IS_COMPONENTS_V2,
        )


class TestTemV2:
    def test_action_row_nao_e_v2(self) -> None:
        assert tem_v2((_row(),)) is False

    def test_container_e_v2(self) -> None:
        assert tem_v2((_v2(),)) is True

    def test_lista_vazia_nao_e_v2(self) -> None:
        assert tem_v2(()) is False


class TestEra:
    """X2: todo componente declara época — atributo de classe, sem
    lista de nomes espalhada (ideia 18 §8)."""

    def test_botao_e_both(self) -> None:
        assert Button.era == "both"
        assert ActionRow.era == "both"

    def test_displays_sao_v2(self) -> None:
        assert TextDisplay.era == "v2"
        assert Container.era == "v2"
        assert File.era == "v2"

    def test_campos_de_modal_sao_modal(self) -> None:
        assert TextInput.era == "modal"
        assert Label.era == "modal"

    def test_modal_nao_declara_era(self) -> None:
        """Modal é resposta, não componente de mensagem — época é
        conversa das duas gerações de layout."""
        assert not hasattr(Modal, "era")


class TestParseFlags:
    def test_intflag_unica(self) -> None:
        assert parse_flags(MessageFlags.EPHEMERAL) == 64

    def test_lista_como_nas_ideias(self) -> None:
        assert parse_flags([MessageFlags.EPHEMERAL, MessageFlags.IS_COMPONENTS_V2]) == 64 | (
            1 << 15
        )

    def test_int_cru_passa(self) -> None:
        assert parse_flags(64) == 64

    def test_none_passa(self) -> None:
        assert parse_flags(None) is None

    def test_nome_solto_e_erro(self) -> None:
        with pytest.raises(ComponentError, match="não é MessageFlags"):
            parse_flags(["ephemeral"])  # type: ignore[list-item]


class TestNormalizarMensagem:
    def test_dict_cru_entra_dict_cru_sai(self) -> None:
        """Ajuste pedido pelo juiz na 0024: normalização **aditiva** —
        quem já mandava dict continua funcionando."""
        saida = normalizar_mensagem({"content": "oi", "tts": True})

        assert saida == {"content": "oi", "tts": True}

    def test_componente_serializa(self) -> None:
        saida = normalizar_mensagem({"components": [_row()]})

        assert saida["components"] == [
            {"type": 1, "components": [{"type": 2, "style": 1, "custom_id": "/ok", "label": "Ok"}]}
        ]

    def test_v2_true_vira_flag(self) -> None:
        """O atalho da 0015: `v2=True` é da resposta, e seta a flag."""
        saida = normalizar_mensagem({"components": [_v2()], "v2": True})

        assert saida["flags"] == int(MessageFlags.IS_COMPONENTS_V2)
        assert "v2" not in saida

    def test_ephemeral_vira_flag_nao_chave(self) -> None:
        """O bug real: `{"ephemeral": True}` no payload é **ignorado**
        pelo Discord — a mensagem aparecia para todo mundo, sem erro
        em lugar nenhum."""
        saida = normalizar_mensagem({"content": "só pra você", "ephemeral": True})

        assert saida == {"content": "só pra você", "flags": 64}

    def test_ephemeral_e_flags_somam(self) -> None:
        saida = normalizar_mensagem(
            {"components": [_v2()], "ephemeral": True, "flags": [MessageFlags.IS_COMPONENTS_V2]}
        )

        assert saida["flags"] == 64 | int(MessageFlags.IS_COMPONENTS_V2)

    def test_embed_serializa(self) -> None:
        from kryncord.builders.embed import Embed

        saida = normalizar_mensagem({"embeds": [Embed(title="T", color="Blurple")]})

        assert saida["embeds"] == [{"title": "T", "color": 5793266}]

    def test_v2_com_content_e_erro_aqui(self) -> None:
        with pytest.raises(ComponentError, match="ignora em silêncio"):
            normalizar_mensagem({"content": "oi", "components": [_v2()], "v2": True})

    def test_chave_vazia_sai_do_payload(self) -> None:
        saida = normalizar_mensagem({"components": None, "flags": None})

        assert "components" not in saida
        assert "flags" not in saida


class TestReplyOptions:
    def test_to_payload_v1(self) -> None:
        from kryncord.builders.messages import ReplyOptions

        opts = ReplyOptions(content="Escolha:", components=(_row(),))

        assert opts.to_payload() == {
            "content": "Escolha:",
            "components": [
                {
                    "type": 1,
                    "components": [{"type": 2, "style": 1, "custom_id": "/ok", "label": "Ok"}],
                }
            ],
        }

    def test_to_payload_v2(self) -> None:
        from kryncord.builders.messages import ReplyOptions

        opts = ReplyOptions(components=(_v2(),), v2=True)

        assert opts.to_payload()["flags"] == int(MessageFlags.IS_COMPONENTS_V2)

    def test_to_payload_mistura_e_erro(self) -> None:
        from kryncord.builders.messages import ReplyOptions

        with pytest.raises(ComponentError, match="ignora em silêncio"):
            ReplyOptions(content="oi", components=(_v2(),), v2=True).to_payload()
