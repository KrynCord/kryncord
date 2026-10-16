"""Testes dos recursos novos do `kryncord.api`.

Cobre o que a ampliação acrescentou: `roles`, `members`, `webhooks`,
`applications`, `interactions`, e o que entrou em `channels` e
`messages`.

O que se verifica aqui não é o payload feliz — é **a rota, o método e o
corpo**. Um API layer errado não falha barulhento: manda `PATCH` onde o
Discord espera `PUT`, ou esquece o `auth=False` do webhook, e o
usuário vê um 404 ou um 401 que não aponta o problema real.

Os helpers de resposta vêm de `test_api.py` — mesmo contrato (sequência
de factories, última repete), para não manter duas cópias que divergem.
Os payloads são novos, porque os recursos são novos.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from kryncord.errors import ComponentError, HTTPError
from kryncord.models import (
    ApplicationCommand,
    Ban,
    Interaction,
    Member,
    Message,
    Role,
    User,
    Webhook,
)
from tests.unit.test_api import make_api, no_content

GUILD = 300
CANAL = 200
MENSAGEM = 100
CARGO = 400
USUARIO = 500
APP = 600
WEBHOOK = 700


# --------------------------------------------------------------------------
# Payloads — cada recurso tem o seu
# --------------------------------------------------------------------------


def payload_de_cargo(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(CARGO),
        "name": "mod",
        "color": 0xFF8000,
        "position": 3,
        "permissions": "8",
        "hoist": True,
        "mentionable": True,
    }
    base.update(extra)
    return base


def payload_de_membro(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user": {"id": str(USUARIO), "username": "ana", "global_name": "Ana"},
        "nick": "Ana.",
        "roles": [str(CARGO)],
        "joined_at": "2024-01-01T00:00:00Z",
    }
    base.update(extra)
    return base


def payload_de_webhook(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": str(WEBHOOK), "type": 0, "channel_id": str(CANAL)}
    base.update(extra)
    return base


def payload_de_comando(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "123456789012345678",
        "application_id": str(APP),
        "name": "ping",
        "description": "responde pong",
        "type": 1,
        "version": "1",
    }
    base.update(extra)
    return base


def payload_de_interacao(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "111",
        "application_id": str(APP),
        "type": 2,
        "token": "token-de-resposta",
        "version": 1,
        "data": {"name": "ping", "type": 1},
    }
    base.update(extra)
    return base


def payload_de_mensagem(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(MENSAGEM),
        "channel_id": str(CANAL),
        "author": {"id": "1", "username": "x"},
        "content": "oi",
        "timestamp": "2024-01-01T00:00:00Z",
        "type": 0,
    }
    base.update(extra)
    return base


def interacao(**extra: Any) -> Interaction:
    parsed = Interaction.from_payload(payload_de_interacao(**extra))
    assert parsed is not None
    return parsed


def corpo_de(request: httpx.Request) -> dict[str, Any]:
    import json

    return json.loads(request.content.decode())


def sem_token(request: httpx.Request) -> bool:
    """Se a requisição foi **sem** o `Authorization: Bot`.

    O caminho do webhook faz autenticação com o próprio token na URL;
    mandar o header do bot junto seria dupla autenticação que o Discord
    aceita mas que mascara qual credencial falhou quando dá erro.
    """
    return "Authorization" not in request.headers


# ==========================================================================
# RolesAPI
# ==========================================================================


class TestRoles:
    async def test_list_devolve_a_lista_inteira(self) -> None:
        """É a única listagem de guild sem paginação — o Discord devolve
        tudo de uma vez, e paginar seria chamada extra sem necessidade."""
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_cargo()]))

        roles = await api.roles.list(GUILD)

        assert all(isinstance(r, Role) for r in roles)
        assert roles[0].name == "mod"
        assert roles[0].color_rgb == (255, 128, 0)
        assert captured[0].method == "GET"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/roles"

    async def test_create_manda_nome_no_corpo(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_cargo()))

        role = await api.roles.create(GUILD, "novo", color=255, hoist=True)

        assert role.name == "mod"
        assert corpo_de(captured[0]) == {"name": "novo", "color": 255, "hoist": True}
        assert captured[0].method == "POST"

    async def test_edit_so_manda_o_que_veio(self) -> None:
        """O Discord faz merge, não substituição — mandar só `name` não
        zera a cor. Confirmar que não injetamos campos vazios."""
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_cargo()))

        await api.roles.edit(GUILD, CARGO, name="outro")

        assert corpo_de(captured[0]) == {"name": "outro"}

    async def test_delete_e_delete_simples(self) -> None:
        """Apagar cargo remove de todo mundo, sem confirmação. O método
        existe sem atalho justamente por isso."""
        api, captured = make_api(no_content())

        await api.roles.delete(GUILD, CARGO)

        assert captured[0].method == "DELETE"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/roles/{CARGO}"

    async def test_add_to_member_e_put_sem_corpo(self) -> None:
        api, captured = make_api(no_content())

        await api.roles.add_to_member(GUILD, USUARIO, CARGO)

        assert captured[0].method == "PUT"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/members/{USUARIO}/roles/{CARGO}"
        assert captured[0].content in (b"", None)

    async def test_remove_from_member(self) -> None:
        api, captured = make_api(no_content())

        await api.roles.remove_from_member(GUILD, USUARIO, CARGO)

        assert captured[0].method == "DELETE"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/members/{USUARIO}/roles/{CARGO}"


# ==========================================================================
# MembersAPI
# ==========================================================================


class TestMembers:
    async def test_list_sem_cursor_e_primeira_pagina(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_membro()]))

        members = await api.members.list(GUILD)

        assert all(isinstance(m, Member) for m in members)
        assert members[0].display_name == "Ana."
        assert members[0].roles == (CARGO,)
        assert captured[0].url.params["limit"] == "1000"
        assert "after" not in captured[0].url.params

    async def test_list_com_cursor_manda_after(self) -> None:
        """Sem `after`, servidor com 50 mil membros devolve sempre os
        mesmos 1000 — é o erro silencioso de paginação."""
        api, captured = make_api(lambda: httpx.Response(200, json=[]))

        await api.members.list(GUILD, limit=50, after=USUARIO)

        assert captured[0].url.params["limit"] == "50"
        assert captured[0].url.params["after"] == str(USUARIO)

    async def test_fetch_404_quando_nao_esta_na_guild(self) -> None:
        """404 é a resposta certa para "está na guild?". `users.fetch`
        é o caminho para ver quem não está."""
        api, _ = make_api(lambda: httpx.Response(404, json={"message": "Unknown Member"}))

        with pytest.raises(HTTPError):
            await api.members.fetch(GUILD, USUARIO)

    async def test_add_e_put_com_access_token(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_membro()))

        await api.members.add(GUILD, USUARIO, access_token="oa", nick="novo")

        assert captured[0].method == "PUT"
        assert corpo_de(captured[0]) == {"access_token": "oa", "nick": "novo"}

    async def test_edit_e_patch(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_membro()))

        await api.members.edit(GUILD, USUARIO, nick="Ana", roles=[str(CARGO)])

        assert captured[0].method == "PATCH"
        assert corpo_de(captured[0]) == {"nick": "Ana", "roles": [str(CARGO)]}

    async def test_kick_devolve_o_usuario_que_saiu(self) -> None:
        """Diferente da maioria, kick devolve objeto — jogar isso fora
        seria perder a prova de quem saiu."""
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        user = await api.members.remove(GUILD, USUARIO, reason="spam")

        assert isinstance(user, User)
        assert user.id == USUARIO
        assert captured[0].method == "DELETE"

    async def test_reason_vai_url_encoded_no_header(self) -> None:
        """A razão de auditoria tem URL-encoding — um motivo com acento
        feito à mão daria 400, e o erro apontaria o header, não o texto.
        Aqui a camada `rest/` é quem cuida disso."""
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        await api.members.remove(GUILD, USUARIO, reason="quebrou o r")

        # O espaço vira `%20` — header não aceita espaço cru.
        assert captured[0].headers["X-Audit-Log-Reason"] == "quebrou%20o%20r"

    async def test_reason_com_acento_vai_encoded(self) -> None:
        """É o caso que o encoding existe para: um motivo em português
        cheio de acento mandado cru daria 400, e o erro apontaria o
        header — não o texto, que é o que alguém teria que corrigir."""
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        await api.members.remove(GUILD, USUARIO, reason="quebrou ação")

        header = captured[0].headers["X-Audit-Log-Reason"]
        assert "ç" not in header and "ã" not in header
        assert header.startswith("quebrou%20a%C3%A7")
        # Sem encoding, o `ç` não-ASCII quebraria a requisição.
        assert all(ord(c) < 128 for c in header)

    async def test_reason_sem_texto_nao_manda_header(self) -> None:
        """``X-Audit-Log-Reason: `` vazio registraria entrada de auditoria
        sem texto — pior que não registrar, alguém leria "por quê?"."""
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        await api.members.remove(GUILD, USUARIO, reason="   ")

        assert "X-Audit-Log-Reason" not in captured[0].headers

    async def test_ban_com_delete_message_seconds(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        await api.members.ban(GUILD, USUARIO, delete_message_seconds=86400, reason="x")

        assert captured[0].method == "PUT"
        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/bans/{USUARIO}"
        assert corpo_de(captured[0]) == {"delete_message_seconds": 86400}

    async def test_ban_sem_delete_manda_corpo_vazio(self) -> None:
        """Não injetar ``delete_message_seconds: null`` — campo ausente
        e campo nulo não são a mesma coisa para o Discord."""
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        await api.members.ban(GUILD, USUARIO)

        assert corpo_de(captured[0]) == {}

    async def test_unban_devolve_o_usuario(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(200, json={"id": str(USUARIO), "username": "ana"})
        )

        user = await api.members.unban(GUILD, USUARIO)

        assert user.id == USUARIO
        assert captured[0].method == "DELETE"

    async def test_bans_pagina_com_after(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(
                200,
                json=[{"user": {"id": str(USUARIO), "username": "ana"}, "reason": "spam"}],
            )
        )

        bans = await api.members.bans(GUILD, after=USUARIO)

        assert all(isinstance(b, Ban) for b in bans)
        assert bans[0].reason == "spam"
        assert captured[0].url.params["after"] == str(USUARIO)

    async def test_fetch_ban_com_motivo(self) -> None:
        api, _ = make_api(
            lambda: httpx.Response(200, json={"user": {"id": str(USUARIO), "username": "ana"}})
        )

        ban = await api.members.fetch_ban(GUILD, USUARIO)

        assert isinstance(ban, Ban)
        assert ban.reason is None


# ==========================================================================
# WebhooksAPI
# ==========================================================================


class TestWebhooks:
    async def test_list_sem_token(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_webhook()]))

        hooks = await api.webhooks.list(CANAL)

        assert all(isinstance(h, Webhook) for h in hooks)
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/webhooks"

    async def test_fetch_sem_token_e_autenticado(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_webhook()))

        hook = await api.webhooks.fetch(WEBHOOK)

        assert hook.token is None
        assert captured[0].url.path == f"/api/v10/webhooks/{WEBHOOK}"
        assert not sem_token(captured[0])

    async def test_fetch_com_token_e_o_outro_caminho(self) -> None:
        """O token faz autenticação — mandar `Authorization: Bot` junto
        seria dupla credencial, e mascararia qual falhou num 403."""
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_webhook(token="abc")))

        hook = await api.webhooks.fetch(WEBHOOK, token="abc")

        assert hook.token == "abc"
        assert captured[0].url.path == f"/api/v10/webhooks/{WEBHOOK}/abc"
        assert sem_token(captured[0])

    async def test_create_devolve_com_token(self) -> None:
        """Único caminho em que o token aparece — `POST` autenticado
        entrega uma vez. Se perder, o webhook novo é o caminho."""
        api, captured = make_api(
            lambda: httpx.Response(200, json=payload_de_webhook(token="secreto", name="log"))
        )

        hook = await api.webhooks.create(CANAL, "log", reason="criação")

        assert hook.token == "secreto"
        assert hook.execute_url is not None
        assert captured[0].method == "POST"

    async def test_edit_com_e_sem_token(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_webhook()))

        await api.webhooks.edit(WEBHOOK, name="a")
        await api.webhooks.edit(WEBHOOK, token="tk", name="b")

        assert captured[0].url.path == f"/api/v10/webhooks/{WEBHOOK}"
        assert not sem_token(captured[0])
        assert captured[1].url.path == f"/api/v10/webhooks/{WEBHOOK}/tk"
        assert sem_token(captured[1])

    async def test_execute_sem_wait_devolve_none(self) -> None:
        """204 não tem mensagem — devolver um objeto inventado seria
        pior que `None`, que é o contrato honesto do Discord."""
        api, captured = make_api(no_content())

        result = await api.webhooks.execute(WEBHOOK, "tk", content="oi")

        assert result is None
        assert captured[0].url.path == f"/api/v10/webhooks/{WEBHOOK}/tk"
        assert sem_token(captured[0])
        assert "wait" not in captured[0].url.params

    async def test_execute_com_wait_devolve_a_mensagem(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        result = await api.webhooks.execute(WEBHOOK, "tk", content="oi", wait=True)

        assert isinstance(result, Message)
        assert captured[0].url.params["wait"] == "true"

    async def test_execute_nunca_autenticado_com_bot(self) -> None:
        """Este é o teste que protege contra a regressão silenciosa:
        alguém "padronizando" o auth quebraria toda execução de webhook
        sem erro visível nenhum."""
        api, captured = make_api(no_content())

        await api.webhooks.execute(WEBHOOK, "tk", content="oi")

        assert sem_token(captured[0])

    async def test_execute_slack(self) -> None:
        api, captured = make_api(no_content())

        await api.webhooks.execute_slack(WEBHOOK, "tk", {"text": "oi"})

        assert captured[0].url.path == f"/api/v10/webhooks/{WEBHOOK}/tk/slack"
        assert corpo_de(captured[0]) == {"text": "oi"}


# ==========================================================================
# ApplicationsAPI
# ==========================================================================


class TestApplications:
    async def test_global_e_guild_sao_o_mesmo_endpoint(self) -> None:
        """`guild_id=None` é o global. Duas listas de métodos quase
        idênticos seria uma segunda fonte de verdade — a URL real só
        tem um segmento a menos."""
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_comando()]))

        await api.applications.list_commands(APP)
        await api.applications.list_commands(APP, guild_id=GUILD)

        assert captured[0].url.path == f"/api/v10/applications/{APP}/commands"
        assert captured[1].url.path == f"/api/v10/applications/{APP}/guilds/{GUILD}/commands"

    async def test_list_devolve_modelo(self) -> None:
        api, _ = make_api(lambda: httpx.Response(200, json=[payload_de_comando()]))

        commands = await api.applications.list_commands(APP)

        assert all(isinstance(c, ApplicationCommand) for c in commands)
        assert commands[0].mention == "</ping:123456789012345678>"
        assert commands[0].is_chat_input

    async def test_create_manda_o_payload_direto(self) -> None:
        """Sem intermediário que renomeie: o payload é o do Discord,
        porque quem escreve a definição lê o docs dele."""
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_comando()))

        await api.applications.create_command(APP, {"name": "ping", "description": "responde pong"})

        assert corpo_de(captured[0]) == {
            "name": "ping",
            "description": "responde pong",
        }

    async def test_bulk_overwrite_e_put(self) -> None:
        """O método de sincronização. `PUT` apaga o que não está na
        lista — criar um a um deixa comando órfão, que aparece pro
        usuário como comando que não faz nada."""
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_comando()]))

        await api.applications.bulk_overwrite_commands(
            APP, [{"name": "ping", "description": "pong"}]
        )

        assert captured[0].method == "PUT"
        assert corpo_de(captured[0]) == [{"name": "ping", "description": "pong"}]

    async def test_bulk_overwrite_da_guild_usa_o_mesmo_metodo(self) -> None:
        """O `sync()` faz um `PUT` por escopo — global, e um por
        guild. Este é o caminho do guild: mesmo método, mesmo corpo,
        só o segmento do meio muda. Sem ele o sync de guild não teria
        como ser escrito."""
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_comando()]))

        await api.applications.bulk_overwrite_commands(
            APP, [{"name": "ping", "description": "pong"}], guild_id=GUILD
        )

        assert captured[0].method == "PUT"
        assert captured[0].url.path == f"/api/v10/applications/{APP}/guilds/{GUILD}/commands"
        assert corpo_de(captured[0]) == [{"name": "ping", "description": "pong"}]

    async def test_delete(self) -> None:
        api, captured = make_api(no_content())

        await api.applications.delete_command(APP, "123456789012345678")

        assert captured[0].method == "DELETE"
        assert captured[0].url.path.endswith("/commands/123456789012345678")

    async def test_edit_e_patch(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_comando()))

        await api.applications.edit_command(APP, "1", name="novo")

        assert captured[0].method == "PATCH"
        assert corpo_de(captured[0]) == {"name": "novo"}

    async def test_me_devolve_dict_nao_modelo(self) -> None:
        """Este payload muda com escopo OAuth2 — modelar uma árvore que
        só existe em app de usuário seria fingir cobrir o que não
        cobrimos. `application_id` é o que se busca, e está sempre lá."""
        api, captured = make_api(lambda: httpx.Response(200, json={"id": str(APP), "name": "Kryn"}))

        app = await api.applications.me()

        assert app["id"] == str(APP)
        assert captured[0].url.path == "/api/v10/applications/@me"


# ==========================================================================
# InteractionsAPI
# ==========================================================================


class TestInteractions:
    async def test_callback_no_caminho_certo(self) -> None:
        """O token vai na URL — é ele a autenticação do callback."""
        api, captured = make_api(no_content())

        await api.interactions.callback(interacao(), 4)

        assert captured[0].method == "POST"
        assert captured[0].url.path == "/api/v10/interactions/111/token-de-resposta/callback"
        assert corpo_de(captured[0]) == {"type": 4}

    async def test_respond_e_tipo_4(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.respond(interacao(), "pong")

        corpo = corpo_de(captured[0])
        assert corpo["type"] == 4
        assert corpo["data"]["content"] == "pong"

    async def test_respond_vazio_falta_antes_de_mandar(self) -> None:
        """Um `data: {}` o Discord recusa com 400 apontando `data`, que
        é o campo errado para o problema. Falhar aqui custa a janela de
        3 segundos — melhor falhar sem gastar requisição nenhuma."""
        api, captured = make_api(no_content())

        with pytest.raises(ValueError, match="defer"):
            await api.interactions.respond(interacao())

        assert captured == []

    async def test_respond_com_só_embed_nao_e_vazio(self) -> None:
        """`content=None` com embed é resposta legítima — só `content`
        vazio é que não é."""
        api, captured = make_api(no_content())

        await api.interactions.respond(interacao(), embeds=[{"title": "oi"}])

        corpo = corpo_de(captured[0])
        assert "content" not in corpo["data"]
        assert corpo["data"]["embeds"] == [{"title": "oi"}]

    async def test_respond_serializa_componente_e_ephemeral(self) -> None:
        """0024 C3: o componente chega ao HTTP como payload, não como
        dataclass — e `ephemeral=True` vira `flags: 64`, porque
        `{"ephemeral": true}` no corpo é **ignorado** pelo Discord em
        silêncio. Era o bug: a mensagem aparecia para todo mundo."""
        from kryncord.components import Button, create_row

        api, captured = make_api(no_content())

        await api.interactions.respond(
            interacao(),
            "escolha",
            components=[create_row(Button(custom_id="/ok", label="Ok"))],
            ephemeral=True,
        )

        corpo = corpo_de(captured[0])
        assert corpo["data"]["components"] == [
            {
                "type": 1,
                "components": [{"type": 2, "style": 1, "custom_id": "/ok", "label": "Ok"}],
            }
        ]
        assert corpo["data"]["flags"] == 64
        assert "ephemeral" not in corpo["data"]

    async def test_respond_v2_true_vira_flag(self) -> None:
        """O atalho `v2=True` é da camada de resposta (0015) — e é aqui,
        no `_message_data`, que todos os métodos de resposta convergem."""
        from kryncord.components import Container, TextDisplay

        api, captured = make_api(no_content())

        await api.interactions.respond(
            interacao(),
            components=[Container("Blurple", TextDisplay("# Título"))],
            v2=True,
        )

        corpo = corpo_de(captured[0])
        assert corpo["data"]["flags"] == 1 << 15
        assert "v2" not in corpo["data"]

    async def test_respond_mistura_v2_com_content_falta_antes_do_http(self) -> None:
        """A tabela da ideia 18 §4 na camada de API: o Discord ignoraria
        o `content` em silêncio — o erro é nosso, e antes da requisição."""
        from kryncord.components import Container, TextDisplay

        api, captured = make_api(no_content())

        with pytest.raises(ComponentError, match="ignora em silêncio"):
            await api.interactions.respond(
                interacao(),
                "oi",
                components=[Container("Blurple", TextDisplay("x"))],
                v2=True,
            )

        assert captured == []

    async def test_defer_de_comando_e_tipo_5(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.defer(interacao())

        assert corpo_de(captured[0]) == {"type": 5}

    async def test_defer_de_componente_e_tipo_6(self) -> None:
        """Componente já mostra carregamento no botão — mandar
        "pensando…" de novo duplicaria."""
        api, captured = make_api(no_content())

        await api.interactions.defer(interacao(type=3, data={"custom_id": "ok"}))

        assert corpo_de(captured[0]) == {"type": 6}

    async def test_defer_ephemeral_marca_a_flag_64(self) -> None:
        """A flag é o canal que existe para "só quem chamou vê" — não há
        campo `ephemeral` no payload, há uma flag de mensagem."""
        api, captured = make_api(no_content())

        await api.interactions.defer(interacao(), ephemeral=True)

        corpo = corpo_de(captured[0])
        assert corpo["type"] == 5
        assert corpo["data"]["flags"] == 64

    async def test_defer_ephemeral_em_componente_nao_manda_flags(self) -> None:
        """Em componente o tipo 6 não aceita data — mandar `flags` seria
        400. `ephemeral` é ignorado ali porque não tem onde entrar."""
        api, captured = make_api(no_content())

        await api.interactions.defer(interacao(type=3, data={"custom_id": "x"}), ephemeral=True)

        assert corpo_de(captured[0]) == {"type": 6}

    async def test_pong_e_tipo_1(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.pong(interacao(type=1))

        assert corpo_de(captured[0]) == {"type": 1}

    async def test_update_message_e_tipo_7(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.update_message(interacao(), "novo")

        corpo = corpo_de(captured[0])
        assert corpo["type"] == 7
        assert corpo["data"]["content"] == "novo"

    async def test_show_modal_e_tipo_9(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.show_modal(
            interacao(), {"custom_id": "f", "title": "T", "components": []}
        )

        corpo = corpo_de(captured[0])
        assert corpo["type"] == 9
        assert corpo["data"]["custom_id"] == "f"

    async def test_autocomplete_devolve_escolhas(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.autocomplete(interacao(type=4), [{"name": "a", "value": "1"}])

        corpo = corpo_de(captured[0])
        assert corpo["type"] == 8
        assert corpo["data"]["choices"] == [{"name": "a", "value": "1"}]

    async def test_fetch_message_404_vira_none(self) -> None:
        """404 aqui é "ainda não existe" — um defer seguido de followup
        sem editar a original deixa ela intocada. Não é erro de rede."""
        api, _ = make_api(lambda: httpx.Response(404, json={"message": "Unknown"}))

        assert await api.interactions.fetch_message(APP, "tk") is None

    async def test_fetch_message_devolve_modelo(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        message = await api.interactions.fetch_message(APP, "tk")

        assert isinstance(message, Message)
        assert captured[0].url.path == (f"/api/v10/webhooks/{APP}/tk/messages/@original")
        assert sem_token(captured[0])

    async def test_fetch_message_alcancando_followup(self) -> None:
        """`message_id` busca um follow-up, não só a original. Sem ele,
        o `fetch_reply()` não fecharia o par com o `follow_up()`."""
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        await api.interactions.fetch_message(APP, "tk", 777)

        assert captured[0].url.path == f"/api/v10/webhooks/{APP}/tk/messages/777"

    async def test_edit_message(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        await api.interactions.edit_message(APP, "tk", "@original", "pronto")

        assert captured[0].method == "PATCH"
        assert captured[0].url.path.endswith("/messages/@original")
        assert corpo_de(captured[0])["content"] == "pronto"

    async def test_edit_message_alcancando_followup(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        await api.interactions.edit_message(APP, "tk", 777, "pronto")

        assert captured[0].url.path.endswith("/messages/777")

    async def test_delete_message(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.delete_message(APP, "tk")

        assert captured[0].method == "DELETE"
        assert captured[0].url.path.endswith("/messages/@original")

    async def test_delete_message_alcancando_followup(self) -> None:
        api, captured = make_api(no_content())

        await api.interactions.delete_message(APP, "tk", 777)

        assert captured[0].url.path.endswith("/messages/777")

    async def test_launch_activity_manda_tipo_12(self) -> None:
        """O `type` enviado é a parte testável sem ponta a ponta — o
        efeito exigiria atividade no bot de teste (0023)."""
        api, captured = make_api(no_content())

        await api.interactions.launch_activity(interacao())

        assert corpo_de(captured[0])["type"] == 12

    async def test_followup_por_padrao_espera_a_mensagem(self) -> None:
        """Diferente do `webhooks.execute`, `wait=True` aqui é default:
        seguir a interação é quase sempre para editar depois, e isso
        precisa do ID."""
        api, captured = make_api(lambda: httpx.Response(200, json=payload_de_mensagem()))

        message = await api.interactions.followup(APP, "tk", "extra")

        assert isinstance(message, Message)
        assert "wait" not in captured[0].url.params
        assert sem_token(captured[0])

    async def test_followup_sem_wait_devolve_none(self) -> None:
        api, captured = make_api(no_content())

        result = await api.interactions.followup(APP, "tk", "x", wait=False)

        assert result is None
        assert captured[0].url.params["wait"] == "false"


# ==========================================================================
# ChannelsAPI — o que a ampliação acrescentou
# ==========================================================================


class TestChannelsExpandidos:
    async def test_list_messages_quebra_o_buraco_principal(self) -> None:
        """Antes não dava nem para listar as últimas mensagens de um
        canal — uma das três primeiras coisas que qualquer bot quer."""
        api, captured = make_api(lambda: httpx.Response(200, json=[payload_de_mensagem()]))

        messages = await api.channels.list_messages(CANAL)

        assert all(isinstance(m, Message) for m in messages)
        assert captured[0].method == "GET"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages"
        assert captured[0].url.params["limit"] == "50"

    async def test_list_messages_com_cursor(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=[]))

        await api.channels.list_messages(CANAL, before=MENSAGEM, limit=100)

        assert captured[0].url.params["before"] == str(MENSAGEM)
        assert captured[0].url.params["limit"] == "100"

    async def test_list_messages_limit_acima_do_maximo_e_cortado(self) -> None:
        """O Discord não reclama de `limit` alto, ele corta. Cortar aqui
        também — mandar 500 e receber 100 sem avisar seria mentir sobre
        o que foi pedido."""
        api, captured = make_api(lambda: httpx.Response(200, json=[]))

        await api.channels.list_messages(CANAL, limit=500)

        assert captured[0].url.params["limit"] == "100"

    async def test_list_messages_around_para_contexto(self) -> None:
        api, captured = make_api(lambda: httpx.Response(200, json=[]))

        await api.channels.list_messages(CANAL, around=MENSAGEM)

        assert captured[0].url.params["around"] == str(MENSAGEM)

    async def test_delete_messages_ate_cem(self) -> None:
        api, captured = make_api(no_content())

        await api.channels.delete_messages(CANAL, [MENSAGEM, MENSAGEM + 1])

        assert captured[0].method == "POST"
        assert captured[0].url.path == f"/api/v10/channels/{CANAL}/messages/delete"
        assert corpo_de(captured[0]) == {"messages": [str(MENSAGEM), str(MENSAGEM + 1)]}

    async def test_delete_messages_acima_de_cem_fala_alto(self) -> None:
        """Partir em silêncio esconderia que foram cinco requisições e
        cinco rate limits. A intenção de "apagar 500" e a de "apagar 3"
        são diferentes — quem decide é quem chama."""
        api, captured = make_api(no_content())

        with pytest.raises(ValueError, match="100"):
            await api.channels.delete_messages(CANAL, range(101))

        assert captured == []

    async def test_delete_messages_vazio_nao_manda_nada(self) -> None:
        """Um `POST` com lista vazia o Discord recusa com 400 apontando
        `messages` — a mensagem errada para "não tem nada para apagar"."""
        api, captured = make_api(no_content())

        await api.channels.delete_messages(CANAL, [])

        assert captured == []

    async def test_create_thread_de_mensagem(self) -> None:
        """`message_id` transforma em thread da mensagem — é o caminho
        das respostas em tópico."""
        api, captured = make_api(lambda: httpx.Response(200, json={"id": "9", "type": 11}))

        thread = await api.channels.create_thread(CANAL, "tópico", message=MENSAGEM)

        assert thread.is_thread
        assert corpo_de(captured[0])["message_id"] == str(MENSAGEM)

    async def test_create_thread_sem_mensagem(self) -> None:
        """Não injetar `message_id: null` — campo ausente e nulo não são
        a mesma coisa, e o Discord recusaria o nulo."""
        api, captured = make_api(lambda: httpx.Response(200, json={"id": "9", "type": 11}))

        await api.channels.create_thread(CANAL, "tópico")

        assert "message_id" not in corpo_de(captured[0])

    async def test_join_e_leave_thread(self) -> None:
        api, captured = make_api(no_content())

        await api.channels.join_thread(CANAL)
        await api.channels.leave_thread(CANAL)

        assert captured[0].method == "PUT"
        assert captured[0].url.path.endswith("/thread-members/@me")
        assert captured[1].method == "DELETE"
        assert captured[1].url.path.endswith("/thread-members/@me")

    async def test_list_archived_threads_preserva_has_more(self) -> None:
        """`has_more` não é decoração: sem ele, o fim da paginação seria
        "recebi menos que `limit`", que é suposição — o Discord pode
        devolver página cheia e ainda ter mais."""
        api, _ = make_api(
            lambda: httpx.Response(
                200,
                json={
                    "threads": [
                        {"id": "900", "type": 11, "name": "a"},
                        {"id": "800", "type": 11, "name": "b"},
                    ],
                    "has_more": True,
                },
            )
        )

        batch = await api.channels.list_archived_threads(CANAL)

        assert batch.has_more is True
        assert len(batch.threads) == 2
        # O mais antigo é o cursor da próxima chamada.
        assert batch.oldest_id == 800

    async def test_list_archived_threads_sem_mais_paginas(self) -> None:
        api, _ = make_api(lambda: httpx.Response(200, json={"threads": [], "has_more": False}))

        batch = await api.channels.list_archived_threads(CANAL)

        assert batch.has_more is False
        assert batch.oldest_id is None

    async def test_list_archived_threads_com_cursor(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(200, json={"threads": [], "has_more": False})
        )

        await api.channels.list_archived_threads(CANAL, before=800, limit=10)

        assert captured[0].url.params["before"] == "800"
        assert captured[0].url.params["limit"] == "10"
        assert captured[0].url.path.endswith("/threads/archived/public")

    async def test_list_archived_threads_privadas(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(200, json={"threads": [], "has_more": False})
        )

        await api.channels.list_archived_threads(CANAL, public=False)

        assert captured[0].url.path.endswith("/threads/archived/private")

    async def test_list_active_threads_do_guild(self) -> None:
        api, captured = make_api(
            lambda: httpx.Response(200, json={"threads": [], "has_more": False})
        )

        await api.channels.list_active_threads(GUILD)

        assert captured[0].url.path == f"/api/v10/guilds/{GUILD}/threads/active"

    async def test_list_active_threads_com_corpo_ruim(self) -> None:
        """`has_more` ausente vira `False` (único default honesto: um
        `True` mandaria buscar página que não existe), mas corpo que não
        é objeto nenhum é erro — não há o que paginar."""
        api, _ = make_api(lambda: httpx.Response(200, json=["não é objeto"]))

        with pytest.raises(HTTPError, match="esperava objeto"):
            await api.channels.list_active_threads(GUILD)

    async def test_list_thread_members_fica_cru(self) -> None:
        """O payload traz campos que não existem no `Member` normal
        (``join_timestamp``, ``flags``). Um `Member` com metade faltando
        seria pior que o dict cru."""
        api, _ = make_api(
            lambda: httpx.Response(
                200,
                json=[
                    {
                        "id": str(USUARIO),
                        "join_timestamp": "2024-01-01T00:00:00Z",
                        "flags": 1,
                    },
                    "lixo",
                ],
            )
        )

        members = await api.channels.list_thread_members(CANAL)

        assert members == [
            {"id": str(USUARIO), "join_timestamp": "2024-01-01T00:00:00Z", "flags": 1}
        ]


# ==========================================================================
# MessagesAPI — reações
# ==========================================================================


class TestReacoes:
    async def test_unicode_vai_percent_encoded(self) -> None:
        """A rota vira nome de bucket e entra em log — emoji cru no
        Windows sai mojibake, e o `#` de alguns emoji cortaria a URL."""
        api, captured = make_api(no_content())

        await api.messages.add_reaction(MENSAGEM, "👍", channel=CANAL)

        # `url.path` decodifica o percent-encoding; `str(url)` é o que
        # vai na rede, e é o que interessa verificar aqui.
        enviada = str(captured[0].url)
        assert "%F0%9F%91%8D" in enviada
        assert enviada.endswith(
            f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}/reactions/%F0%9F%91%8D/@me"
        )

    async def test_custom_desmontado_para_name_id(self) -> None:
        """``<:name:123>`` — depois de tirar os ``<>`` sobra
        ``:name:123``, com dois-pontos na frente, porque o formatador é
        ``<`` + ``:name:123`` + ``>``. Tirar só os ``<>`` mandaria o
        caminho com o dois-pontos sobrando, e daria 404."""
        api, captured = make_api(no_content())

        await api.messages.add_reaction(MENSAGEM, "<:fire:123456789012345678>", channel=CANAL)

        assert captured[0].url.path.endswith("/reactions/fire:123456789012345678/@me")

    async def test_custom_animado_perde_o_prefixo(self) -> None:
        """``a:`` é animação, e o separador é **dois-pontos**, não
        sublinhado — no caminho o Discord não distingue, e manter daria
        404."""
        api, captured = make_api(no_content())

        await api.messages.add_reaction(MENSAGEM, "<a:fire:123456789012345678>", channel=CANAL)

        assert captured[0].url.path.endswith("/reactions/fire:123456789012345678/@me")
        # E nada de "a:" sobrando no caminho.
        assert "a:fire" not in captured[0].url.path

    async def test_custom_ja_desmontado_passa_direto(self) -> None:
        api, captured = make_api(no_content())

        await api.messages.add_reaction(MENSAGEM, "fire:123456789012345678", channel=CANAL)

        assert captured[0].url.path.endswith("/reactions/fire:123456789012345678/@me")

    async def test_remove_reaction_de_outra_pessoa(self) -> None:
        """Outro `user_id` exige `MANAGE_MESSAGES`; o default `@me` não.
        Dois públicos diferentes para o mesmo endpoint."""
        api, captured = make_api(no_content())

        await api.messages.remove_reaction(MENSAGEM, "👍", user_id=USUARIO, channel=CANAL)

        assert captured[0].method == "DELETE"
        assert str(captured[0].url).endswith(f"/reactions/%F0%9F%91%8D/{USUARIO}")

    async def test_remove_all_reactions_e_de_todo_mundo(self) -> None:
        api, captured = make_api(no_content())

        await api.messages.remove_all_reactions(MENSAGEM, channel=CANAL)

        assert captured[0].url.path == (f"/api/v10/channels/{CANAL}/messages/{MENSAGEM}/reactions")

    async def test_remove_all_reactions_for_e_de_um_emoji(self) -> None:
        """O meio-termo: limpar o 👍 de todos sem apagar o resto."""
        api, captured = make_api(no_content())

        await api.messages.remove_all_reactions_for(MENSAGEM, "👍", channel=CANAL)

        assert str(captured[0].url).endswith(f"/messages/{MENSAGEM}/reactions/%F0%9F%91%8D")

    async def test_canal_descoberto_da_propria_mensagem(self) -> None:
        """O caminho que o handler usa de verdade: passa a mensagem e
        não pensa no canal."""
        api, captured = make_api(no_content())
        message = Message.from_payload(payload_de_mensagem())
        assert message is not None

        await api.messages.add_reaction(message, "👍")

        assert f"/channels/{CANAL}/messages/{MENSAGEM}/reactions" in captured[0].url.path
