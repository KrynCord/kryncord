"""Testes de `kryncord.state.event_updates` — o que cada evento significa.

A dificuldade não é guardar, é **atualizar sem apagar o que não veio**.
`GUILD_UPDATE` manda um guild sem os arrays de organização,
`MESSAGE_UPDATE` de edição em embed vem sem `content`, e
`GUILD_MEMBER_UPDATE` traz `deaf?` como opcional. Os testes que mais
importam aqui são os que mandam um payload pela metade e conferem que o
resto continua de pé.

O segundo eixo é o contrário: payload que traz um valor **falso de
verdade** tem que sobrescrever. `from_payload` não distingue ausente
de `False`, então quem decide é o JSON — e um teste só com payloads
completos não pegaria o bug de um merge que nunca descarta nada.

Nada aqui abre rede: são dicts e modelos.
"""

from __future__ import annotations

from kryncord.cache import CacheKind, CachePolicy
from kryncord.state import ConnectionState, EventUpdater


def fluxo(**kwargs: object) -> tuple[ConnectionState, EventUpdater]:
    """Estado + atualizador, com a política que o teste pedir.

    `members` e `messages` vêm desligados no default, e quase todo
    teste destes arquivos quer os dois ligados — sem isso, o `set` é
    ignorado em silêncio e a asserção falha num lugar que não tem nada
    a ver com o que se queria verificar.

    Os kwargs **substituem** os ligados em vez de acompanhar: passar
    `messages=0` para testar o tipo desligado tem que vencer o default,
    não chocar com ele.
    """
    base: dict[str, object] = {"members": True, "messages": 10}
    base.update(kwargs)
    estado = ConnectionState(policy=CachePolicy(**base))  # type: ignore[arg-type]
    return estado, EventUpdater(estado)


READY = {
    "v": 10,
    "user": {"id": "99", "username": "bot", "bot": True},
    "guilds": [{"id": "10", "unavailable": True}, {"id": "11", "unavailable": True}],
    "session_id": "sessao-1",
    "resume_gateway_url": "wss://bogus.discord.gg",
}

GUILD_CREATE = {
    "id": "10",
    "name": "Servidor",
    "roles": [{"id": "30", "name": "Mod", "hoist": True}],
    # `channels` e `threads` de propósito **sem** `guild_id`: é o que o
    # Discord real manda — confirmado ao vivo, `24/24` canais vieram
    # sem o campo. O contexto é a resposta, e sem completar, a guild
    # não veria os canais que ela mesma mandou.
    "channels": [{"id": "20", "name": "geral", "type": 0}],
    "threads": [{"id": "21", "name": "conversa", "type": 11, "parent_id": "20"}],
    "members": [{"user": {"id": "1", "username": "ana"}, "nick": "Ana"}],
    "member_count": 1,
}

MEMBER_ADD = {
    "guild_id": "10",
    "user": {"id": "1", "username": "ana"},
    "nick": "Ana",
    "joined_at": "2020-01-01T00:00:00.000+00:00",
    "deaf": True,
}

MESSAGE_CREATE = {
    "id": "40",
    "channel_id": "20",
    "guild_id": "10",
    "content": "oi tudo bem",
    "author": {"id": "1", "username": "ana"},
    "member": {"user": {"id": "1", "username": "ana"}, "nick": "Ana"},
    "embeds": [],
}


# --------------------------------------------------------------------------
# Conexão
# --------------------------------------------------------------------------


