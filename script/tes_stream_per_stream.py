import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent

from app.config import OPENROUTER_MODEL

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"It's always sunny in {city}!"


agent = create_agent(
    model=f"openrouter:{OPENROUTER_MODEL}",
    tools=[get_weather],
)

stream = agent.stream_events({
    "messages": [{"role": "user", "content": "What is the weather in SF?, and who is prabowo?"}],
}, version="v3")

collected_events = []

for event in stream:
    collected_events.append(event)
    sys.stdout.write(".")

sys.stdout.write("\n\n")

ts = datetime.now().strftime('%Y%m%d_%H%M%S')
events_file = LOG_DIR / f"events_{ts}.txt"
events_file.write_text("\n".join(str(e) for e in collected_events))
print(f"Events saved to: {events_file}")

final_state = stream.output
state_file = LOG_DIR / f"state_{ts}.txt"
state_file.write_text(str(final_state))
print(f"Final state saved to: {state_file}")

print("\n=== SUMMARY ===")
print(f"Total events: {len(collected_events)}")
print(f"Final messages: {len(final_state.get('messages', []))}")

usage = final_state.get("messages", [])[-1].response_metadata if final_state.get("messages") else {}
if usage:
    print(f"Tokens: {usage.get('usage', {}).get('total_tokens', 'N/A')}")
    print(f"Cost: {usage.get('cost', 'N/A')}")
