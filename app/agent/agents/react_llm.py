import re

from langchain_openai import ChatOpenAI

from .base import ReActAgent
from ..state import AgentState

ACTION_RE = re.compile(r'^ACTION:\s*(\w+)\s*(.*)', re.MULTILINE)
FINAL_RE = re.compile(r'^FINAL:\s*(.*)', re.MULTILINE)


class LLMReActAgent(ReActAgent):

    def __init__(
        self,
        model: ChatOpenAI,
        tools=None,
        max_iterations=5,
        system_prompt: str | None = None,
    ):
        super().__init__(tools=tools, max_iterations=max_iterations, name="LLMReAct")
        self._model = model
        self._system_prompt = system_prompt or "You are a helpful AI agent."

    def _build_prompt(self, state: AgentState) -> list:
        tool_descriptions = "\n".join(
            f"- {t.name}: {t.description}" for t in self.tools
        )
        system = f"{self._system_prompt}\n\nTools:\n{tool_descriptions}"

        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

        messages = [SystemMessage(content=system)]
        for msg in state.get("messages", []):
            if msg.startswith("User:"):
                messages.append(HumanMessage(content=msg[5:].strip()))
            elif msg.startswith("Observation:"):
                messages.append(ToolMessage(content=msg[12:].strip(), tool_call_id="cv"))
            else:
                content = msg
                if msg.startswith("Assistant:"):
                    content = msg[10:].strip()
                messages.append(AIMessage(content=content))
        return messages

    def reason(self, state: AgentState) -> dict:
        iterations = state.get("iterations", 0)

        if iterations >= self.max_iterations:
            msg = "Assistant: Reached max iterations. Please send a new message."
            self._emit("token", msg)
            self._emit("done", "")
            return {
                "messages": [msg],
                "next_action": "end",
                "iterations": iterations,
            }

        messages = self._build_prompt(state)
        full_response = ""

        try:
            for chunk in self._model.stream(messages):
                text = chunk.content if hasattr(chunk, "content") else ""
                if text:
                    self._emit("token", text)
                    full_response += text
        except Exception as e:
            self._emit("error", f"LLM error: {e}")
            return {
                "messages": [f"Assistant: Error: {e}"],
                "next_action": "end",
                "iterations": iterations,
            }

        response = full_response.strip()
        tool_name, tool_input = self._parse_action(response)

        if tool_name:
            self._emit("tool_status", f"{tool_name}")
            return {
                "messages": [f"Assistant: {response}"],
                "next_action": "action",
                "iterations": iterations,
            }
        else:
            return {
                "messages": [f"Assistant: {response}"],
                "next_action": "end",
                "iterations": iterations,
            }

    async def act(self, state: AgentState) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {"messages": [], "next_action": "", "iterations": state.get("iterations", 0)}

        last_msg = messages[-1]
        tool_name, tool_input = self._parse_action(last_msg)
        if not tool_name:
            return {"messages": [], "next_action": "", "iterations": state.get("iterations", 0)}

        tool = self.get_tool(tool_name)
        if tool is None:
            result = f"Unknown tool: {tool_name}"
        else:
            result = await tool.execute(tool_input)

        self._emit("tool_result", result if len(result) < 200 else f"Done ({len(result)} chars)")
        return {
            "messages": [f"Observation: {result}"],
            "next_action": "",
            "iterations": state.get("iterations", 0) + 1,
        }

    def _parse_action(self, response: str) -> tuple[str | None, str | None]:
        text = response
        if text.startswith("Assistant:"):
            text = text[10:].strip()

        lines = text.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            m = re.match(r'^ACTION:\s*(\w+)\s*(.*)', line)
            if m:
                name = m.group(1)
                same_line = m.group(2).strip()
                if name == "edit_cv" and not same_line:
                    rest = "\n".join(lines[i+1:]).strip()
                    return name, rest if rest else same_line
                return name, same_line
        return None, None
