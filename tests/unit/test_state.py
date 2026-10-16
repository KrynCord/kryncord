"""Testes de `kryncord.state` — o que vira `client.cache`.

Divididos em três: a construção (e o erro de passar os dois
argumentos), a leitura (pontual e geral), a visão por servidor, e a
remoção em massa que só acontece quando o bot sai de um guild.

Sobre tocar nos `put_*` e `drop_*` privados: são privados porque não
são API de **usuário** — quem mexer por fora reescreve o que o gateway
disse. Os testes não são usuário, são a outra metade do contrato: é
`EventUpdater` que vai chamar exatamente isto, e testá-lo só pelos
eventos esconderia se a chave ou o agrupamento estão errados, que é o
erro que não se vê (um `get()` que devolve `None` sempre, parecendo
política desligada).
"""

from __future__ import annotations

import pytest

from kryncord.cache import CacheKind, CachePolicy, MemoryCache
from kryncord.models import Channel, Guild, Member, Message, Role, User
from kryncord.state import ConnectionState, GuildState

# --------------------------------------------------------------------------
# Fábricas — payload nenhum aqui, são modelos puros
# --------------------------------------------------------------------------


def usuario(uid: int = 1, nome: str = "ana") -> User:
    return User(id=uid, username=nome)


def guild(gid: int = 10, nome: str = "Servidor") -> Guild:
    return Guild(id=gid, name=nome)


def canal(cid: int = 20, gid: int | None = 10, nome: str = "geral") -> Channel:
    return Channel(id=cid, guild_id=gid, name=nome)


def membro(uid: int = 1, nick: str | None = None) -> Member:
    return Member(user=usuario(uid), nick=nick)


def cargo(rid: int = 30, nome: str = "Mod") -> Role:
    return Role(id=rid, name=nome)


def mensagem(mid: int = 40, cid: int = 20, conteudo: str = "oi") -> Message:
    return Message(id=mid, channel_id=cid, content=conteudo)


def estado(**kwargs: object) -> ConnectionState:
    return ConnectionState(policy=CachePolicy(**kwargs))  # type: ignore[arg-type]


def estado_ligado() -> ConnectionState:
    """Estado com os dois opt-in ligados, para os testes que cuidam de
    agrupamento e roundtrip em vez de política.

    Sem isto, um `_put_member` ou `_put_message` seria simplesmente
    ignorado pelo default — e a asserção falharia num lugar que não
    tem nada a ver com o que o teste quer verificar.
    """
    return ConnectionState(policy=CachePolicy(members=True, messages=10))


# --------------------------------------------------------------------------
# Construção
# --------------------------------------------------------------------------


def test_padrao_e_o_nosso_cache_com_a_politica_padrao() -> None:
    state = ConnectionState()

    assert isinstance(state.cache, MemoryCache)
    assert state.policy is state.cache.policy
    assert state.enabled is True


def test_cache_e_policy_juntos_sao_erro() -> None:
    """Dois lugares dizendo o que guardar: quem passa `cache` já embutiu
    a política dentro dele, e ignorar o `policy` faria a configuração do
    usuário não efeito nenhum — o tipo de falha que só aparece quando
    alguém já confiou no resultado."""
    with pytest.raises(ValueError, match="nunca os dois"):
        ConnectionState(MemoryCache(), policy=CachePolicy())


def test_cache_injetado_traz_a_propria_politica() -> None:
    """`enabled` pergunta ao armazenamento, não ao chamador — senão com
    um cache trocado a resposta viria do lugar errado."""
    injetado = MemoryCache(CachePolicy(messages=9))

    state = ConnectionState(injetado)

    assert state.cache is injetado
    assert state.policy.messages == 9


def test_estado_vazio_de_cara() -> None:
    state = estado()

    assert state.me is None
    assert state.guilds == ()
    assert state.channels == ()
    assert state.users == ()
    assert state.messages == ()
    assert len(state) == 0


