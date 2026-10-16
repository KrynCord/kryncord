# Publicar uma versão

Do código ao `pip install kryncord`. Este documento é o passo a passo que
eu sigo — a Action `.github/workflows/publish.yml` já automatiza quase
tudo dele.

```text
código → pyproject.toml → build → TestPyPI → PyPI → pip install kryncord
```

## Regra única

**Versão publicada não se sobrescreve.** O PyPI é imutável: um upload da
`0.1.0b1` é para sempre, certo ou errado. Se algo quebrar depois, saem
`0.1.0b2`, `0.1.0b3`… — nunca um re-upload da mesma numeração.

## 1. Contas

1. Conta no [TestPyPI](https://test.pypi.org) e outra no
   [PyPI](https://pypi.org) — são contas separadas, o login de um não
   serve no outro.
2. **2FA ligado** nos dois. O PyPI exige 2FA para publicar.
3. Para publicar na mão, gere um **API token** em cada um
   (`Settings → API tokens`) e guarde como `PYPI_TOKEN` / `TESTPYPI_TOKEN`.

## 2. Trusted Publishing (uma vez só)

A Action publica com OIDC: nenhum token fica guardado no GitHub. Configure
nos dois sites — em **Publishing → Add a new publisher**:

| Campo | Valor |
|---|---|
| Owner | `KrynCord` |
| Repository | `kryncord` |
| Workflow | `publish.yml` |
| Environment | `pypi` (no PyPI) / `testpypi` (no TestPyPI) |

Os environments já existem no repositório, e o `publish.yml` já os usa.

## 3. Bump da versão

A versão mora em **dois lugares** e os dois têm que bater:

```text
src/kryncord/version.py   →  __version__ = "0.1.0b1"
pyproject.toml            →  version = "0.1.0b1"
```

`tests/unit/test_public_api.py` compara os dois com o metadata instalado —
esquecer um deles derruba o teste na hora, não na publicação.

A numeração segue [PEP 440](https://peps.python.org/pep-0440/) para
pré-release:

```text
0.1.0b1  →  beta 1
0.1.0b2  →  beta 2 (correção)
0.1.0    →  estável
0.2.0    →  recurso novo compatível
```

## 4. CHANGELOG

Já tem uma seção `[Unreleased]`. Move o que foi pro `0.1.0b1`, com data,
e confere os links no rodapé.

## 5. Publicar

```bash
# só confere que tag e versão são a mesma coisa antes de subir
git tag v0.1.0b1
git push origin v0.1.0b1
```

A Action então:

```text
checks (ruff + mypy + pytest)
   │  falhou, para tudo — nada de publicar lixo
   ▼
build (sdist + wheel + twine check)
   │  confere se a tag == versão do pyproject
   ▼
publish-testpypi
   │
   ▼
publish-pypi
```

## 6. Conferir no TestPyPI antes

A cadeia `publish-testpypi → publish-pypi` faz isso automaticamente, mas
na mão dá para testar o pacote como se tivesse vindo do PyPI:

```bash
python -m pip install --index-url https://test.pypi.org/simple/ `
    --extra-index-url https://pypi.org/simple kryncord==0.1.0b1
```

O `--extra-index-url` é obrigatório aqui: o TestPyPI não serve as
dependências (`httpx`, `websockets`), então elas vêm do PyPI de verdade.
Sem ele o `pip` reclama que não achou `httpx`.

## 7. Instalar a beta

Atenção que é o detalhe que mais pega: **o `pip` não instala pré-release
por padrão**. Sem `--pre`, `pip install kryncord` só acha a estável mais
alta — que hoje é nenhuma.

```bash
python -m pip install --pre kryncord
```

## Publicar na mão (alternativa)

Quando a Action não serve — por exemplo, para um hotfix:

```bash
python -m pip install --upgrade build twine
python -m build                       # gera sdist + wheel em dist/
python -m twine check --strict dist/* # valida os metadados
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```

O `twine` pede `__token__` como usuário e o API token como senha. Nunca
faça upload sem o `twine check` antes: ele é que pega metadado quebrado
(classifier inválido, README que não renderiza) antes do PyPI rejeitar
— ou pior, aceitar.

## O que vai dentro do pacote

`[tool.hatch.build.targets.sdist]` no `pyproject.toml` tem uma lista
explícita de `only-include`. Sem ela o hatchling embala tudo que estiver
na pasta — na primeira tentativa o sdist saiu com **9,2 MB**, quase tudo
`base/discord.js` de referência. Hoje são **460 KB**, e o wheel contém só
`kryncord/`.
