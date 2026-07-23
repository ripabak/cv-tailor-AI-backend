from abc import ABC, abstractmethod
from typing import Callable


class BaseTool(ABC):
    name: str = "base_tool"
    description: str = "Base tool"

    def __init__(self):
        self._cb: Callable[[str, str], None] | None = None

    def set_callback(self, cb: Callable[[str, str], None]) -> None:
        self._cb = cb

    def _emit(self, event: str, data: str) -> None:
        if self._cb:
            self._cb(event, data)

    @abstractmethod
    async def execute(self, query: str) -> str:
        ...