# --------------------------------------------------------------------------
# `me`
# --------------------------------------------------------------------------


def test_me_preenchido_e_lido() -> None:
    state = estado()
    state.set_me(usuario(99, "bot"))

    assert state.me is not None
    assert state.me.username == "bot"


def test_me_nao_conta_como_entrada() -> None:
    """`me` não é uma entrada, é a identificação de quem está conectado.
    Contá-lo faria `len()` mudar sem que nada entrou no repositório."""
    state = estado()
    state.set_me(usuario(99))

    assert len(state) == 0


def test_me_fica_fora_do_repositorio_e_nao_transborda() -> None:
    """`me` é campo próprio, não entrada: o repositório de usuários é
    LRU e não tem evento de remoção, então encher até transbordar
    derruba quem entrou — e "quem eu sou" não pode ser um desses.

    A segunda asserção documenta o preço: `me` **não** está no
    repositório, então `get_user(id_do_bot)` devolve `None` até o bot
    aparecer num payload de verdade (uma mensagem que ele mesmo mandou,
    por exemplo). A regra é uma só: `set_me` é "você é este", e não
    "você o viu".
    """
    state = ConnectionState(policy=CachePolicy(users=1))
    state.set_me(usuario(99, "bot"))

    for uid in (1, 2, 3):
        state._put_user(usuario(uid))

    assert state.stats.total_evictions >= 1  # o repositório transbordou
    assert state.me is not None
    assert state.me.id == 99
    assert state.get_user(99) is None


# --------------------------------------------------------------------------
# Escrita + leitura
# --------------------------------------------------------------------------


def test_cada_entidade_sobrevive_ao_roundtrip() -> None:
    state = estado_ligado()
    state._put_guild(guild())
    state._put_channel(canal())
    state._put_user(usuario())
    state._put_member(10, membro())
    state._put_role(10, cargo())
    state._put_message(mensagem())

    assert state.get_guild(10) is not None
    assert state.get_channel(20) is not None
    assert state.get_user(1) is not None
    assert state.get_member(10, 1) is not None
    assert state.get_role(10, 30) is not None
    assert state.get_message(40) is not None


def test_get_member_com_membros_desligados_devolve_none() -> None:
    """O default deixa `members` de fora, e este é o `None` que mais
    engana: não é "não é membro", é "não guardei". Por isso a política
    está em `cache.policy` — a resposta está a uma consulta de
    distância."""
    state = estado()
    # Ignorado pela política — é exatamente o que o teste quer ver.
    state._put_member(10, membro())

    assert state.get_member(10, 1) is None
    assert state.policy.members is False


def test_get_member_e_o_mesmo_que_na_visao() -> None:
    state = estado_ligado()
    state._put_guild(guild())
    state._put_member(10, membro())

    visao = state.guild(10)
    assert visao is not None

    assert state.get_member(10, 1) is visao.get_member(1)
    # E não é uma varredura: os dois são o mesmo lookup de chave.
    assert state.get_member(10, 999) is None
    assert state.get_member(11, 1) is None  # guild errada, mesmo usuário


def test_membr_de_guild_diferente_nao_vaza_para_a_outra() -> None:
    state = estado_ligado()
    state._put_member(10, membro(1, "aqui"))
    state._put_member(11, membro(1, "la"))

    assert state.get_member(10, 1).nick == "aqui"  # type: ignore[union-attr]
    assert state.get_member(11, 1).nick == "la"  # type: ignore[union-attr]


def test_canal_de_dm_entra_no_global_e_nao_num_guild() -> None:
    """DM tem `guild_id=None`, que é o valor, não a ausência. Ela
    existe e só a leitura global acha — não pertence a guild nenhuma."""
    state = estado()
    state._put_channel(canal(500, gid=None, nome="dm"))
    state._put_guild(guild())

    assert state.get_channel(500) is not None
    assert state.get_channel(500).guild_id is None  # type: ignore[union-attr]

    visao = state.guild(10)
    assert visao is not None
    assert state.get_channel(500) in state.channels
    assert visao.get_channel(500) is None


