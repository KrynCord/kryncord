"""`converters.py` — anotação é conversor, cache antes de REST (0014).

O fio: cada tipo da tabela tem um caminho determinístico — e o
`ConversionError` tem que carregar o nome do param, senão o usuário
fica sabendo o valor mas não qual dos cinco quebrou.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

import pytest

from kryncord.errors import ConversionError, ResponderDefinitionError
from kryncord.models.interaction import Interaction
from kryncord.responders.converters import (
    converte,
    plano_de,
    recebe_params_dict,
    registrar_conversor,
    resolve_conversor,
)


class Cor(StrEnum):
    VERMELHO = "vermelho"
    AZUL = "azul"


class CtxFalso:
    """O mínimo que um conversor do Discord pergunta: nada."""

    interaction = Interaction(id=1, application_id=1, type=3, token="t", guild_id=99)
    cache = None
    client = None


class TestResolve:
    def test_sem_anotacao_e_identidade(self) -> None:
        conversor, opcional = resolve_conversor(None)

        assert conversor is None
        assert opcional is False

    def test_str_e_identidade(self) -> None:
        assert resolve_conversor(str)[0] is None

    def test_union_com_none_marca_opcional(self) -> None:
        _, opcional = resolve_conversor(int | None)

        assert opcional is True

    def test_union_de_dois_tipos_e_erro(self) -> None:
        """Union sem `None` não tem conversor único — em runtime seria
        adivinhar."""
        with pytest.raises(ResponderDefinitionError, match="union"):
            resolve_conversor(int | str)

    def test_strenum_vira_validado(self) -> None:
        conversor, _ = resolve_conversor(Cor)

        assert conversor("azul", CtxFalso()) is Cor.AZUL
        with pytest.raises(ConversionError, match="fora do Cor"):
            conversor("roxo", CtxFalso())

    def test_anotacao_desconhecida_e_erro_na_importacao(self) -> None:
        class Exotica:
            pass

        with pytest.raises(ResponderDefinitionError, match="não tem conversor"):
            resolve_conversor(Exotica)


class TestConversoresBase:
    async def test_int(self) -> None:
        conversor, _ = resolve_conversor(int)
        assert await converte(conversor, "42", None, "p") == 42

    async def test_int_invalido_levanta_com_nome_do_param(self) -> None:
        conversor, _ = resolve_conversor(int)

        with pytest.raises(ConversionError, match="param 'p'"):
            await converte(conversor, "abc", None, "p")

    async def test_float(self) -> None:
        conversor, _ = resolve_conversor(float)
        assert await converte(conversor, "1.5", None, "p") == 1.5

    async def test_bool(self) -> None:
        """`"true"/"1"/"yes"` → True, resto → False — a tabela da 08 §2."""
        conversor, _ = resolve_conversor(bool)

        assert await converte(conversor, "true", None, "p") is True
        assert await converte(conversor, "1", None, "p") is True
        assert await converte(conversor, "YES", None, "p") is True
        assert await converte(conversor, "no", None, "p") is False

    async def test_uuid(self) -> None:
        conversor, _ = resolve_conversor(UUID)
        assert await converte(conversor, "12345678-1234-5678-1234-567812345678", None, "p") == UUID(
            "12345678-1234-5678-1234-567812345678"
        )

    async def test_literal(self) -> None:
        conversor, _ = resolve_conversor(Literal["a", "b"])

        assert await converte(conversor, "a", None, "p") == "a"
        with pytest.raises(ConversionError, match="fora do Literal"):
            await converte(conversor, "c", None, "p")


class TestDatetime:
    """A regra de uma linha da 0014: ISO, epoch s, epoch ms — pelo formato."""

    async def test_epoch_segundos(self) -> None:
        conversor, _ = resolve_conversor(datetime)
        resultado = await converte(conversor, "1700000000", None, "p")

        assert resultado == datetime.fromtimestamp(1700000000)

    async def test_epoch_milissegundos(self) -> None:
        conversor, _ = resolve_conversor(datetime)
        resultado = await converte(conversor, "1700000000000", None, "p")

        assert resultado == datetime.fromtimestamp(1700000000)

    async def test_iso(self) -> None:
        conversor, _ = resolve_conversor(datetime)
        resultado = await converte(conversor, "2024-01-01T10:00:00", None, "p")

        assert resultado == datetime(2024, 1, 1, 10, 0, 0)

    async def test_lixo_e_erro(self) -> None:
        conversor, _ = resolve_conversor(datetime)

        with pytest.raises(ConversionError, match="não é datetime"):
            await converte(conversor, "ontem", None, "p")


class TestConversoresDiscord:
    """Cache → REST → `ConversionError`, a ordem da 0014."""

    class CacheFalso:
        def __init__(self, usuarios: dict | None = None, mensagens: dict | None = None) -> None:
            self.usuarios = usuarios or {}
            self.mensagens = mensagens or {}

        def get_user(self, uid: int):
            return self.usuarios.get(uid)

        def get_message(self, mid: int):
            return self.mensagens.get(mid)

    class ClientFalso:
        def __init__(self, api=None) -> None:
            self.api = api
            self.cache = None

    def _ctx(self, cache=None, client=None) -> CtxFalso:
        ctx = CtxFalso()
        ctx.cache = cache
        ctx.client = client
        return ctx

    async def test_user_no_cache_nao_vai_a_rede(self) -> None:
        from kryncord.models.user import User

        usuario = User(id=7, username="ana", discriminator="0001")
        cache = self.CacheFalso(usuarios={7: usuario})
        conversor, _ = resolve_conversor(User)

        class BateNaRede:
            class api:
                class users:
                    @staticmethod
                    async def fetch(uid: int):
                        raise AssertionError("não devia ter ido à REST — o cache tinha")

        resultado = await converte(conversor, "7", self._ctx(cache=cache, client=BateNaRede()), "u")

        assert resultado is usuario

    async def test_user_fora_do_cache_sem_client_e_erro(self) -> None:
        from kryncord.models.user import User

        conversor, _ = resolve_conversor(User)

        with pytest.raises(ConversionError, match="sem client"):
            await converte(conversor, "7", self._ctx(cache=self.CacheFalso()), "u")

    async def test_user_no_miss_vai_a_rest(self) -> None:
        """O miss vai à REST — conversão falhando num usuário que
        existiria seria erro não-falso-positivo (0014)."""
        from kryncord.models.user import User

        usuario = User(id=7, username="ana", discriminator="0001")

        class ApiComUser:
            class users:
                @staticmethod
                async def fetch(uid: int):
                    return usuario

        conversor, _ = resolve_conversor(User)

        resultado = await converte(
            conversor,
            "7",
            self._ctx(cache=self.CacheFalso(), client=self.ClientFalso(ApiComUser)),
            "u",
        )

        assert resultado is usuario

    async def test_member_sem_guild_e_erro_claro(self) -> None:
        """`Member` exige guild — e a guild vem do contexto, não do
        modelo (0008: `Member` não tem `guild_id`)."""
        from kryncord.models.member import Member

        conversor, _ = resolve_conversor(Member)
        ctx = CtxFalso()
        ctx.interaction = Interaction(id=1, application_id=1, type=3, token="t")

        with pytest.raises(ConversionError, match="exige guild"):
            await converte(conversor, "123", ctx, "m")

    async def test_message_fora_do_cache_e_erro_explicando(self) -> None:
        """`Message` é só cache: REST exige `channel_id`, que o
        custom_id não carrega. O erro tem que dizer isso."""
        from kryncord.models.message import Message

        conversor, _ = resolve_conversor(Message)

        with pytest.raises(ConversionError, match="channel_id"):
            await converte(conversor, "123", self._ctx(cache=self.CacheFalso()), "msg")


class TestRegistrarConversor:
    def test_registra_e_usa(self) -> None:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Pontos:
            valor: int

        def _de_pontos(raw: str, ctx: object) -> Pontos:
            return Pontos(int(raw) * 10)

        registrar_conversor(Pontos, _de_pontos)
        conversor, _ = resolve_conversor(Pontos)

        assert conversor("5", None).valor == 50

    def test_sobrescrever_existente_e_erro(self) -> None:
        """Dois módulos brigando pelo mesmo tipo é bug que só aparece
        em runtime — a importação é a única chance."""
        with pytest.raises(ResponderDefinitionError, match="já existe conversor"):
            registrar_conversor(int, lambda raw, ctx: int(raw) * 2)


class TestPlanoDe:
    """O plano de injeção — validado na importação, executado no clique."""

    async def test_handler_sozinho_plano_vazio(self) -> None:
        async def h(ctx): ...

        assert plano_de(h, "/a") == ()

    async def test_star_args_pula_validacao(self) -> None:
        """K9: `*args` é o pedido explícito de "me dá tudo"."""

        async def h(ctx, *args): ...

        assert plano_de(h, "/a") == ()

    async def test_param_da_rota_entra_no_plano(self) -> None:
        async def h(ctx, user_id: int): ...

        ((nome, conversor, opcional, tem_default),) = plano_de(h, "/a/{user_id}")

        assert nome == "user_id"
        assert conversor is resolve_conversor(int)[0]
        assert opcional is False
        assert tem_default is False

    async def test_param_fora_da_rota_e_erro(self) -> None:
        async def h(ctx, user_ld: int): ...

        with pytest.raises(ResponderDefinitionError, match="user_ld"):
            plano_de(h, "/a/{user_id}")

    async def test_param_fora_com_default_passa(self) -> None:
        """Default existe para param opcional de código, não de rota."""

        async def h(ctx, user_id: int, pagina: int = 1): ...

        plano = plano_de(h, "/a/{user_id}")

        assert [item[0] for item in plano] == ["user_id", "pagina"]

    async def test_opcional_da_rota_mais_anotacao_required(self) -> None:
        """A união dos dois sinais: `{?x}` na rota OU `| None` na
        anotação — os exemplos da 0013 usam cada forma de um jeito."""

        async def h(ctx, number: int): ...

        ((_, _, opcional, _),) = plano_de(h, "/page/{?number}")

        assert opcional is True

    async def test_anotacao_none_marca_opcional(self) -> None:
        async def h(ctx, date: datetime | None): ...

        ((_, _, opcional, _),) = plano_de(h, "/remember/{date}")

        assert opcional is True

    async def test_dict_form_e_detectada(self) -> None:
        async def h(ctx, params): ...

        assert recebe_params_dict(h, "/a/{x}") is True

    async def test_param_da_rota_chamado_params_nao_e_dict(self) -> None:
        """Se a rota tem um param com esse nome, ele é param — o valor
        concreto vence o dict."""

        async def h(ctx, params): ...

        assert recebe_params_dict(h, "/a/{params}") is False

    async def test_handler_sem_ctx_e_erro(self) -> None:
        async def h(): ...

        with pytest.raises(ResponderDefinitionError, match="contexto"):
            plano_de(h, "/a")