def test_ready_grava_me_e_os_stubs_das_guilds() -> None:
    """O `READY` manda `guilds` como `{id, unavailable}` — é o Discord
    dizendo "você está nestes servidores, ainda não vou te contar nada".
    Guardar o stub é o que faz `get_guild(id)` achar antes dos
    `GUILD_CREATE` chegarem."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)

    assert estado.me is not None
    assert estado.me.id == 99
    assert estado.me.bot is True

    stub = estado.get_guild(10)
    assert stub is not None
    assert stub.name is None  # nem nome tinha ainda
    assert stub.unavailable is True
    assert estado.get_guild(11) is not None


def test_ready_sem_usuario_nao_levanta() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("READY", {"guilds": []})

    assert estado.me is None
    assert estado.guilds == ()


def test_user_update_troca_me() -> None:
    """`USER_UPDATE` só vem para o próprio bot — trocou avatar ou nome.
    É por isso que `users` precisa de LRU: nenhum evento remove conta de
    terceiro."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("USER_UPDATE", {"id": "99", "username": "nome-novo"})

    assert estado.me is not None
    assert estado.me.username == "nome-novo"


# --------------------------------------------------------------------------
# Guild
# --------------------------------------------------------------------------


def test_guild_create_guarda_tudo_o_que_vem_junto() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    guild = estado.get_guild(10)
    assert guild is not None
    assert guild.name == "Servidor"

    visao = estado.guild(10)
    assert visao is not None
    assert [r.id for r in visao.roles] == [30]
    assert [c.id for c in visao.channels] == [20, 21]  # canal + thread
    assert [m.user.id for m in visao.members] == [1]

    # A conta veio dentro do membro e é a mesma em toda guild.
    assert estado.get_user(1) is not None


def test_canais_do_guild_create_ganham_a_guild_pelo_contexto() -> None:
    """Sem `guild_id` no payload, o agrupamento sairia `None` e a guild
    não enxergaria os canais que ela mesma mandou — que parece (e é
    tratado como) política desligada."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    canal = estado.get_channel(20)
    assert canal is not None
    assert canal.guild_id == 10  # completado pelo contexto


def test_guild_create_sem_guild_id_no_canal_e_preservado_o_que_veio() -> None:
    """O contrário também: se o Discord mandou `guild_id`, ele é a
    verdade — completar seria decidir contra o payload."""
    estado, atualiza = fluxo()
    atualiza.apply(
        "GUILD_CREATE",
        {
            "id": "10",
            "name": "S",
            "channels": [{"id": "20", "name": "g", "type": 0, "guild_id": "55"}],
        },
    )

    canal = estado.get_channel(20)
    assert canal is not None
    assert canal.guild_id == 55  # veio no payload, ficou


def test_guild_create_com_membros_desligados_nao_levanta() -> None:
    """A política desligada não é erro — é o `set` sendo ignorado. O
    guild e os canais entram mesmo assim."""
    estado, atualiza = fluxo(members=False)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    visao = estado.guild(10)
    assert visao is not None
    assert visao.members == ()
    assert visao.channels != ()  # canal não é membro
    assert estado.get_user(1) is not None  # conta entra de qualquer jeito


def test_guild_create_de_stub_nao_tem_nada_para_separar() -> None:
    """Cenário 1 dos docs: `GUILD_CREATE` pode vir como unavailable
    durante um outage, e aí não há array nenhum — nem erro, nem
    resto de dado antigo perdido."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("GUILD_CREATE", {"id": "10", "unavailable": True})

    guild = estado.get_guild(10)
    assert guild is not None
    assert guild.unavailable is True
    assert estado.get_guild(11) is not None  # a outra ficou


def test_guild_update_nao_apaga_o_que_nao_veio() -> None:
    """É o motivo do merge existir. `GUILD_UPDATE` é um objeto de guild
    comum, e os arrays de organização não vêm nele — mas até `roles` e
    `emojis`, que são IDs, não vêm sempre. Apagar tudo que faltou
    deixaria um guild renomeado sem nenhum cargo."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_UPDATE", {"id": "10", "name": "Renomeado"})

    guild = estado.get_guild(10)
    assert guild is not None
    assert guild.name == "Renomeado"
    assert guild.roles == (30,)  # não veio no update, ficou

    visao = estado.guild(10)
    assert visao is not None
    assert visao.members != ()  # os filhos não foram tocados


def test_guild_delete_indisponivel_mantem_tudo() -> None:
    """Indisponibilidade é outage, não saída: o Discord te tira por
    causa de um problema e manda `GUILD_CREATE` de volta. Apagar membros
    aqui jogaria fora dados que ninguém vai reenviar antes de precisar."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_DELETE", {"id": "10", "unavailable": True})

    guild = estado.get_guild(10)
    assert guild is not None
    assert guild.unavailable is True
    assert guild.name == "Servidor"  # merge preservou

    visao = estado.guild(10)
    assert visao is not None
    assert visao.members != ()
    assert visao.channels != ()