def test_enumerações_devolvem_o_que_foi_guardado() -> None:
    state = estado_ligado()
    state._put_guild(guild(10))
    state._put_guild(guild(11))
    state._put_channel(canal(20, 10))
    state._put_channel(canal(21, 11))
    state._put_user(usuario(1))
    state._put_message(mensagem())

    assert len(state.guilds) == 2
    assert len(state.channels) == 2
    assert len(state.users) == 1
    assert len(state.messages) == 1


def test_len_repr_e_as_dict() -> None:
    state = estado()
    state.set_me(usuario(99))
    state._put_guild(guild())

    assert len(state) == 1  # `me` não conta
    assert "ConnectionState" in repr(state)
    assert "enabled=True" in repr(state)

    retrato = state.as_dict()
    assert retrato["me"] == 99
    assert retrato["guilds"] == 1
    assert retrato["enabled"] is True
    assert retrato["hit_rate"] is None  # ninguém consultou ainda


def test_as_dict_com_me_ausente() -> None:
    assert estado().as_dict()["me"] is None


def test_enabled_false_quando_a_politica_desliga() -> None:
    state = ConnectionState(policy=CachePolicy.disabled())

    assert state.enabled is False
    assert state.as_dict()["enabled"] is False


# --------------------------------------------------------------------------
# Visão por servidor
# --------------------------------------------------------------------------


def test_guild_devolve_visao_quando_esta_cacheada() -> None:
    state = estado()
    state._put_guild(guild())

    visao = state.guild(10)

    assert isinstance(visao, GuildState)
    assert visao.id == 10
    assert visao.guild is not None
    assert visao.guild.name == "Servidor"


def test_guild_none_quando_nao_esta_cacheada() -> None:
    """Devolver uma visão vazia faria `state.members` parecer
    "servidor sem membros" — que é outra afirmação, e falsa."""
    assert estado().guild(999) is None


def test_visao_lista_membros_cargos_e_canais() -> None:
    state = estado_ligado()
    state._put_guild(guild())
    state._put_member(10, membro(1))
    state._put_member(10, membro(2))
    state._put_role(10, cargo(30))
    state._put_channel(canal(20, 10))

    visao = state.guild(10)
    assert visao is not None

    assert [m.user.id for m in visao.members] == [1, 2]
    assert [r.id for r in visao.roles] == [30]
    assert [c.id for c in visao.channels] == [20]


def test_visao_nao_ve_canal_de_outra_guild() -> None:
    """O ID é global, então achar um canal não prova que ele é desta
    guild — e devolver o de outra seria responder outra pergunta."""
    state = estado()
    state._put_guild(guild(10))
    state._put_channel(canal(600, gid=11))

    visao = state.guild(10)
    assert visao is not None

    assert state.get_channel(600) is not None  # global acha
    assert visao.get_channel(600) is None  # desta guild, não


def test_visao_sem_membros_e_tupla_vazia() -> None:
    """Política desligada, gateway ainda não entregou, ou não é membro:
    os três respondem o mesmo, e é vazio — nunca `None`. Enumeração que
    devolve `None` obriga todo leitor a tratar ausência em vez de
    lista."""
    state = estado()
    state._put_guild(guild())
    state._put_member(10, membro())

    visao = state.guild(10)
    assert visao is not None

    assert visao.members == ()
    assert visao.get_member(1) is None


def test_visao_get_role_e_get_member_sao_lookups() -> None:
    state = estado_ligado()
    state._put_guild(guild())
    state._put_member(10, membro(1))
    state._put_role(10, cargo(30))

    visao = state.guild(10)
    assert visao is not None

    assert visao.get_member(1) is not None
    assert visao.get_member(2) is None
    assert visao.get_role(30) is not None
    assert visao.get_role(31) is None


