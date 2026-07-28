import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage

from app.config import OPENROUTER_MODEL


def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"It's always sunny in {city}!"


agent = create_agent(
    model=f"openrouter:{OPENROUTER_MODEL}",
    tools=[get_weather],
)

user_input = input("Enter your message: ")

for snapshot in agent.stream_events(
    {"messages": [HumanMessage(content=user_input)]},
    version="v3",
).values:
    latest = snapshot["messages"][-1]

    if isinstance(latest, HumanMessage):
        print(f"User: {latest.content}")
    elif isinstance(latest, AIMessage):
        if latest.tool_calls:
            for tc in latest.tool_calls:
                print(f"Tool call: {tc['name']}({tc['args']})")
        if isinstance(latest.content, str):
            print(f"Agent: {latest.content}")
        elif isinstance(latest.content, list):
            for block in latest.content:
                if block.get("type") == "text":
                    print(f"Agent: {block['text']}")
