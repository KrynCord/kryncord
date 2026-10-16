"""Testes de `kryncord.cache` — chaves, política, métrica e a mecânica.

Cobrem a camada que não depende de Discord nenhum: um dicionário com
teto, índice por grupo e contadores. Nada aqui abre rede, dorme ou
usa relógio de verdade.

Os casos que mais importam são os de **remoção**: LRU derrubando o
item certo em vez de o recente, o índice de grupo não ficando com
chave órfã, e `0` significando "desligado" em vez de "teto de zero
lugares" — os três são erros que passariam batido em teste de
funcionalidade e só apareceriam como memória vazando ou `get()`
devolvendo `None` para sempre.
"""

from __future__ import annotations

import dataclasses

import pytest

from kryncord.cache import (
    DEFAULT_USER_LIMIT,
    CacheKind,
    CachePolicy,
    CacheProtocol,
    CacheStats,
    MemoryCache,
    channel_key,
    guild_group,
    guild_key,
    member_key,
    message_key,
    role_key,
    user_key,
)

# --------------------------------------------------------------------------
# Chaves
# --------------------------------------------------------------------------


def test_chave_de_entidade_global_e_so_o_id() -> None:
    """Guild, canal, conta e mensagem têm ID global no Discord — a
    guild na chave seria redundância, e redundância que pode divergir."""
    assert guild_key(123) == "123"
    assert channel_key(456) == "456"
    assert user_key(789) == "789"
    assert message_key(999) == "999"


def test_chave_de_membro_carrega_a_guild() -> None:
    """Um membro não existe solto: `Member` é a presença de uma conta
    dentro de um servidor, com apelido e cargos próprios de lá."""
    assert member_key(10, 20) == "10:20"


def test_o_mesmo_usuario_em_duas_guilds_sao_entradas_diferentes() -> None:
    """Cinco guilds, cinco `Member` — e separar os dois é a diferença
    entre "Ana é Moderadora aqui" e "Ana é Moderadora em todo lugar"."""
    assert member_key(1, 7) != member_key(2, 7)


def test_cargo_tambem_e_por_guild() -> None:
    assert role_key(1, 9) == "1:9"
    assert role_key(1, 9) != role_key(2, 9)


def test_id_int_e_string_produzem_a_mesma_chave() -> None:
    """O Discord manda snowflake como string; quem lê de modelo tem
    `int`. Se os dois formatos fizessem chaves diferentes, um `get()`
    com o tipo errado devolveria `None` sem dizer por quê."""
    assert member_key(10, 20) == member_key("10", "20")
    assert guild_key(10) == guild_key("10")


def test_chaves_sao_strings_nao_tuplas() -> None:
    """`protocol.py` promete uma interface que outras implementações
    vão cumprir, e uma tupla `(guild, user)` só existe dentro de um
    dict. String atravessa qualquer backend sem tradução."""
    assert isinstance(guild_key(1), str)
    assert isinstance(member_key(1, 2), str)


def test_grupo_e_a_guild_de_origem() -> None:
    """É o rótulo que `set()` guarda para `group_values()` não varrer
    tudo — o que custaria a todos os servidores pagar por um só."""
    assert guild_group(10) == "10"


# --------------------------------------------------------------------------
# Política
# --------------------------------------------------------------------------


def test_default_e_o_documentado() -> None:
    politica = CachePolicy()

    assert politica.enabled is True
    # Os quatro que o gateway invalida sozinho.
    assert politica.guilds is True
    assert politica.channels is True
    assert politica.roles is True
    # Os dois que crescem com o servidor começam desligados.
    assert politica.members is False
    assert politica.messages == 0
    # Sem `USER_DELETE`, o limite é a única contenção.
    assert politica.users == DEFAULT_USER_LIMIT


def test_bool_ligado_e_sem_teto() -> None:
    """`None` significa "não tem teto", não "desligado": o limite
    destas entidades é a sessão, validada pelo próprio gateway."""
    politica = CachePolicy()
    assert politica.limit_for(CacheKind.GUILD) is None
    assert politica.limit_for(CacheKind.CHANNEL) is None


def test_bool_desligado_e_zero() -> None:
    politica = CachePolicy(members=False, guilds=False)
    assert politica.limit_for(CacheKind.MEMBER) == 0
    assert politica.limit_for(CacheKind.GUILD) == 0