def test_duas_visoes_da_mesma_guild_veem_a_mesma_coisa() -> None:
    """Sem estado próprio: apontam para o mesmo armazenamento, e não
    têm o que divergir.

    A prova é comportamental em vez de identidade de objeto — uma
    `GuildState` não expõe o armazenamento para comparar, e não
    precisaria: o que importa é que o que entra por um aparece no
    outro, que é o que sem cópia não teria como deixar de acontecer.
    """
    state = estado_ligado()
    state._put_guild(guild())

    uma = state.guild(10)
    outra = state.guild(10)
    assert uma is not None and outra is not None
    assert uma is not outra  # objetos diferentes...

    state._put_member(10, membro(1))

    assert outra.members != ()  # ...mas a outra vê o que entrou


def test_repr_da_visao_diz_a_guild() -> None:
    state = estado()
    state._put_guild(guild(42))

    visao = state.guild(42)
    assert visao is not None
    assert repr(visao) == "GuildState(guild_id=42)"


# --------------------------------------------------------------------------
# Remoção
# --------------------------------------------------------------------------


def test_drop_guild_tira_s_o_servidor() -> None:
    state = estado()
    state._put_guild(guild())
    state._put_channel(canal(20, 10))

    state._drop_guild(10)

    assert state.get_guild(10) is None
    # Canal continua: quem sai não obrigou os filhos a sair junto.
    assert state.get_channel(20) is not None


def test_drop_guild_children_tira_os_grupos_inteiros() -> None:
    """Só acontece quando o bot **saiu** do servidor. Os canais vão
    porque a guild sumiu, não porque algum canal foi apagado — não há
    `CHANNEL_DELETE` para canais de um lugar que deixou de existir
    para nós."""
    state = estado_ligado()
    state._put_guild(guild())
    state._put_member(10, membro(1))
    state._put_member(10, membro(2))
    state._put_role(10, cargo(30))
    state._put_channel(canal(20, 10))

    state._drop_guild_children(10)

    visao = state.guild(10)
    assert visao is not None
    assert visao.members == ()
    assert visao.roles == ()
    assert visao.channels == ()
    # E o servidor em si fica: `GUILD_DELETE` chama as duas coisas
    # separadas, porque indisponibilidade chama só uma.
    assert state.get_guild(10) is not None


def test_drop_guild_children_nao_toca_na_guild_vizinha() -> None:
    state = estado_ligado()
    state._put_guild(guild(11))
    state._put_member(11, membro(7))
    state._put_member(10, membro(7))

    state._drop_guild_children(10)

    assert state.get_member(11, 7) is not None
    assert state.get_member(10, 7) is None


def test_drop_de_entidade_inexistente_e_no_op() -> None:
    """`MESSAGE_DELETE` de mensagem nunca cacheada é o caso normal.
    Erro aqui faria o cache reclamar por estar incompleto."""
    state = estado()

    state._drop_message(40)
    state._drop_channel(20)
    state._drop_role(10, 30)

    assert state.get_message(40) is None


# --------------------------------------------------------------------------
# Limpeza
# --------------------------------------------------------------------------


def test_clear_tudo_mantem_me() -> None:
    """Apagar a memória não faz o bot esquecer quem ele é."""
    state = estado()
    state.set_me(usuario(99, "bot"))
    state._put_guild(guild())

    state.clear()

    assert state.guilds == ()
    assert state.me is not None
    assert state.me.username == "bot"


def test_clear_de_um_tipo_so() -> None:
    state = estado()
    state._put_guild(guild())
    state._put_user(usuario())

    state.clear(CacheKind.GUILD)

    assert state.guilds == ()
    assert len(state.users) == 1


def test_clear_tambem_zera_a_visao() -> None:
    state = estado_ligado()
    state._put_guild(guild())
    state._put_member(10, membro())
    state._put_role(10, cargo())

    state.clear()

    visao = state.guild(10)
    assert visao is None  # nem o servidor existe mais