def test_guild_delete_sem_unavailable_tira_a_guild_e_os_filhos() -> None:
    """Saiu de vez. Os filhos vão junto — não há `CHANNEL_DELETE` para
    canais de um servidor que deixou de existir para nós, e deixar
    `members` órfãos seria memória de um lugar onde o bot não está."""
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_DELETE", {"id": "10"})

    assert estado.get_guild(10) is None
    assert estado.get_member(10, 1) is None
    assert estado.get_role(10, 30) is None
    assert estado.get_channel(20) is None
    # A guild vizinha do READY não foi pega no fogo cruzado.
    assert estado.get_guild(11) is not None


def test_guild_delete_com_id_invalido_e_no_op() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("READY", READY)

    atualiza.apply("GUILD_DELETE", {"unavailable": True})

    assert estado.get_guild(10) is not None


# --------------------------------------------------------------------------
# Membros
# --------------------------------------------------------------------------


def test_member_add_pega_a_guild_do_envelope() -> None:
    """`Member` não tem `guild_id` porque dentro do `GUILD_CREATE` a
    lista vem dentro do objeto da guild e não diz de qual é. Nos eventos
    soltos o Discord completa — e sem ele não há para onde gravar."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_MEMBER_ADD", MEMBER_ADD)

    membro = estado.get_member(10, 1)
    assert membro is not None
    assert membro.nick == "Ana"
    assert estado.get_user(1) is not None


def test_member_add_em_outra_guild_nao_se_mistura() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_MEMBER_ADD", {**MEMBER_ADD, "guild_id": "11"})

    assert estado.get_member(11, 1) is not None
    assert estado.get_member(10, 1) is None


def test_member_update_preserva_o_que_nao_veio() -> None:
    """`deaf?` e `mute?` vêm marcados como opcionais: um payload sem
    eles não significa "não está surdo", significa "não mudou"."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_MEMBER_ADD", MEMBER_ADD)

    atualiza.apply(
        "GUILD_MEMBER_UPDATE",
        {
            "guild_id": "10",
            "user": {"id": "1", "username": "ana"},
            "roles": ["30"],
            "nick": "Apelido novo",
        },
    )

    membro = estado.get_member(10, 1)
    assert membro is not None
    assert membro.nick == "Apelido novo"
    assert membro.deaf is True  # não veio no update, ficou
    assert membro.joined_at is not None  # idem


def test_member_update_com_false_explícito_sobrescreve() -> None:
    """O outro lado da regra: ausente fica, presente muda — mesmo que
    o presente seja `False`. Um merge que nunca descarta passaria este
    teste errado, e é o bug que só aparece quando alguém é dessafado."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_MEMBER_ADD", MEMBER_ADD)
    assert estado.get_member(10, 1).deaf is True  # type: ignore[union-attr]

    atualiza.apply(
        "GUILD_MEMBER_UPDATE",
        {
            "guild_id": "10",
            "user": {"id": "1", "username": "ana"},
            "deaf": False,
        },
    )

    assert estado.get_member(10, 1).deaf is False  # type: ignore[union-attr]


def test_member_remove_tira_o_membro_e_deixa_a_conta() -> None:
    """Saiu do servidor — a **conta** continua existindo em outras
    guilds. Achar que este é um `USER_DELETE` seria apagar alguém que
    está em outro lugar."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_MEMBER_ADD", MEMBER_ADD)

    atualiza.apply("GUILD_MEMBER_REMOVE", {"guild_id": "10", "user": {"id": "1"}})

    assert estado.get_member(10, 1) is None
    assert estado.get_user(1) is not None


