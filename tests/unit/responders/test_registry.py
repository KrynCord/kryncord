"""`registry.py` + `decorators.py` — registro e conflito na importação.

O fio: conflito de padrão é o bug que não falha nunca — só erra,
atendendo a quem chegar por último. A importação é a única chance de
apontar os dois módulos.
"""

from __future__ import annotations

import pytest

from kryncord.enums import ResponderType
from kryncord.errors import ResponderDefinitionError
from kryncord.responders.decorators import responder
from kryncord.responders.registry import ResponderRegistry

B = [ResponderType.BUTTON]
S = [ResponderType.STRING_SELECT]
M = [ResponderType.MODAL_SUBMIT]


async def h(ctx): ...


async def h2(ctx): ...


class TestRegistro:
    def test_registra_e_match(self) -> None:
        reg = ResponderRegistry()
        responder("/system/confirm", types=B, registry=reg)(h)

        achado = reg.match("/system/confirm", ResponderType.BUTTON)

        assert achado is not None
        assert achado.entrada.handler is h
        assert achado.params == {}

    def test_sem_types_e_erro(self) -> None:
        """Sem filtro, casaria qualquer interação — inclusive as que
        não existem ainda."""
        reg = ResponderRegistry()

        with pytest.raises(ResponderDefinitionError, match="sem types"):
            responder("/a", types=[], registry=reg)(h)

    def test_cache_invalido_e_erro(self) -> None:
        reg = ResponderRegistry()

        with pytest.raises(ResponderDefinitionError, match="'any', 'cached' ou 'fresh'"):
            responder("/a", types=B, cache="sempre", registry=reg)(h)

    def test_handler_sync_e_erro(self) -> None:
        """Handler síncrono bloquearia o loop inteiro no primeiro
        clique — não no décimo."""
        reg = ResponderRegistry()

        def sync(ctx): ...

        with pytest.raises(ResponderDefinitionError, match="não é async"):
            responder("/a", types=B, registry=reg)(sync)


class TestConflitos:
    def test_mesmo_padrao_tipos_disjuntos_sao_dois_registros(self) -> None:
        """`types` é filtro, não prioridade (0013): o mesmo id em
        modal e em botão são dois lugares da interface."""
        reg = ResponderRegistry()
        responder("/register/form", types=B, registry=reg)(h)
        responder("/register/form", types=M, registry=reg)(h2)

        assert len(reg) == 2
        assert reg.match("/register/form", ResponderType.BUTTON).entrada.handler is h
        assert reg.match("/register/form", ResponderType.MODAL_SUBMIT).entrada.handler is h2

    def test_mesmo_padrao_tipos_sobrepostos_e_erro(self) -> None:
        reg = ResponderRegistry()
        responder("/register/form", types=[ResponderType.BUTTON], registry=reg)(h)

        with pytest.raises(ResponderDefinitionError, match="conflita"):
            responder(
                "/register/form",
                types=[ResponderType.BUTTON, ResponderType.MODAL_SUBMIT],
                registry=reg,
            )(h2)

    def test_pesos_iguais_casando_o_mesmo_id_e_erro(self) -> None:
        """/a/:x e /a/:y têm o mesmo peso e casam /a/1 — ninguém decide
        qual atende, e o empate exato é erro na importação."""
        reg = ResponderRegistry()
        responder("/a/:x", types=B, registry=reg)(h)

        with pytest.raises(ResponderDefinitionError, match="conflita"):
            responder("/a/:y", types=B, registry=reg)(h2)

    def test_pesos_iguais_literais_diferentes_passam(self) -> None:
        """/a/:x e /b/:y nunca casam o mesmo id — são duas rotas."""
        reg = ResponderRegistry()
        responder("/a/:x", types=B, registry=reg)(h)
        responder("/b/:y", types=B, registry=reg)(h2)

        assert len(reg) == 2

    def test_mensagem_cita_os_dois_modulos(self) -> None:
        """Sem citar os dois, o usuário persegue o lugar errado."""
        reg = ResponderRegistry()

        async def primeiro(ctx): ...

        responder("/x", types=B, registry=reg)(primeiro)

        with pytest.raises(ResponderDefinitionError, match=r"responders\.test_registry"):
            responder("/x", types=B, registry=reg)(h)


class TestMatchPrioridade:
    def test_mais_especifico_casa_primeiro(self) -> None:
        reg = ResponderRegistry()
        responder("/manage/**", types=B, registry=reg)(h)
        responder("/manage/user/:id/ban", types=B, registry=reg)(h2)

        achado = reg.match("/manage/user/9/ban", ResponderType.BUTTON)

        assert achado.entrada.handler is h2
        assert achado.params == {"id": "9"}

    def test_tipo_errado_nao_casa(self) -> None:
        reg = ResponderRegistry()
        responder("/a", types=B, registry=reg)(h)

        assert reg.match("/a", ResponderType.MODAL_SUBMIT) is None

    def test_sem_tipo_casa_qualquer(self) -> None:
        """`tipo=None` ignora o filtro — é o caminho do teste."""
        reg = ResponderRegistry()
        responder("/a", types=B, registry=reg)(h)

        assert reg.match("/a").entrada.handler is h

    def test_por_tipo_filtra(self) -> None:
        reg = ResponderRegistry()
        responder("/a", types=B + M, registry=reg)(h)

        botao = reg.por_tipo(ResponderType.BUTTON)
        modal = reg.por_tipo(ResponderType.STRING_SELECT)

        assert len(botao) == 1
        assert len(modal) == 0


class TestGlobal:
    def test_decorator_sem_registry_usa_o_global(self) -> None:
        """K12: o global é o default — `@responder` num módulo
        registra sem que o usuário aponte um client."""
        from kryncord.registry import registry

        rotulo = "/teste/global/k12"
        try:
            responder(rotulo, types=B)(h)

            assert registry.responders.match(rotulo, ResponderType.BUTTON) is not None
        finally:
            registry.responders.limpa()

    def test_limpa_zera(self) -> None:
        reg = ResponderRegistry()
        responder("/a", types=B, registry=reg)(h)
        reg.limpa()

        assert len(reg) == 0
