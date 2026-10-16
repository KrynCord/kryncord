"""Logging da KrynCord.

Regras:

1. A biblioteca usa o logger ``kryncord`` (e filhos). Nunca configura o
   logger raiz — isso é decisão da aplicação.
2. Nenhum token, header de autenticação ou segredo aparece em log, em
   nenhum nível.
3. `setup_logging` é opcional. Quem quiser configurar na mão pode.
"""

from __future__ import annotations

import logging

ROOT_LOGGER_NAME = "kryncord"

#: Sufixos de atributo que nunca devem ir para o log, em nenhum nível.
#: Usado por `redact`.
SENSITIVE_KEYS = frozenset(
    {
        "token",
        "authorization",
        "auth",
        "secret",
        "password",
        "session_id",
        "resume_gateway_url",
    }
)


def get_logger(name: str | None = None) -> logging.Logger:
    """Retorna um logger dentro do namespace ``kryncord``.

    ``get_logger("rest")`` devolve o logger ``kryncord.rest``.
    """
    if not name:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def setup_logging(level: str | int = "INFO") -> logging.Logger:
    """Configura o logger ``kryncord`` com um handler de stream.

    Não toca no logger raiz. Seguro de chamar mais de uma vez — o handler
    é substituído, não acumulado.
    """
    logger = get_logger()
    logger.setLevel(level)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def redact(data: object) -> object:
    """Remove valores sensíveis de uma estrutura, para log seguro.

    Faz o mínimo: copia dict, mascarando chaves sensíveis. Percore listas
    e tuples, preservando o tipo. Qualquer outra coisa volta intacta —
    esta função não é um sanitizador de payload, é um último filtro antes
    do log.
    """
    if isinstance(data, dict):
        return {
            key: "***" if isinstance(key, str) and key.lower() in SENSITIVE_KEYS else redact(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(item) for item in data]
    if isinstance(data, tuple):
        return tuple(redact(item) for item in data)
    return data