def test_member_add_sem_guild_ou_sem_usuario_e_no_op() -> None:
    estado, atualiza = fluxo()

    atualiza.apply("GUILD_MEMBER_ADD", {"user": {"id": "1"}})  # sem guild
    atualiza.apply("GUILD_MEMBER_ADD", {"guild_id": "10"})  # sem user
    atualiza.apply("GUILD_MEMBER_ADD", {"guild_id": "10", "user": {}})  # sem id

    assert estado.get_member(10, 1) is None


# --------------------------------------------------------------------------
# Cargos
# --------------------------------------------------------------------------


def test_role_create_guarda_na_guild_certa() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_ROLE_CREATE", {"guild_id": "10", "role": {"id": "31", "name": "Novo"}})

    assert estado.get_role(10, 31) is not None
    assert estado.get_role(10, 30) is not None  # o antigo ficou


def test_role_update_faz_merge_com_o_objeto_do_cargo() -> None:
    """O merge é com `role`, não com o envelope `{guild_id, role}`: os
    nomes de campo vivem dentro de `role`, e comparar com o envelope
    não encontraria nenhum e manteria tudo velho."""
    estado, atualiza = fluxo()
    atualiza.apply(
        "GUILD_ROLE_CREATE", {"guild_id": "10", "role": {"id": "30", "name": "Mod", "hoist": True}}
    )

    atualiza.apply("GUILD_ROLE_UPDATE", {"guild_id": "10", "role": {"id": "30", "name": "Admin"}})

    role = estado.get_role(10, 30)
    assert role is not None
    assert role.name == "Admin"  # veio no update
    assert role.hoist is True  # não veio, ficou


def test_role_delete_usa_o_role_id() -> None:
    """O Discord manda só o ID, não o objeto."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("GUILD_ROLE_DELETE", {"guild_id": "10", "role_id": "30"})

    assert estado.get_role(10, 30) is None


def test_role_delete_sem_role_id_e_no_op() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_ROLE_DELETE", {"guild_id": "10"})
    assert estado.get_role(10, 30) is None


# --------------------------------------------------------------------------
# Canais e threads
# --------------------------------------------------------------------------


def test_channel_create_e_delete() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("CHANNEL_CREATE", {"id": "20", "guild_id": "10", "name": "geral", "type": 0})
    assert estado.get_channel(20) is not None

    atualiza.apply("CHANNEL_DELETE", {"id": "20", "guild_id": "10", "type": 0})
    assert estado.get_channel(20) is None


def test_channel_update_preserva_a_guild_e_o_que_nao_veio() -> None:
    """O agrupamento é calculado do `guild_id`, então um payload sem
    ele tem que manter o antigo — senão o canal continua existindo e
    some da visão da guild, que é o bug mais confuso desta camada."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("CHANNEL_UPDATE", {"id": "20", "name": "renomeado"})

    canal = estado.get_channel(20)
    assert canal is not None
    assert canal.name == "renomeado"
    assert canal.guild_id == 10  # não veio no update, ficou

    visao = estado.guild(10)
    assert visao is not None
    assert [c.id for c in visao.channels] == [20, 21]  # ainda agrupados


