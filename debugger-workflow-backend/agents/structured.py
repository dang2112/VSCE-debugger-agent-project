"""Provider-backed structured generation shared by RCA and patch generation."""
import json
from google.genai import types
from agents.direct_debugger import SYSTEM_PROMPT
from agents.llm_backend import STRUCTURED_MODEL as MODEL, client, generate_content


def generate_structured(payload: dict, schema, instruction: str):
    response = generate_content(
        model=MODEL, contents=json.dumps(payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT + '\n' + instruction,
            response_mime_type='application/json', response_json_schema=schema.model_json_schema(),
            temperature=0.1, max_output_tokens=8192,
        ),
    )
    if not response.text or not response.text.strip():
        raise ValueError('Model returned no structured result')
    return schema.model_validate_json(response.text)