def test_int_passa_direto_como_teto() -> None:
    politica = CachePolicy(messages=7, users=3)
    assert politica.limit_for(CacheKind.MESSAGE) == 7
    assert politica.limit_for(CacheKind.USER) == 3


def test_enabled_false_zera_todo_tipo() -> None:
    """Um flag que os campos individuais sobrescrevem não é um flag —
    é sugestão."""
    politica = CachePolicy(enabled=False, guilds=True, members=True, messages=500)
    for kind in CacheKind:
        assert politica.limit_for(kind) == 0
        assert politica.allows(kind) is False


def test_zero_significa_desligado_nao_teto_de_zero_lugares() -> None:
    """É o jeito de dizer "não guarda isto" sem inventar um quinto
    campo — e `allows` é quem traduz."""
    politica = CachePolicy(messages=0)
    assert politica.limit_for(CacheKind.MESSAGE) == 0
    assert politica.allows(CacheKind.MESSAGE) is False


def test_allows_para_os_tipos_ligados() -> None:
    politica = CachePolicy()
    assert politica.allows(CacheKind.GUILD) is True
    assert politica.allows(CacheKind.MEMBER) is False  # opt-in
    assert politica.allows(CacheKind.MESSAGE) is False  # opt-in
    assert politica.allows(CacheKind.USER) is True  # tem teto, mas guarda


def test_preset_desligado() -> None:
    politica = CachePolicy.disabled()
    assert politica.enabled is False
    assert all(not politica.allows(kind) for kind in CacheKind)


def test_preset_full_liga_os_dois_opt_in() -> None:
    politica = CachePolicy.full()
    assert politica.members is True
    assert politica.messages == 2_000
    # Mesmo no "full", o teto existe: a arquitetura proíbe guardar
    # indefinidamente, e "full" não é exceção à regra.
    assert politica.messages > 0


def test_politica_e_congelada() -> None:
    """Uma política que muda no meio do uso derrubaria itens já
    guardados sem avisar quem estava contando com eles."""
    politica = CachePolicy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        politica.messages = 100  # type: ignore[misc]


# --------------------------------------------------------------------------
# Métrica
# --------------------------------------------------------------------------


def test_contagem_por_tipo() -> None:
    stats = CacheStats()
    stats.hit(CacheKind.GUILD)
    stats.hit(CacheKind.GUILD)
    stats.miss(CacheKind.MEMBER)

    assert stats.hits[CacheKind.GUILD] == 2
    assert stats.misses[CacheKind.MEMBER] == 1
    assert stats.total_hits == 2
    assert stats.total_misses == 1


def test_hit_rate_none_quando_ninguem_consultou() -> None:
    """`0/0` não é 0% — é "não sei". Devolver `0.0` diria que tudo
    falhou, e quem lê a métrica concluiria o contrário do que houve."""
    assert CacheStats().hit_rate is None


def test_hit_rate_zero_quando_so_faltou() -> None:
    stats = CacheStats()
    stats.miss(CacheKind.USER)
    assert stats.hit_rate == 0.0


def test_hit_rate_e_a_metade() -> None:
    stats = CacheStats()
    stats.hit(CacheKind.USER)
    stats.miss(CacheKind.USER)
    assert stats.hit_rate == 0.5


def test_evict_com_contagem_nao_positiva_nao_conta() -> None:
    """`evict(0)` não é "removeu zero vezes", é "não houve remoção" —
    e uma contagem negativa não existe."""
    stats = CacheStats()
    stats.evict(CacheKind.MESSAGE, 0)
    stats.evict(CacheKind.MESSAGE, -5)
    assert stats.total_evictions == 0

    stats.evict(CacheKind.MESSAGE, 3)
    assert stats.total_evictions == 3


def test_snapshot_e_independente() -> None:
    """Quem guarda um `CacheStats` para comparar antes e depois não
    pode ver os números mudarem dentro do retrato."""
    stats = CacheStats()
    stats.hit(CacheKind.GUILD)
    copia = stats.snapshot()

    stats.hit(CacheKind.GUILD)
    copia.miss(CacheKind.MEMBER)

    assert copia.hits[CacheKind.GUILD] == 1
    assert stats.hits[CacheKind.GUILD] == 2
    assert stats.misses == {}  # a cópia não escreu no original


