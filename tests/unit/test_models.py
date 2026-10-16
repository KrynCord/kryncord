"""Testes dos modelos e das primitivas de parsing.

O que se testa aqui não é o payload feliz — é o payload *errado*. O
Discord manda parcial, omite campo, manda tipo errado às vezes, e a
promessa dos modelos é que nada disso derruba o bot. `models/base.py`
documenta essa tolerância; os testes abaixo são a prova.

O caso mais importante é o de `PartialMessage`: ele existe para que
``partial.content`` *não exista*. Se um dia alguém "melhorar" o modelo
adicionando o campo com default, este teste tem que quebrar.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from kryncord.models import (
    DISCORD_EPOCH_MS,
    ApplicationCommand,
    Attachment,
    Ban,
    Channel,
    Guild,
    Interaction,
    Member,
    Message,
    PartialChannel,
    PartialGuild,
    PartialMessage,
    Ready,
    Role,
    User,
    Webhook,
    boolean,
    cdn,
    default_avatar_url,
    integer,
    mapping,
    parse_all,
    sequence,
    snowflake,
    snowflake_datetime,
    string,
    timestamp,
)

# ==========================================================================
# Primitivas — o alicerce que todos os modelos usam
# ==========================================================================


class TestSnowflake:
    def test_converte_string_de_digitos_em_int(self) -> None:
        assert snowflake({"id": "123456789012345678"}, "id") == 123456789012345678

    def test_aceita_int_ja_convertido(self) -> None:
        assert snowflake({"id": 42}, "id") == 42

    def test_bool_nao_vira_id(self) -> None:
        """`bool` é subclasse de `int` em Python.

        Sem esta checar, ``{"id": true}`` viraria ``id == 1`` e o bot
        perseguiria um usuário que não existe.
        """
        assert snowflake({"id": True}, "id", default=-1) == -1

    def test_string_nao_numerica_vai_para_o_default(self) -> None:
        assert snowflake({"id": "abc"}, "id", default=None) is None

    def test_campo_ausente_devolve_o_default(self) -> None:
        assert snowflake({}, "id", default=7) == 7

    def test_string_vazia_devolve_o_default(self) -> None:
        assert snowflake({"id": ""}, "id", default=None) is None


class TestString:
    def test_devolve_o_valor(self) -> None:
        assert string({"n": "oi"}, "n") == "oi"

    def test_string_vazia_e_valor_legitimo(self) -> None:
        """Mensagem sem texto e mensagem vazia não são a mesma coisa."""
        assert string({"n": ""}, "n", default="fallback") == ""

    def test_tipo_errado_devolve_o_default(self) -> None:
        assert string({"n": 1}, "n", default=None) is None


class TestInteger:
    def test_devolve_o_valor(self) -> None:
        assert integer({"n": 5}, "n") == 5

    def test_bool_nao_passa(self) -> None:
        assert integer({"n": True}, "n", default=-1) == -1


class TestBoolean:
    def test_devolve_o_valor(self) -> None:
        assert boolean({"n": True}, "n") is True

    def test_falso_e_valor_legitimo(self) -> None:
        assert boolean({"n": False}, "n", default=True) is False

    def test_ausente_devolve_o_default(self) -> None:
        """O Discord omite flags falsas — ausente não é o mesmo que falso."""
        assert boolean({}, "n", default=True) is True


class TestTimestamp:
    def test_parse_iso_com_z(self) -> None:
        assert timestamp({"t": "2024-01-01T12:00:00Z"}, "t") == datetime(
            2024, 1, 1, 12, 0, tzinfo=UTC
        )

    def test_parse_iso_com_fuso_explicito(self) -> None:
        """`Z` e `+00:00` são o mesmo instante e viram o mesmo objeto."""
        com_z = timestamp({"t": "2024-01-01T12:00:00Z"}, "t")
        com_fuso = timestamp({"t": "2024-01-01T12:00:00+00:00"}, "t")
        assert com_z == com_fuso

    def test_sem_fuso_assume_utc(self) -> None:
        """Um datetime sem fuso não compara com os outros — assumir UTC
        é melhor que produzir algo inutilizável."""
        result = timestamp({"t": "2024-01-01T12:00:00"}, "t")
        assert result is not None
        assert result.tzinfo is not None

    def test_malformado_devolve_none(self) -> None:
        assert timestamp({"t": "ontem"}, "t") is None

    def test_ausente_devolve_none(self) -> None:
        assert timestamp({}, "t") is None

    def test_nao_string_devolve_none(self) -> None:
        assert timestamp({"t": 1704100800}, "t") is None


class TestMappingESequence:
    def test_mapping_devolve_o_objeto(self) -> None:
        assert mapping({"a": {"b": 1}}, "a") == {"b": 1}

    def test_mapping_ausente_devolve_vazio(self) -> None:
        """Vazio e não `None`: quase todo uso é `nested.get(...)`, e
        obrigar checagem nula em cada chamada só polui o chamador."""
        assert mapping({}, "a") == {}

    def test_mapping_nao_objeto_devolve_vazio(self) -> None:
        assert mapping({"a": [1]}, "a") == {}

    def test_sequence_devolve_tuple(self) -> None:
        """Tuple e não list: modelo `frozen` com lista mutável dentro é
        um objeto imutável de mentira."""
        result = sequence({"a": [1, 2]}, "a")
        assert result == (1, 2)
        assert isinstance(result, tuple)

    def test_sequence_ausente_devolve_vazio(self) -> None:
        assert sequence({}, "a") == ()

    def test_sequence_com_string_nao_e_lista(self) -> None:
        assert sequence({"a": "abc"}, "a") == ()


class TestParseAll:
    def test_parseia_cada_item(self) -> None:
        result = parse_all({"a": [{"id": "1"}, {"id": "2"}]}, "a", PartialGuild.from_payload)
        assert result == (PartialGuild(id=1), PartialGuild(id=2))

    def test_descarta_o_que_nao_deu(self) -> None:
        """O Discord manda entradas ruins junto das boas. Derrubar a
        lista inteira seria perder um evento válido para punir um
        payload que o bot não pediu."""
        result = parse_all(
            {"a": [{"id": "1"}, {"sem": "id"}, "não é objeto"]}, "a", PartialGuild.from_payload
        )
        assert result == (PartialGuild(id=1),)

    def test_ausente_devolve_vazio(self) -> None:
        assert parse_all({}, "a", PartialGuild.from_payload) == ()

    def test_nao_tenta_em_item_que_nao_e_objeto(self) -> None:
        """Só itens `Mapping` chegam ao parser — o resto nem tenta."""
        chamado: list[object] = []

        def parser(item: Mapping[str, Any]) -> int:
            chamado.append(item)
            return 1

        parse_all({"a": ["texto", 42, {"id": "1"}]}, "a", parser)
        assert chamado == [{"id": "1"}]


class TestSnowflakeDatetime:
    def test_extrai_o_momento_de_criacao(self) -> None:
        moment = datetime(2020, 1, 1, tzinfo=UTC)
        ms = int(moment.timestamp() * 1000) - DISCORD_EPOCH_MS
        assert snowflake_datetime(ms << 22) == moment

    def test_22_bits_baixos_nao_sao_tempo(self) -> None:
        """Os bits de contador e worker ficam fora do cálculo — se
        entrassem, dois IDs criados no mesmo milissegundo dariam datas
        diferentes."""
        base = (int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000) - DISCORD_EPOCH_MS) << 22
        assert snowflake_datetime(base) == snowflake_datetime(base | 0x3FFFFF)


class TestCdn:
    def test_monta_url(self) -> None:
        assert cdn("avatars/1/x.png") == "https://cdn.discordapp.com/avatars/1/x.png"

    def test_avatar_generico_e_de_embed(self) -> None:
        assert "/embed/avatars/" in default_avatar_url(0)


# ==========================================================================
# User
# ==========================================================================


class TestUser:
    def test_payload_completo(self) -> None:
        user = User.from_payload(
            {
                "id": "123",
                "username": "gustavo",
                "discriminator": "0001",
                "global_name": "Gustavo",
                "avatar": "abc123",
                "bot": True,
            }
        )
        assert user.id == 123
        assert user.username == "gustavo"
        assert user.bot is True

    def test_display_name_prefere_o_global_name(self) -> None:
        user = User.from_payload({"id": "1", "username": "login", "global_name": "Exibido"})
        assert user.display_name == "Exibido"

    def test_display_name_cai_no_username(self) -> None:
        """Conta nova não tem `global_name` — e ainda assim tem nome
        para mostrar."""
        user = User.from_payload({"id": "1", "username": "login"})
        assert user.display_name == "login"

    def test_avatar_url_none_sem_avatar(self) -> None:
        user = User.from_payload({"id": "1", "username": "x"})
        assert user.avatar_url is None

    def test_avatar_url_monta_o_caminho(self) -> None:
        user = User.from_payload({"id": "42", "username": "x", "avatar": "hash"})
        assert user.avatar_url == "https://cdn.discordapp.com/avatars/42/hash.png"

    def test_display_avatar_url_nunca_e_none(self) -> None:
        """É o que se coloca num `<img>` sem tratar o caso omissso."""
        user = User.from_payload({"id": "42", "username": "x", "discriminator": "7"})
        assert "cdn.discordapp.com" in user.display_avatar_url

    def test_discriminator_zero_para_conta_nova(self) -> None:
        user = User.from_payload({"id": "1", "username": "x", "discriminator": "0"})
        assert user.discriminator_value == 0

    def test_mention(self) -> None:
        user = User.from_payload({"id": "99", "username": "x"})
        assert user.mention == "<@99>"

    def test_payload_sem_nada_devolve_none(self) -> None:
        """Uma conta sem ID não é conta. `None` é o sinal de que não deu
        para interpretar — o dispatcher entrega o payload cru."""
        assert User.from_payload({}) is None

    def test_id_int_e_aceito(self) -> None:
        """Aceita tanto a string do JSON quanto um int já convertido —
        o segundo aparece quando o payload passou por outro caminho."""
        assert User.from_payload({"id": 42, "username": "x"}).id == 42  # type: ignore[union-attr]


# ==========================================================================
# Member
# ==========================================================================


class TestMember:
    def test_devolve_none_sem_user(self) -> None:
        """Um `Member` sem conta não é ninguém. Devolver um com usuário
        inventado seria pior que devolver nada."""
        assert Member.from_payload({"nick": "fulano"}) is None

    def test_parse_completo(self) -> None:
        member = Member.from_payload(
            {
                "user": {"id": "1", "username": "x"},
                "nick": "apelido",
                "roles": ["111", "222"],
                "joined_at": "2024-01-01T00:00:00Z",
            }
        )
        assert member is not None
        assert member.roles == (111, 222)
        assert member.nick == "apelido"

    def test_roles_viram_int_nao_string(self) -> None:
        """O Discord manda IDs como string. Guardar str faria
        ``"123" == 123`` falhar silenciosamente."""
        member = Member.from_payload({"user": {"id": "1", "username": "x"}, "roles": ["9"]})
        assert member is not None
        assert member.roles == (9,)
        assert all(isinstance(r, int) for r in member.roles)

    def test_display_name_prefere_o_apelido_da_guild(self) -> None:
        member = Member.from_payload(
            {"user": {"id": "1", "username": "login", "global_name": "Global"}, "nick": "Nick"}
        )
        assert member is not None
        assert member.display_name == "Nick"

    def test_display_name_cai_no_usuario(self) -> None:
        member = Member.from_payload({"user": {"id": "1", "username": "login"}})
        assert member is not None
        assert member.display_name == "login"


# ==========================================================================
# Attachment
# ==========================================================================


class TestAttachment:
    def test_parse(self) -> None:
        att = Attachment.from_payload(
            {
                "id": "1",
                "filename": "foto.png",
                "url": "https://cdn/x.png",
                "proxy_url": "https://cdn/p/x.png",
                "size": 2048,
                "content_type": "image/png",
                "width": 100,
                "height": 50,
            }
        )
        assert att.filename == "foto.png"
        assert att.size == 2048
        assert att.is_image is True

    def test_is_image_false_para_nao_imagem(self) -> None:
        att = Attachment.from_payload(
            {"id": "1", "filename": "a.txt", "content_type": "text/plain"}
        )
        assert att.is_image is False

    def test_is_image_false_sem_content_type(self) -> None:
        att = Attachment.from_payload({"id": "1", "filename": "a"})
        assert att.is_image is False


# ==========================================================================
# Message
# ==========================================================================


class TestMessage:
    def test_payload_completo(self) -> None:
        message = Message.from_payload(
            {
                "id": "100",
                "channel_id": "200",
                "guild_id": "300",
                "author": {"id": "1", "username": "x", "global_name": "X"},
                "member": {"user": {"id": "1", "username": "x"}, "nick": "N"},
                "content": "oi",
                "timestamp": "2024-01-01T00:00:00Z",
                "type": 0,
            }
        )
        assert message.id == 100
        assert message.content == "oi"
        assert message.author is not None
        assert message.author.display_name == "X"
        assert message.member is not None
        assert message.member.nick == "N"

    def test_content_none_nao_vazio(self) -> None:
        """Mensagem sem texto e mensagem vazia não são a mesma coisa."""
        message = Message.from_payload({"id": "1", "channel_id": "2"})
        assert message.content is None

    def test_string_vazia_e_valor_legitimo(self) -> None:
        message = Message.from_payload({"id": "1", "channel_id": "2", "content": ""})
        assert message.content == ""

    def test_author_none_nao_inventado(self) -> None:
        """Mensagem de webhook sem autor. Inventar um seria fazer o bot
        falar com um fantasma."""
        message = Message.from_payload({"id": "1", "channel_id": "2"})
        assert message.author is None

    def test_author_name_com_fallback(self) -> None:
        """Não levanta `AttributeError` no meio de um log."""
        message = Message.from_payload({"id": "1", "channel_id": "2"})
        assert message.author_name == "?"

    def test_mentions_guardam_ids(self) -> None:
        """Uma mensagem que menciona mil pessoas não deve custar mil
        objetos `User` carregados."""
        message = Message.from_payload(
            {
                "id": "1",
                "channel_id": "2",
                "mentions": [{"id": "11", "username": "a"}, {"id": "22", "username": "b"}],
            }
        )
        assert message.mentions == (11, 22)

    def test_mention_roles_vem_como_string_e_vira_int(self) -> None:
        message = Message.from_payload({"id": "1", "channel_id": "2", "mention_roles": ["5", "6"]})
        assert message.mention_roles == (5, 6)

    def test_attachments_viram_modelos(self) -> None:
        message = Message.from_payload(
            {
                "id": "1",
                "channel_id": "2",
                "attachments": [{"id": "9", "filename": "a.png", "url": "u", "proxy_url": "p"}],
            }
        )
        assert len(message.attachments) == 1
        assert message.attachments[0].filename == "a.png"

    def test_referenced_message_recursivo(self) -> None:
        """Uma resposta carrega a mensagem citada inteira, e ela pode
        ter outra resposta dentro."""
        message = Message.from_payload(
            {
                "id": "1",
                "channel_id": "2",
                "content": "resposta",
                "referenced_message": {
                    "id": "99",
                    "channel_id": "2",
                    "content": "original",
                    "referenced_message": {"id": "98", "channel_id": "2", "content": "mais antiga"},
                },
            }
        )
        assert message.referenced_message is not None
        assert message.referenced_message.content == "original"
        assert message.referenced_message.referenced_message is not None
        assert message.referenced_message.referenced_message.content == "mais antiga"

    def test_is_default_para_mensagem_comum(self) -> None:
        message = Message.from_payload({"id": "1", "channel_id": "2", "type": 0})
        assert message.is_default is True
        assert message.is_system is False

    def test_is_system_para_mensagem_de_sistema(self) -> None:
        message = Message.from_payload({"id": "1", "channel_id": "2", "type": 6})
        assert message.is_system is True

    def test_interaction_extraida_do_objeto_aninhado(self) -> None:
        message = Message.from_payload(
            {"id": "1", "channel_id": "2", "interaction": {"id": "77", "name": "ping"}}
        )
        assert message.interaction_id == 77
        assert message.interaction_name == "ping"

    def test_clean_content_nao_existe_ainda(self) -> None:
        """Trocar ``<@123>`` por ``@123`` não ajuda, e trocar por nome
        exige resolver o ID — trabalho do cache, ainda não existente.

        O teste registra a decisão: propriedade que parece ajudar e não
        ajuda é pior que propriedade ausente. Se um dia aparecer, tem
        que vir com cache e resolver nome de verdade.
        """
        message = Message.from_payload({"id": "1", "channel_id": "2", "content": "oi <@11>"})
        assert not hasattr(message, "clean_content")

    def test_payload_update_parcial_nao_inventa_conteudo(self) -> None:
        """O `MESSAGE_UPDATE` manda só o que mudou. Um modelo que
        preenche o resto com default faz o handler achar que o texto
        foi apagado."""
        message = Message.from_payload({"id": "1", "channel_id": "2", "pinned": True})
        assert message.content is None
        assert message.pinned is True


# ==========================================================================
# Channel
# ==========================================================================


class TestChannel:
    def test_payload_completo(self) -> None:
        channel = Channel.from_payload(
            {
                "id": "1",
                "type": 0,
                "guild_id": "2",
                "name": "geral",
                "position": 3,
                "topic": "conversa",
                "nsfw": False,
            }
        )
        assert channel.name == "geral"
        assert channel.is_text is True
        assert channel.is_sendable is True

    def test_classifica_texto_e_anuncio(self) -> None:
        assert Channel.from_payload({"id": "1", "type": 0}).is_text is True
        assert Channel.from_payload({"id": "1", "type": 5}).is_text is True

    def test_classifica_dm(self) -> None:
        assert Channel.from_payload({"id": "1", "type": 1}).is_dm is True
        assert Channel.from_payload({"id": "1", "type": 3}).is_dm is True

    def test_classifica_thread(self) -> None:
        for channel_type in (10, 11, 12):
            assert Channel.from_payload({"id": "1", "type": channel_type}).is_thread is True

    def test_classifica_categoria(self) -> None:
        assert Channel.from_payload({"id": "1", "type": 4}).is_category is True

    def test_categoria_nao_recebe_mensagem(self) -> None:
        """Categoria agrupa, não conversa. Tratar como texto é como se
        ganha 403 no primeiro `send`."""
        assert Channel.from_payload({"id": "1", "type": 4}).is_sendable is False

    def test_voz_nao_recebe_texto(self) -> None:
        assert Channel.from_payload({"id": "1", "type": 2}).is_sendable is False

    def test_recipients_guardam_ids(self) -> None:
        channel = Channel.from_payload(
            {"id": "1", "type": 1, "recipients": [{"id": "10"}, {"id": "20"}]}
        )
        assert channel.recipient_ids == (10, 20)

    def test_thread_metadata_lida(self) -> None:
        channel = Channel.from_payload(
            {"id": "1", "type": 11, "thread_metadata": {"archived": True, "locked": True}}
        )
        assert channel.archived is True
        assert channel.locked is True

    def test_mention(self) -> None:
        assert Channel.from_payload({"id": "55", "type": 0}).mention == "<#55>"


# ==========================================================================
# Guild
# ==========================================================================


class TestGuild:
    def test_payload_completo(self) -> None:
        guild = Guild.from_payload(
            {
                "id": "1",
                "name": "Kryn",
                "icon": "hash",
                "owner_id": "2",
                "member_count": 10,
                "features": ["VANITY_URL"],
            }
        )
        assert guild.name == "Kryn"
        assert guild.features == ("VANITY_URL",)

    def test_roles_guardam_ids_nao_objetos(self) -> None:
        """Uma guild com vinte roles de vinte campos cada seria um
        objeto pesado que ninguém pediu."""
        guild = Guild.from_payload({"id": "1", "roles": [{"id": "11"}, {"id": "22"}]})
        assert guild.roles == (11, 22)

    def test_emojis_guardam_ids(self) -> None:
        guild = Guild.from_payload({"id": "1", "emojis": [{"id": "33"}]})
        assert guild.emojis == (33,)

    def test_payload_do_ready_so_tem_id(self) -> None:
        """O `READY` manda só `id` e `unavailable`. O mesmo modelo
        representa os dois, e nada além do `id` é obrigatório."""
        guild = Guild.from_payload({"id": "1", "unavailable": True})
        assert guild.id == 1
        assert guild.name is None
        assert guild.unavailable is True

    def test_icon_url_none_sem_icone(self) -> None:
        assert Guild.from_payload({"id": "1"}).icon_url is None

    def test_icon_url_monta_o_caminho(self) -> None:
        guild = Guild.from_payload({"id": "1", "icon": "h"})
        assert guild.icon_url == "https://cdn.discordapp.com/icons/1/h.png"


# ==========================================================================
# Partial — o ponto inteiro é o que NÃO existe
# ==========================================================================


class TestPartialMessage:
    def test_so_tem_os_campos_que_veio(self) -> None:
        """`MESSAGE_DELETE` manda id, channel_id e mais nada.

        Um `Message` com `content=None` faria o handler achar que a
        mensagem não tinha texto. `PartialMessage` não tem o campo, e o
        `AttributeError` é a resposta honesta.
        """
        partial = PartialMessage.from_payload({"id": "1", "channel_id": "2", "guild_id": "3"})
        assert partial.id == 1
        assert partial.channel_id == 2
        assert partial.guild_id == 3

    def test_nao_tem_content(self) -> None:
        """O teste que protege o propósito do módulo. Se um dia alguém
        adicionar `content` com default, isto tem que quebrar."""
        partial = PartialMessage.from_payload({"id": "1", "channel_id": "2"})
        assert not hasattr(partial, "content")
        assert not hasattr(partial, "author")

    def test_guild_id_ausente_e_none(self) -> None:
        """DM não tem guild — `None` é a resposta certa, não erro."""
        partial = PartialMessage.from_payload({"id": "1", "channel_id": "2"})
        assert partial.guild_id is None


class TestPartialGuild:
    def test_do_ready(self) -> None:
        guild = PartialGuild.from_payload({"id": "1", "unavailable": True})
        assert guild.id == 1
        assert guild.unavailable is True

    def test_unavailable_default_false(self) -> None:
        assert PartialGuild.from_payload({"id": "1"}).unavailable is False


class TestPartialChannel:
    def test_so_o_basico(self) -> None:
        channel = PartialChannel.from_payload({"id": "1", "type": 0, "guild_id": "2"})
        assert channel.id == 1
        assert channel.type == 0
        assert channel.guild_id == 2


# ==========================================================================
# Ready
# ==========================================================================


class TestReady:
    def test_payload_completo(self) -> None:
        ready = Ready.from_payload(
            {
                "user": {"id": "1", "username": "bot"},
                "session_id": "abc",
                "resume_gateway_url": "wss://x",
                "guilds": [{"id": "10", "unavailable": True}, {"id": "20"}],
                "shard": [0, 1],
            }
        )
        assert ready.user is not None
        assert ready.user.username == "bot"
        assert ready.session_id == "abc"
        assert ready.guild_ids == (10, 20)
        assert ready.shard_id == 0
        assert ready.shard_count == 1

    def test_guilds_sao_referencias_nao_carregadas(self) -> None:
        """A guild completa chega no `GUILD_CREATE`. Aqui só o ID."""
        ready = Ready.from_payload({"guilds": [{"id": "10"}]})
        assert ready.guilds[0].id == 10

    def test_shard_none_quando_nao_e_shardado(self) -> None:
        ready = Ready.from_payload({})
        assert ready.shard is None
        assert ready.shard_id is None

    def test_payload_sem_nada_nao_levanta(self) -> None:
        """O Gateway já validou o `session_id` antes de entregar. Este
        modelo é para o código da aplicação, não para a máquina de
        estados."""
        ready = Ready.from_payload({})
        assert ready.user is None
        assert ready.guilds == ()

    @pytest.mark.parametrize("shard", [["a", "b"], [1], "x"])
    def test_shard_malformado_vira_none(self, shard: object) -> None:
        ready = Ready.from_payload({"shard": shard})
        assert ready.shard is None


# ==========================================================================
# Tolerância — o contrato de que payload errado não derruba o bot
# ==========================================================================


class TestTolerancia:
    @pytest.mark.parametrize(
        "payload",
        [
            {"id": "1", "author": "não é objeto"},
            {"id": "1", "attachments": "não é lista"},
            {"id": "1", "content": 42},
            {"id": "1", "timestamp": "inválido"},
            {"id": "1", "mentions": [1, 2, "xyz"]},
        ],
        ids=[
            "author-string",
            "attachments-string",
            "content-int",
            "timestamp-ruim",
            "mentions-sujas",
        ],
    )
    def test_message_nunca_levanta(self, payload: dict[str, object]) -> None:
        """Nenhum payload malformado pode derrubar o dispatch.

        Tipo errado vira ausência, não exceção. O único caso que
        devolve `None` é o de faltar o ``id`` — coberto abaixo.
        """
        message = Message.from_payload(payload)  # type: ignore[arg-type]
        assert isinstance(message, Message)

    @pytest.mark.parametrize(
        "modelo",
        [Message, Channel, Guild, PartialMessage, PartialChannel, PartialGuild, User, Attachment],
        ids=lambda m: m.__name__,
    )
    def test_sem_id_devolve_none(self, modelo: type[object]) -> None:
        """O contrato: objeto sem ID não significa nada, e `None` é o
        sinal disso — o dispatcher entrega o payload cru em vez de um
        objeto que faria o handler perseguir um ID que não existe."""
        from_payload = modelo.from_payload
        assert from_payload({"channel_id": "2", "content": "oi"}) is None

    def test_id_bool_nao_conta_como_id(self) -> None:
        """`bool` é subclasse de `int` em Python. Sem essa checagem,
        ``{"id": true}`` viraria ``id == 1`` e o bot perseguiria um
        usuário que não existe."""
        assert Message.from_payload({"id": True, "channel_id": "2"}) is None

    def test_guild_como_lista_nao_levanta(self) -> None:
        guild = Guild.from_payload({"id": "1", "roles": "não é lista"})
        assert guild is not None
        assert guild.roles == ()

    def test_lista_com_entrada_ruim_preserva_as_boas(self) -> None:
        """O Discord manda listas com entradas ruins junto das boas.
        Derrubar a mensagem inteira por uma entrada seria perder um
        evento válido para punir um payload que o bot não pediu."""
        message = Message.from_payload(
            {
                "id": "1",
                "channel_id": "2",
                "attachments": [
                    {"id": "9", "filename": "boa.png", "url": "u", "proxy_url": "p"},
                    {"filename": "sem-id.png"},
                    "não é objeto",
                ],
            }
        )
        assert message is not None
        assert len(message.attachments) == 1
        assert message.attachments[0].filename == "boa.png"


# ==========================================================================
# Role
# ==========================================================================


class TestRole:
    def test_sem_id_ou_nome_nao_e_cargo(self) -> None:
        """Sem ID não se edita, sem nome não se invoca — `None` nos dois."""
        assert Role.from_payload({"name": "mod"}) is None
        assert Role.from_payload({"id": "1"}) is None
        assert Role.from_payload({}) is None

    def test_permissoes_continuam_string(self) -> None:
        """O Discord manda bits de 64 como string porque JavaScript perde
        precisão acima de ``2**53``. Guardar `int` daria comparação
        direta; guardar `str` seria o tipo honesto."""
        role = Role.from_payload({"id": "1", "name": "admin", "permissions": "8"})
        assert role is not None
        assert role.permissions == "8"
        assert isinstance(role.permissions, str)

    def test_color_rgb_decompoe_os_24_bits(self) -> None:
        role = Role.from_payload({"id": "1", "name": "c", "color": 0xFF8000})
        assert role is not None
        assert role.color_rgb == (255, 128, 0)

    def test_color_rgb_zerado_e_preto(self) -> None:
        """`color` ausente vira 0, e 0 é preto — não é o mesmo que
        "sem cor", que o Discord representa por nenhuma cor aplicada."""
        role = Role.from_payload({"id": "1", "name": "c"})
        assert role is not None
        assert role.color_rgb == (0, 0, 0)

    def test_mention_no_formato_do_chat(self) -> None:
        role = Role.from_payload({"id": "123456789012345678", "name": "mod"})
        assert role is not None
        assert role.mention == "<@&123456789012345678>"

    def test_icon_url_sem_icone_e_none(self) -> None:
        """Cargo sem ícone usa emoji unicode — `None` aqui é o correto,
        não uma URL apontando para nada."""
        role = Role.from_payload({"id": "1", "name": "c", "unicode_emoji": "🔥"})
        assert role is not None
        assert role.icon_url is None

    def test_icon_url_com_icone(self) -> None:
        role = Role.from_payload({"id": "1", "name": "c", "icon": "abc"})
        assert role is not None
        assert role.icon_url is not None
        assert "/role-icons/1/abc.png" in role.icon_url

    def test_tipo_errado_vira_ausencia(self) -> None:
        """O contrato de tolerância vale para todo modelo novo."""
        role = Role.from_payload({"id": "1", "name": "c", "position": "não é int"})
        assert role is not None
        assert role.position == 0


# ==========================================================================
# Ban
# ==========================================================================


class TestBan:
    def test_sem_usuario_nao_e_ban(self) -> None:
        assert Ban.from_payload({"reason": "spam"}) is None
        assert Ban.from_payload({}) is None

    def test_usuario_sem_id_tambem_nao_e_ban(self) -> None:
        """`User.from_payload` devolve `None`, e o `Ban` não sobrevive
        a isso — um ban sem usuário não identifica ninguém."""
        assert Ban.from_payload({"user": {"username": "x"}, "reason": "r"}) is None

    def test_motivo_ausente_e_none_nao_vazio(self) -> None:
        """ "Sem motivo declarado" e "motivo vazio" não são a mesma
        coisa — ``""`` afirmaria que alguém escreveu nada."""
        ban = Ban.from_payload({"user": {"id": "1", "username": "x"}})
        assert ban is not None
        assert ban.reason is None

    def test_motivo_presente(self) -> None:
        ban = Ban.from_payload({"user": {"id": "1", "username": "x"}, "reason": "spam"})
        assert ban is not None
        assert ban.reason == "spam"
        assert ban.user.id == 1


# ==========================================================================
# Webhook
# ==========================================================================


class TestWebhook:
    def test_sem_id_nao_e_webhook(self) -> None:
        assert Webhook.from_payload({"name": "log", "type": 1}) is None

    def test_token_ausente_e_none_nao_vazio(self) -> None:
        """`GET /webhooks/:id` não entrega token. Um ``""`` afirmaria
        que existe um token que não serve para nada."""
        webhook = Webhook.from_payload({"id": "1", "type": 0})
        assert webhook is not None
        assert webhook.token is None
        assert webhook.execute_url is None

    def test_execute_url_com_token(self) -> None:
        webhook = Webhook.from_payload({"id": "5", "type": 0, "token": "abc"})
        assert webhook is not None
        assert webhook.execute_url == "https://discord.com/api/webhooks/5/abc"

    def test_execute_url_nunca_com_token_ausente(self) -> None:
        """É a propriedade que alguém vai colocar num log por engano —
        devolver URL vazia seria pior que `None`."""
        webhook = Webhook.from_payload({"id": "1", "type": 0})
        assert webhook is not None
        assert webhook.execute_url is None

    def test_type_1_e_o_do_slack(self) -> None:
        slack = Webhook.from_payload({"id": "1", "type": 1})
        proprio = Webhook.from_payload({"id": "2", "type": 0})
        assert slack is not None and slack.is_slack_compatible
        assert proprio is not None and not proprio.is_slack_compatible

    def test_token_numerico_nao_vira_int(self) -> None:
        """Um token como número perderia zeros à esquerda na URL."""
        webhook = Webhook.from_payload({"id": "1", "type": 0, "token": 123})
        assert webhook is not None
        assert webhook.token is None

    def test_source_guild_e_channel_objetos_aninhados(self) -> None:
        webhook = Webhook.from_payload(
            {
                "id": "1",
                "type": 1,
                "source_guild": {"id": "9", "name": "Kryn"},
                "source_channel": {"id": "8", "name": "geral"},
            }
        )
        assert webhook is not None
        assert webhook.source_guild_id == 9
        assert webhook.source_channel_id == 8


# ==========================================================================
# ApplicationCommand
# ==========================================================================


class TestApplicationCommand:
    def test_sem_id_ou_nome_nao_e_comando(self) -> None:
        assert ApplicationCommand.from_payload({"name": "/ping", "description": "x"}) is None
        assert ApplicationCommand.from_payload({"id": "1"}) is None

    def test_descricao_vazia_e_legal_para_contexto(self) -> None:
        """Comando de contexto (tipo 2/3) o Discord exige **sem**
        descrição — ``""`` é o valor legal, não uma ausência."""
        cmd = ApplicationCommand.from_payload({"id": "1", "name": "Ver", "type": 2})
        assert cmd is not None
        assert cmd.description == ""
        assert cmd.is_context_menu
        assert not cmd.is_chat_input

    def test_opcoes_ruimas_sao_descartadas(self) -> None:
        """Só `Mapping` chega. Opção de comando tem sete tipos com
        campos mutuamente exclusivos — manter o que é objeto é o que
        interessa, o resto nem era payload."""
        cmd = ApplicationCommand.from_payload(
            {"id": "1", "name": "p", "description": "d", "options": [{"type": 1}, "junk", 42]}
        )
        assert cmd is not None
        assert len(cmd.options) == 1
        assert isinstance(cmd.options[0], dict)

    def test_mention_com_id(self) -> None:
        cmd = ApplicationCommand.from_payload({"id": "123456789012345678", "name": "ping"})
        assert cmd is not None
        assert cmd.mention == "</ping:123456789012345678>"

    def test_dm_permission_none_quando_ausente(self) -> None:
        """`False` e ausente são coisas diferentes: `False` é o Discord
        dizendo "só em guild", ausente é ele não dizendo nada."""
        cmd = ApplicationCommand.from_payload({"id": "1", "name": "p"})
        assert cmd is not None
        assert cmd.dm_permission is None

    def test_localizations_somente_strings(self) -> None:
        cmd = ApplicationCommand.from_payload(
            {"id": "1", "name": "p", "name_localizations": {"pt-BR": "pingar", "ru": None}}
        )
        assert cmd is not None
        assert cmd.name_localizations == {"pt-BR": "pingar"}

    def test_localizations_ausentes_e_none_nao_vazio(self) -> None:
        cmd = ApplicationCommand.from_payload({"id": "1", "name": "p"})
        assert cmd is not None
        assert cmd.name_localizations is None


# ==========================================================================
# Interaction
# ==========================================================================


class TestInteraction:
    def payload(self, **extra: object) -> dict[str, object]:
        base: dict[str, object] = {
            "id": "1",
            "application_id": "2",
            "type": 2,
            "token": "tok",
        }
        base.update(extra)
        return base

    @pytest.mark.parametrize("faltando", ["id", "type", "token"])
    def test_falta_de_resposta_devolve_none(self, faltando: str) -> None:
        """Os três são o mínimo: sem `token` não há URL de callback,
        sem `type` não se sabe qual endpoint, sem `id` a resposta aponta
        para nada. Um objeto meio montado mandaria `POST` para URL
        incompleta e daria um 404 que não explica o problema."""
        dados = self.payload()
        del dados[faltando]
        assert Interaction.from_payload(dados) is None

    def test_autor_vem_do_member_em_guild(self) -> None:
        """Em guild o Discord manda só ``member``; em DM, só ``user``.
        São dois caminhos para a mesma informação."""
        inter = Interaction.from_payload(
            self.payload(member={"user": {"id": "7", "username": "ana"}})
        )
        assert inter is not None
        assert inter.author is not None
        assert inter.author.username == "ana"

    def test_autor_vem_do_user_em_dm(self) -> None:
        inter = Interaction.from_payload(self.payload(user={"id": "7", "username": "ana"}))
        assert inter is not None
        assert inter.author is not None
        assert inter.author.username == "ana"

    def test_command_name_e_custom_id_do_data(self) -> None:
        comando = Interaction.from_payload(self.payload(data={"name": "ping"}))
        botao = Interaction.from_payload(self.payload(type=3, data={"custom_id": "sim"}))
        assert comando is not None
        assert comando.command_name == "ping"
        assert comando.custom_id is None
        assert botao is not None
        assert botao.custom_id == "sim"
        assert botao.command_name is None

    def test_classificacao_por_tipo(self) -> None:
        comando = Interaction.from_payload(self.payload(type=2))
        botao = Interaction.from_payload(self.payload(type=3))
        modal = Interaction.from_payload(self.payload(type=5))
        assert comando is not None and comando.is_command()
        assert botao is not None and botao.is_message_component()
        assert modal is not None and modal.is_modal_submit()

    def test_sem_data_comandos_sao_none_nao_erro(self) -> None:
        """PING (tipo 1) vem sem `data` — esperar dict seria AttributeError
        no meio de uma verificação de URL."""
        inter = Interaction.from_payload(self.payload(type=1))
        assert inter is not None
        assert inter.command_name is None
        assert inter.custom_id is None
        assert inter.data is None

    def test_raw_preserva_o_que_nao_modelamos(self) -> None:
        """`data` tem três formatos (comando, componente, modal) — o
        payload inteiro fica guardado para quem precisar do campo que
        deixamos de fora."""
        inter = Interaction.from_payload(self.payload(app_id_extra="valor"))
        assert inter is not None
        assert inter.raw is not None
        assert inter.raw["app_id_extra"] == "valor"
