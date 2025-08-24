import os
import json
from typing import Any, Dict
from .models import AppConfig
from .cache import get_llm_cached, set_llm_cached


def parse_free_text_to_config(prompt: str, llm_config=None, cache_enabled: bool = True, cache_ttl_hours: int = 24) -> Dict[str, Any]:
    """
    Parses the free-text 'prompt' into the strict schema using OpenAI structured output.
    If OpenAI isn't configured, returns an empty dict.
    Supports caching of LLM responses to reduce API calls and costs.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # No LLM configured; skip structured parsing step gracefully.
        return {}
    
    # Use config model or fallback to environment/defaults
    if llm_config:
        model = llm_config.model
        max_tokens = llm_config.max_tokens
        temperature = llm_config.temperature
    else:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        max_tokens = None
        temperature = 0.0

    # Deferred import so code runs without the package if not installed.
    from openai import OpenAI

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

    # Check cache first if enabled
    if cache_enabled:
        cached_response = get_llm_cached(user, system, cache_ttl_hours)
        if cached_response:
            return cached_response

    # Make LLM call if not cached
    client = OpenAI(api_key=api_key)
    
    # Determine if model supports JSON response format
    json_models = {
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-1106-preview", 
        "gpt-4-0125-preview", "gpt-3.5-turbo-1106", "gpt-3.5-turbo-0125"
    }
    supports_json_mode = any(json_model in model.lower() for json_model in json_models)
    
    # Build request parameters
    request_params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    
    # Add optional parameters if specified
    if max_tokens:
        request_params["max_tokens"] = max_tokens
    
    # Add JSON response format only if supported
    if supports_json_mode:
        request_params["response_format"] = {"type": "json_object"}
    else:
        # For older models, add explicit JSON instruction
        request_params["messages"][0]["content"] += "\n\nIMPORTANT: You MUST respond with valid JSON only."
    
    resp = client.chat.completions.create(**request_params)
    content = resp.choices[0].message.content
    
    # Extract JSON if wrapped in markdown code blocks
    if content.strip().startswith("```"):
        # Remove markdown code block formatting
        lines = content.strip().split('\n')
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        content = '\n'.join(lines)
    
    data = json.loads(content)
    
    # Validate against our Pydantic schema and return normalized dict
    llm_obj = AppConfig.model_validate(data)
    out = llm_obj.model_dump(exclude_none=True)
    
    # Cache the result if enabled
    if cache_enabled:
        set_llm_cached(user, system, out)
        
    return out
