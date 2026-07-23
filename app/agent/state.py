import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    messages: Annotated[list[str], operator.add]
    cv_id: int
    next_action: str
    iterations: int