def test_reset_zera_contadores_e_mantem_tamanho() -> None:
    """Apagar a contagem de acertos não esvazia o cache — reportar
    `size == 0` logo depois de um reset seria mentira sobre quanto está
    na memória."""
    stats = CacheStats()
    stats.hit(CacheKind.GUILD)
    stats.miss(CacheKind.GUILD)
    stats.evict(CacheKind.MESSAGE, 2)
    stats.set_size(CacheKind.GUILD, 5)

    stats.reset()

    assert stats.total_hits == 0
    assert stats.total_misses == 0
    assert stats.total_evictions == 0
    assert stats.sizes[CacheKind.GUILD] == 5


def test_total_size_soma_os_tipos() -> None:
    stats = CacheStats()
    stats.set_size(CacheKind.GUILD, 2)
    stats.set_size(CacheKind.USER, 3)
    assert stats.total_size == 5


# --------------------------------------------------------------------------
# Armazenamento em memória
# --------------------------------------------------------------------------


def test_set_e_get_devolvem_o_mesmo_objeto() -> None:
    cache = MemoryCache()
    valor = {"qualquer": "coisa"}

    cache.set(CacheKind.GUILD, guild_key(1), valor)

    assert cache.get(CacheKind.GUILD, guild_key(1)) is valor
    assert cache.stats.hits[CacheKind.GUILD] == 1


def test_get_sem_armação_conta_falta() -> None:
    """Falta conta mesmo quando a política desligou o tipo: quem
    chamou `get_member()` recebeu `None`, e a métrica tem que dizer
    isso. Um `hit_rate` ruim porque a política não cobre o tipo é o
    sintoma certo — e some assim que alguém ligar o campo."""
    cache = MemoryCache(CachePolicy(members=False))

    assert cache.get(CacheKind.MEMBER, member_key(1, 2)) is None
    assert cache.stats.misses[CacheKind.MEMBER] == 1


def test_set_com_tipo_desligado_e_ignorado() -> None:
    """Ignorar é o contrato: a política é quem decide, e um `set` que
    desligasse a política por baixo tornaria `CachePolicy` sugestão."""
    cache = MemoryCache(CachePolicy(members=False, messages=0))

    cache.set(CacheKind.MEMBER, member_key(1, 2), object())
    cache.set(CacheKind.MESSAGE, message_key(3), object())

    assert cache.values(CacheKind.MEMBER) == ()
    assert cache.values(CacheKind.MESSAGE) == ()


def test_pop_devolve_e_remove() -> None:
    cache = MemoryCache()
    cache.set(CacheKind.GUILD, guild_key(1), "guild")

    assert cache.pop(CacheKind.GUILD, guild_key(1)) == "guild"
    assert cache.get(CacheKind.GUILD, guild_key(1)) is None
    assert cache.stats.sizes[CacheKind.GUILD] == 0


def test_pop_inexistente_nao_conta_falta() -> None:
    """`MESSAGE_DELETE` de mensagem nunca cacheada é o caso normal.
    Puni-lo como falha faria a métrica culpar o cache por estar
    incompleto, que é o estado dele por design."""
    cache = MemoryCache()

    assert cache.pop(CacheKind.MESSAGE, message_key(9)) is None
    assert cache.stats.misses.get(CacheKind.MESSAGE) is None


def test_values_sem_tipo_guardado_e_tupla_vazia() -> None:
    """E não `None`: `values()` descreve um conjunto, e conjunto vazio
    não é ausência."""
    assert MemoryCache().values(CacheKind.GUILD) == ()


def test_values_na_ordem_do_lru() -> None:
    """Do menos ao mais recentemente usado. Quem quer histórico usa a
    REST com cursor — o cache é estado, não arquivo."""
    cache = MemoryCache(CachePolicy(users=5))
    for uid in (1, 2, 3):
        cache.set(CacheKind.USER, user_key(uid), f"u{uid}")

    assert cache.values(CacheKind.USER) == ("u1", "u2", "u3")


def _com_membros() -> MemoryCache:
    """Cache com `members` ligado.

    O default deixa `members` de fora (é opt-in), e estes testes cuidam
    do **índice**, não da política — deixar o `set` ser ignorado faria
    as asserções passarem com `== ()` por motivo nenhum, que é a forma
    mais silenciosa de um teste não testar nada.
    """
    return MemoryCache(CachePolicy(members=True))


def test_group_values_devolve_so_os_do_grupo() -> None:
    cache = _com_membros()
    cache.set(CacheKind.MEMBER, member_key(10, 1), "a", group="10")
    cache.set(CacheKind.MEMBER, member_key(10, 2), "b", group="10")
    cache.set(CacheKind.MEMBER, member_key(20, 3), "c", group="20")

    assert cache.group_values(CacheKind.MEMBER, "10") == ("a", "b")
    assert cache.group_values(CacheKind.MEMBER, "20") == ("c",)