def test_thread_create_e_delete_sao_canais() -> None:
    """`THREAD_DELETE` manda só `{id, guild_id, parent_id, type}` — um
    recorte. Ainda assim o ID está lá, que é tudo que remover precisa.

    Não existe `Thread` em `models/`: thread **é** `Channel` (tipos
    10/11/12), e tratar os dois igual é o que faz `get_channel()` achar
    thread nenhuma hora.
    """
    estado, atualiza = fluxo()
    atualiza.apply(
        "THREAD_CREATE", {"id": "21", "guild_id": "10", "parent_id": "20", "type": 11, "name": "t"}
    )
    thread = estado.get_channel(21)
    assert thread is not None
    assert thread.guild_id == 10

    atualiza.apply("THREAD_UPDATE", {"id": "21", "name": "t2"})
    assert estado.get_channel(21).name == "t2"  # type: ignore[union-attr]

    atualiza.apply("THREAD_DELETE", {"id": "21", "guild_id": "10", "parent_id": "20", "type": 11})
    assert estado.get_channel(21) is None


def test_channel_de_dm_nao_entra_na_visao_da_guild() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)
    atualiza.apply("CHANNEL_CREATE", {"id": "500", "name": "dm", "type": 1})

    assert estado.get_channel(500) is not None
    visao = estado.guild(10)
    assert visao is not None
    assert [c.id for c in visao.channels] == [20, 21]


# --------------------------------------------------------------------------
# Mensagens
# --------------------------------------------------------------------------


