from abc import ABC, abstractmethod
from typing import Callable

from ..state import AgentState
from ..tools.base import BaseTool


class ReActAgent(ABC):
    def __init__(
        self,
        tools: list[BaseTool] | None = None,
        max_iterations: int = 5,
        name: str = "ReActAgent",
    ):
        self.tools = tools or []
        self.max_iterations = max_iterations
        self.name = name
        self._tool_map = {t.name: t for t in self.tools}
        self._cb: Callable[[str, str], None] | None = None

    def set_callback(self, cb: Callable[[str, str], None]) -> None:
        self._cb = cb
        for tool in self.tools:
            tool.set_callback(cb)

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tool_map.get(name)

    def _emit(self, event: str, data: str) -> None:
        if self._cb:
            self._cb(event, data)

    @abstractmethod
    def reason(self, state: AgentState) -> dict:
        ...

    @abstractmethod
    async def act(self, state: AgentState) -> dict:
        ...