def test_group_values_em_ordem_de_chegada() -> None:
    """Não há ordem natural: o Discord manda um array que pode vir em
    qualquer. A de chegada é a única estável — a do gateway, que é de
    onde veio."""
    cache = _com_membros()
    for uid in (7, 3, 9):
        cache.set(CacheKind.MEMBER, member_key(10, uid), uid, group="10")

    assert cache.group_values(CacheKind.MEMBER, "10") == (7, 3, 9)


def test_grupo_inexistente_e_tupla_vazia() -> None:
    """E não `None`: perguntar "membros da guild 99" tem resposta —
    nenhum —, que é diferente de não ter perguntado."""
    assert MemoryCache().group_values(CacheKind.MEMBER, "99") == ()


def test_lru_derruba_o_mais_antigo() -> None:
    cache = MemoryCache(CachePolicy(users=2))
    for uid in (1, 2, 3):
        cache.set(CacheKind.USER, user_key(uid), f"u{uid}")

    assert cache.values(CacheKind.USER) == ("u2", "u3")
    assert cache.stats.evictions[CacheKind.USER] == 1


def test_get_promove_no_lru() -> None:
    """Sem a promoção, um autor que fala todo dia seria descartado por
    alguém que passou uma vez e nunca mais apareceu — "os últimos 5000
    vistos" viraria "os últimos 5000 inseridos"."""
    cache = MemoryCache(CachePolicy(users=2))
    for uid in (1, 2):
        cache.set(CacheKind.USER, user_key(uid), f"u{uid}")

    cache.get(CacheKind.USER, user_key(1))  # promove o 1
    cache.set(CacheKind.USER, user_key(3), "u3")

    # O 2 era o menos recente antes da inserção — saiu ele.
    assert cache.values(CacheKind.USER) == ("u1", "u3")


def test_get_sem_teto_nao_reordena() -> None:
    """`move_to_end` num tipo sem teto é trabalho que não muda nada,
    e não é de graça."""
    cache = MemoryCache(CachePolicy(guilds=True))
    cache.set(CacheKind.GUILD, guild_key(1), "a")
    cache.set(CacheKind.GUILD, guild_key(2), "b")

    assert cache.get(CacheKind.GUILD, guild_key(1)) == "a"
    assert cache.values(CacheKind.GUILD) == ("a", "b")


def test_derruba_um_por_rodada_ate_caber() -> None:
    """`while` e não `if`: o teto pode ter caído, e uma entrada por
    rodada não estaria de pé quando a diferença é grande."""
    cache = MemoryCache(CachePolicy(users=1))
    cache.set(CacheKind.USER, user_key(1), "a")
    cache.set(CacheKind.USER, user_key(2), "b")
    cache.set(CacheKind.USER, user_key(3), "c")

    assert cache.values(CacheKind.USER) == ("c",)
    assert cache.stats.evictions[CacheKind.USER] == 2


def test_teto_zero_nao_guarda_nada() -> None:
    """`messages=0` é desligado, e tem que valer no armazenamento, não
    só na política."""
    cache = MemoryCache(CachePolicy(messages=0))
    cache.set(CacheKind.MESSAGE, message_key(1), "oi")

    assert cache.values(CacheKind.MESSAGE) == ()


def test_membros_de_duas_guilds_nao_se_misturam() -> None:
    cache = _com_membros()
    cache.set(CacheKind.MEMBER, member_key(1, 50), "da guild 1", group="1")
    cache.set(CacheKind.MEMBER, member_key(2, 50), "da guild 2", group="2")

    assert cache.group_values(CacheKind.MEMBER, "1") == ("da guild 1",)
    assert cache.group_values(CacheKind.MEMBER, "2") == ("da guild 2",)


def test_pop_tira_a_chave_do_indice_do_grupo() -> None:
    """Chave órfã no índice seria um membro que aparece na enumeração
    mas não existe mais — `group_values` devolveria um fantasma, ou
    pior, o valor antigo."""
    cache = _com_membros()
    cache.set(CacheKind.MEMBER, member_key(10, 1), "a", group="10")
    assert cache.group_values(CacheKind.MEMBER, "10") == ("a",)

    cache.pop(CacheKind.MEMBER, member_key(10, 1))

    assert cache.group_values(CacheKind.MEMBER, "10") == ()