def test_message_create_guarda_mensagem_autor_e_membro() -> None:
    """O `member` dentro da mensagem é a face do autor **naquela**
    guild, e é a via mais comum de membro chegar para quem não ligou o
    intent `GUILD_MEMBERS` — não é dado inventado, veio no payload."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    atualiza.apply("MESSAGE_CREATE", MESSAGE_CREATE)

    mensagem = estado.get_message(40)
    assert mensagem is not None
    assert mensagem.content == "oi tudo bem"
    assert estado.get_user(1) is not None
    assert estado.get_member(10, 1) is not None


def test_message_create_com_mensagens_desligadas_e_no_op() -> None:
    estado, atualiza = fluxo(messages=0)
    atualiza.apply("MESSAGE_CREATE", MESSAGE_CREATE)

    assert estado.get_message(40) is None
    # A conta e o membro continuam entrando: a política de `messages`
    # não governa os outros tipos.
    assert estado.get_user(1) is not None


def test_message_update_preserva_o_content_que_nao_veio() -> None:
    """Editar só o embed numa mensagem com conteúdo manda o payload
    **sem** `content`. Gravar por cima apagaria a mensagem inteira e
    deixaria o texto vazio — numa edição que nem mexeu nele."""
    estado, atualiza = fluxo()
    atualiza.apply("MESSAGE_CREATE", MESSAGE_CREATE)

    atualiza.apply(
        "MESSAGE_UPDATE",
        {
            "id": "40",
            "channel_id": "20",
            "guild_id": "10",
            "edited_timestamp": "2024-05-05T12:00:00.000+00:00",
            "embeds": [{"title": "novo embed"}],
        },
    )

    mensagem = estado.get_message(40)
    assert mensagem is not None
    assert mensagem.content == "oi tudo bem"  # não veio, ficou
    assert mensagem.edited_at is not None  # veio, entrou


def test_message_update_vazio_nao_zera_a_mensagem() -> None:
    """O caso mais seco do mesmo erro: payload sem `content` nenhum,
    nem embed — só o ID. Guardar o parse direto deixaria o texto `None`."""
    estado, atualiza = fluxo()
    atualiza.apply("MESSAGE_CREATE", MESSAGE_CREATE)

    atualiza.apply("MESSAGE_UPDATE", {"id": "40", "channel_id": "20"})

    mensagem = estado.get_message(40)
    assert mensagem is not None
    assert mensagem.content == "oi tudo bem"


def test_message_update_que_nunca_vimos_guarda_o_que_chegou() -> None:
    """Sem antigo não há o que juntar, e guardar só o que se sabe é
    honesto — é o que se sabe."""
    estado, atualiza = fluxo()
    atualiza.apply("MESSAGE_UPDATE", {"id": "99", "channel_id": "20", "content": "só isto"})

    mensagem = estado.get_message(99)
    assert mensagem is not None
    assert mensagem.content == "só isto"


def test_message_delete() -> None:
    estado, atualiza = fluxo()
    atualiza.apply("MESSAGE_CREATE", MESSAGE_CREATE)

    atualiza.apply("MESSAGE_DELETE", {"id": "40", "channel_id": "20", "guild_id": "10"})

    assert estado.get_message(40) is None


def test_message_delete_de_mensagem_nunca_cacheada_e_no_op() -> None:
    """Sem falta na métrica: `messages` começa desligado, e apagar algo
    que nunca foi cacheado é o caso normal — não uma falha do cache.
    Punir isto como faria a métrica dizer que o cache está ruim quando
    ele está apenas incompleto, que é o estado dele por design."""
    estado, atualiza = fluxo()

    atualiza.apply("MESSAGE_DELETE", {"id": "40", "channel_id": "20"})

    # Antes de qualquer `get`: só a remoção aconteceu, e ela não conta
    # falta. A consulta logo abaixo registraria a dela, que é a resposta
    # certa para quem perguntou.
    assert estado.stats.misses.get(CacheKind.MESSAGE) is None
    assert estado.get_message(40) is None


def test_message_delete_bulk() -> None:
    estado, atualiza = fluxo()
    for mid in (41, 42, 43):
        atualiza.apply("MESSAGE_CREATE", {**MESSAGE_CREATE, "id": str(mid)})
    assert len(estado.messages) == 3

    atualiza.apply("MESSAGE_DELETE_BULK", {"channel_id": "20", "ids": ["41", "43"]})

    assert [m.id for m in estado.messages] == [42]


# --------------------------------------------------------------------------
# Payloads que não servem
# --------------------------------------------------------------------------


def test_payload_que_nao_e_objeto_e_ignorado() -> None:
    """Dispatch que não veio como objeto não descreve entidade nenhuma.
    Não é erro — é o caso de "não há o que guardar"."""
    estado, atualiza = fluxo()
    for payload in (None, "texto", 42, ["lista"]):
        atualiza.apply("MESSAGE_CREATE", payload)
        atualiza.apply("GUILD_CREATE", payload)

    assert estado.messages == ()
    assert estado.guilds == ()


def test_evento_desconhecido_e_ignorado() -> None:
    """`TYPING_START`, `PRESENCE_UPDATE` e os outros que o cache não
    guarda passam sem custo."""
    estado, atualiza = fluxo()
    atualiza.apply("TYPING_START", {"channel_id": "20", "user_id": "1"})
    atualiza.apply("PRESENCE_UPDATE", {"user": {"id": "1"}, "status": "online"})

    assert estado.users == ()


def test_guild_create_sem_id_nao_levanta() -> None:
    """`from_payload` devolve `None` quando falta o essencial — é a
    regra do 0006, e aqui ela vira "não guarda" em vez de exceção."""
    estado, atualiza = fluxo()

    atualiza.apply("GUILD_CREATE", {"name": "sem id"})
    atualiza.apply("CHANNEL_CREATE", {"name": "sem id"})
    atualiza.apply("GUILD_ROLE_UPDATE", {"guild_id": "10"})
    atualiza.apply("MESSAGE_CREATE", {"content": "sem id"})

    assert estado.guilds == ()
    assert estado.channels == ()
    assert estado.messages == ()
    assert estado.get_role(10, 30) is None


def test_aplicar_dois_vezes_e_idempotente_para_criação() -> None:
    """Reentrega do gateway acontece (resume). Reaplicar um
    `GUILD_CREATE` tem que dar o mesmo lugar, não duplicar nem apagar."""
    estado, atualiza = fluxo()
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)
    atualiza.apply("GUILD_CREATE", GUILD_CREATE)

    visao = estado.guild(10)
    assert visao is not None
    assert [m.user.id for m in visao.members] == [1]
    assert [c.id for c in visao.channels] == [20, 21]
    assert len(estado.users) == 1
