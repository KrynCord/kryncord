"""`FileUpload` — o campo que só existe em modal, e só dentro de `Label`.

É a confirmação em código da ideia 15 §3: `FileUpload` (type 19) é filho
de `Label` e de mais nenhum lugar. Fora de modal → o validador do
modal reclama; fora de `Label` → o `Label` reclama. O componente não
precisa saber nada disso — ele só declara `era = "modal"` e a validação
da árvore faz o resto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kryncord.components.base import Component, limita
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

MAX_ARQUIVOS = 25


@dataclass(frozen=True, slots=True)
class FileUpload(Component):
    """Upload de arquivos dentro de um modal.

        Label("Anexo", FileUpload(custom_id="doc", max_values=3))

    `min_values`/`max_values` são quantos arquivos o usuário precisa
    anexar — o mesmo contrato de `min_values`/`max_values` dos selects.
    """

    type = ComponentType.FILE_UPLOAD

    custom_id: str
    min_values: int = 1
    max_values: int = 1
    required: bool = False
    file_types: tuple[str, ...] = ()

    era = "modal"

    def __post_init__(self) -> None:
        limita(self.custom_id, 100, "custom_id", onde="FileUpload")
        if self.min_values < 0 or self.min_values > MAX_ARQUIVOS:
            raise ComponentError(
                f"FileUpload: min_values={self.min_values} fora de 0..{MAX_ARQUIVOS}"
            )
        if self.max_values < 1 or self.max_values > MAX_ARQUIVOS:
            raise ComponentError(
                f"FileUpload: max_values={self.max_values} fora de 1..{MAX_ARQUIVOS}"
            )
        if self.min_values > self.max_values:
            raise ComponentError(
                f"FileUpload: min_values={self.min_values} > max_values={self.max_values}"
            )
        object.__setattr__(self, "file_types", tuple(str(t) for t in self.file_types))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 19, "custom_id": self.custom_id}
        if self.min_values != 1:
            payload["min_values"] = self.min_values
        if self.max_values != 1:
            payload["max_values"] = self.max_values
        if self.required:
            payload["required"] = True
        if self.file_types:
            payload["file_types"] = list(self.file_types)
        return payload


def create_file_upload(custom_id: str, **kwargs: Any) -> FileUpload:
    """Alias fino — simetria com os demais `create_*`."""
    return FileUpload(custom_id=custom_id, **kwargs)


__all__ = ["MAX_ARQUIVOS", "FileUpload", "create_file_upload"]
