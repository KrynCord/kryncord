"""Versão do pacote.

Centralizada para que `importlib.metadata` e o código importado não
divergam. `pyproject.toml` é a fonte da verdade para o build; este
arquivo é a fonte da verdade para o runtime.
"""

__version__ = "0.1.0b1"
