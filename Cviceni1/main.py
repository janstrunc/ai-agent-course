import json
import os
from dotenv import load_dotenv
import anthropic
import yfinance as yf

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


from typing import Callable

TOOL_REGISTRY: dict[str, Callable] = {}
TOOLS: list[dict] = []


def register_tool(name: str, description: str, input_schema: dict):
    def decorator(func):
        TOOL_REGISTRY[name] = func
        TOOLS.append({
            "name": name,
            "description": description,
            "input_schema": input_schema,
        })
        return func
    return decorator


@register_tool(
    name="get_stock_price",
    description="Get the current stock price for a ticker symbol.",
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Ticker symbol, e.g. AAPL",
            }
        },
        "required": ["ticker"],
    },
)
def get_stock_price(ticker: str):
    ticker = ticker.strip().upper()
    try:
        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        currency = info.get("currency")
        name = info.get("shortName") or info.get("longName")
        if price is None:
            return {"ticker": ticker, "error": "Price not found"}
        return {
            "ticker": ticker,
            "name": name,
            "price": price,
            "currency": currency,
        }
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc)}


def ask_llm(question: str, model: str = "claude-sonnet-4-5-20250929"):
    messages = [
        {"role": "user", "content": question},
    ]

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system="Jsi uzitecny asistent.",
        messages=messages,
        tools=TOOLS,
    )

    if response.stop_reason != "tool_use":
        return response.content[0].text

    # Process tool calls
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            func = TOOL_REGISTRY[block.name]
            function_result = func(**block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(function_result),
                }
            )

    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})

    second_response = client.messages.create(
        model=model,
        max_tokens=1024,
        system="Jsi uzitecny asistent.",
        messages=messages,
        tools=TOOLS,
    )

    return second_response.content[0].text


if __name__ == "__main__":
    user_question = "Jaka je aktualni cena akcie AAPL?"
    answer = ask_llm(user_question)
    print(answer)