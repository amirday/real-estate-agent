import os
import json
from typing import Any, Dict
from .exc import DataValidationError
from .config import AppConfig


def parse_free_text_to_config(prompt: str) -> Dict[str, Any]:
    """
    Parses the free-text 'prompt' into the strict schema using OpenAI structured output.
    If OpenAI isn't configured, returns an empty dict.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        # No LLM configured; skip structured parsing step gracefully.
        return {}

    # Deferred import so code runs without the package if not installed.
    try:
        from openai import OpenAI
    except Exception:
        return {}

    client = OpenAI(api_key=api_key)

    # Build JSON Schema from our Pydantic model
    schema = AppConfig.model_json_schema()

    system = (
        "You are a helpful real estate config parser. "
        "Return ONLY JSON that validates against the provided JSON Schema. "
        "Output must be a single JSON object with any subset of: filters, arv_config, profit_config, deal_screen. "
        "Omit fields you cannot infer; do not hallucinate values."
    )

    user = (
        "Free-text user intent (map into the schema):\n---\n"
        + prompt
        + "\n---\nJSON Schema (draft-07 compatible):\n\n"
        + json.dumps(schema, indent=2)
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        # Validate against our Pydantic schema and return normalized dict
        llm_obj = AppConfig.model_validate(data)
        out = llm_obj.model_dump(exclude_none=True)
        # prune to allowed top-level keys just in case
        allowed = {"filters", "arv_config", "profit_config", "deal_screen"}
        return {k: v for k, v in out.items() if k in allowed}
    except Exception as e:
        # When LLM is configured, any failure to produce valid JSON is fatal
        raise DataValidationError(f"LLM parsing failed: {e}; raw={locals().get('content', '')}")
