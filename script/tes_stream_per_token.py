import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent

from app.config import OPENROUTER_MODEL

def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"It's always sunny in {city}!"


agent = create_agent(
    model=f"openrouter:{OPENROUTER_MODEL}",
    tools=[get_weather],
)

stream = agent.stream_events({
    "messages": [{"role": "user", "content": "What is the weather in SF?, and who is prabowo?"""}],
}, version="v3")

for message in stream.messages:
    print(f"{message}: ", end="", flush=True)
    for delta in message.text:
        print(delta, end="", flush=True)
    
final_state = stream.output