def test_grupo_que_fica_vazio_some_do_indice() -> None:
    """Um servidor que o bot saiu não pode deixar dict vazio no
    índice: memória e uma ordem fantasma para sempre."""
    cache = _com_membros()
    cache.set(CacheKind.MEMBER, member_key(10, 1), "a", group="10")

    cache.pop(CacheKind.MEMBER, member_key(10, 1))

    assert "10" not in cache._groups.get(CacheKind.MEMBER, {})


def test_troca_de_grupo_tira_do_indice_antigo() -> None:
    """Canal movido de guild (não acontece na prática, mas o índice não
    pode depender disso): a chave não pode ficar contando nos dois."""
    cache = MemoryCache()
    cache.set(CacheKind.CHANNEL, channel_key(20), "c", group="10")
    cache.set(CacheKind.CHANNEL, channel_key(20), "c", group="11")

    assert cache.group_values(CacheKind.CHANNEL, "10") == ()
    assert cache.group_values(CacheKind.CHANNEL, "11") == ("c",)


def test_lru_derruba_tambem_do_indice_do_grupo() -> None:
    """O caminho `evict → unindex`, que hoje não acontece por acaso:
    só `users` e `messages` têm teto, e nenhum dos dois recebe grupo
    (`_put_user` e `_put_message` mandam `group=None`).

    Passar grupo na mão é uso legítimo do protocolo — `group` é "de
    onde veio", e um chamador próprio pode agrupar o que quiser. Sem
    isto, a remoção por teto deixaria a chave órfã no índice do grupo,
    e `group_values` devolveria gente que já saiu.
    """
    cache = MemoryCache(CachePolicy(users=2))
    for uid in (1, 2, 3):
        cache.set(CacheKind.USER, user_key(uid), f"u{uid}", group="10")

    assert cache.group_values(CacheKind.USER, "10") == ("u2", "u3")
    assert cache.stats.evictions[CacheKind.USER] == 1


def test_clear_de_um_tipo_so() -> None:
    cache = MemoryCache()
    cache.set(CacheKind.GUILD, guild_key(1), "g")
    cache.set(CacheKind.USER, user_key(1), "u")

    cache.clear(CacheKind.GUILD)

    assert cache.values(CacheKind.GUILD) == ()
    assert cache.values(CacheKind.USER) == ("u",)
    assert cache.stats.sizes[CacheKind.GUILD] == 0
    assert cache.stats.sizes[CacheKind.USER] == 1


def test_clear_tudo_zera_tamanhos_mas_mantem_contadores() -> None:
    """Esvaziar o cache não apaga o histórico de acertos."""
    cache = MemoryCache()
    cache.set(CacheKind.GUILD, guild_key(1), "g")
    cache.get(CacheKind.GUILD, guild_key(1))

    cache.clear()

    assert cache.values(CacheKind.GUILD) == ()
    assert cache.stats.total_size == 0
    assert cache.stats.total_hits == 1


def test_clear_tambem_limpa_os_grupos() -> None:
    cache = _com_membros()
    cache.set(CacheKind.MEMBER, member_key(10, 1), "a", group="10")
    assert cache.group_values(CacheKind.MEMBER, "10") == ("a",)

    cache.clear(CacheKind.MEMBER)

    assert cache.group_values(CacheKind.MEMBER, "10") == ()


def test_stats_devolve_copia_com_tamanhos_atualizados() -> None:
    """Cópia, não o objeto vivo: quem guarda o retrato não pode ver os
    números mudarem na mão."""
    cache = MemoryCache()
    cache.set(CacheKind.GUILD, guild_key(1), "g")

    stats = cache.stats
    assert stats.sizes[CacheKind.GUILD] == 1

    cache.set(CacheKind.GUILD, guild_key(2), "g2")
    assert stats.sizes[CacheKind.GUILD] == 1  # o retrato não muda
    assert cache.stats.sizes[CacheKind.GUILD] == 2


def test_implementacao_conforma_o_protocolo() -> None:
    """É a promessa de `protocol.py`: trocável. Se `MemoryCache` sair
    do contrato, um backend próprio que o copiasse também sairia — e o
    erro apareceria só quando alguém trocasse em produção."""
    assert isinstance(MemoryCache(), CacheProtocol)


def test_repr_diz_o_que_importa() -> None:
    cache = MemoryCache()
    assert "MemoryCache" in repr(cache)
