"""Provider boundary for debugging agents, preserving existing internal content types."""
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
import httpx

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

DEFAULT_MODELS = {'anthropic': 'claude-sonnet-5-5', 'gemini': 'gemini-3.1-flash-lite'}


class ModelBackendError(RuntimeError):
    pass


def provider_name():
    provider = os.getenv('DEBUGGER_PROVIDER', 'anthropic').strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ModelBackendError('DEBUGGER_PROVIDER must be anthropic or gemini')
    return provider


def model_for(stage):
    common = os.getenv('DEBUGGER_MODEL', '').strip() or DEFAULT_MODELS[provider_name()]
    return (os.getenv(f'DEBUGGER_{stage.upper()}_MODEL', '').strip() or common).removeprefix('models/')


DIRECT_MODEL = model_for('direct')
AGENT_MODEL = model_for('agent')
STRUCTURED_MODEL = model_for('structured')


def _redact(message):
    for name in ('GEMINI_API_KEY', 'ANTHROPIC_API_KEY'):
        key = os.getenv(name, '')
        if key:
            message = message.replace(key, '[redacted]')
    return message[:1800]


def _claude_schema(value):
    """Adapt strict JSON schema; Pydantic still validates the original constraints."""
    if isinstance(value, list):
        return [_claude_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    # Property/definition names are data, not schema keywords.
    out = {}
    constraints = {}
    unsupported = {'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
                   'minLength', 'maxLength', 'maxItems', 'uniqueItems'}
    for key, child in value.items():
        if key in unsupported or (key == 'minItems' and child not in (0, 1)):
            constraints[key] = child
        elif key in ('properties', '$defs', 'definitions'):
            out[key] = {name: _claude_schema(schema) for name, schema in child.items()}
        elif key == 'additionalProperties':
            continue
        else:
            out[key] = _claude_schema(child)
    if constraints:
        out['description'] = (out.get('description', '') + ' Constraints: ' + json.dumps(constraints)).strip()
    if out.get('type') == 'object' or 'properties' in out:
        out['additionalProperties'] = False
    return out


def _claude_messages(contents):
    if isinstance(contents, str):
        return [{'role': 'user', 'content': [{'type': 'text', 'text': contents}]}]
    messages, pending = [], []
    for turn, item in enumerate(contents):
        content = types.Content.model_validate(item) if isinstance(item, dict) else item
        role = 'assistant' if content.role == 'model' else 'user'
        native = next((p.part_metadata.get('anthropic_content') for p in content.parts or []
                       if p.part_metadata and p.part_metadata.get('anthropic_content')), None)
        blocks = []
        for index, part in enumerate(content.parts or []):
            if part.function_call:
                call = part.function_call
                call_id = call.id or f'toolu_{turn}_{index}'
                pending.append((call.name, call_id))
                blocks.append({'type': 'tool_use', 'id': call_id, 'name': call.name, 'input': call.args or {}})
            elif part.function_response:
                response = part.function_response
                match = next((pair for pair in pending if pair[1] == response.id), None) if response.id else next(
                    (pair for pair in pending if pair[0] == response.name), None)
                if match is None:
                    raise ModelBackendError('Cannot match a saved tool response to its call. Start a new debugging session.')
                pending.remove(match)
                block = {'type': 'tool_result', 'tool_use_id': match[1], 'content': json.dumps(response.response, ensure_ascii=False)}
                if 'error' in (response.response or {}):
                    block['is_error'] = True
                blocks.append(block)
            elif part.text and not part.thought:
                blocks.append({'type': 'text', 'text': part.text})
        if native and role == 'assistant':
            blocks = native  # Preserve Claude thinking signatures/tool blocks unchanged.
        if not blocks:
            continue
        if role == 'user':
            blocks = [b for b in blocks if b['type'] == 'tool_result'] + [b for b in blocks if b['type'] != 'tool_result']
        if messages and messages[-1]['role'] == role:
            messages[-1]['content'].extend(blocks)
        else:
            messages.append({'role': role, 'content': blocks})
    if pending:
        raise ModelBackendError('The model history contains unanswered tool calls. Complete their results before continuing.')
    return messages


def _anthropic_generate(model, contents, config):
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not key:
        raise ModelBackendError('Set ANTHROPIC_API_KEY in the backend .env, then restart the backend. A Gemini key cannot authenticate to Anthropic.')
    if not model.startswith('claude-'):
        raise ModelBackendError('Anthropic requires a Claude model ID. Set DEBUGGER_MODEL=claude-sonnet-5-5 or another accessible Claude model.')
    body = {'model': model, 'max_tokens': config.max_output_tokens or 8192,
            'messages': _claude_messages(contents)}
    if config.system_instruction:
        body['system'] = config.system_instruction
    # Sonnet 5.5 rejects temperature/top_p/top_k. Leave sampling provider-native.
    if config.tools:
        declarations = [declaration for tool in config.tools for declaration in tool.function_declarations or []]
        body['tools'] = [{'name': d.name, 'description': d.description or '',
                          'input_schema': d.parameters_json_schema or d.parameters.model_dump(exclude_none=True)}
                         for d in declarations]
    if config.response_json_schema:
        body['output_config'] = {'format': {'type': 'json_schema', 'schema': _claude_schema(config.response_json_schema)}}
    try:
        with httpx.Client(timeout=120.0, follow_redirects=False) as transport:
            for attempt in range(2):
                response = transport.post('https://api.anthropic.com/v1/messages',
                    headers={'x-api-key': key, 'anthropic-version': '2023-06-01'}, json=body)
                if response.status_code in (500, 502, 503, 504, 529) and attempt == 0:
                    time.sleep(.5)
                    continue
                break
    except httpx.HTTPError as exc:
        raise ModelBackendError('Anthropic connection failed: ' + _redact(str(exc))) from None
    try:
        payload = response.json()
    except ValueError:
        raise ModelBackendError(f'Anthropic returned non-JSON content (HTTP {response.status_code})') from None
    if response.status_code >= 400:
        detail = _redact(str(payload.get('error', {}).get('message', 'Request failed')))
        raise ModelBackendError(f'Anthropic model {model} failed (HTTP {response.status_code}): {detail}')
    if payload.get('stop_reason') in ('max_tokens', 'refusal'):
        raise ModelBackendError('Anthropic stopped without a complete answer: ' + payload['stop_reason'])
    blocks = payload.get('content', [])
    parts = []
    for block in blocks:
        if block['type'] == 'text':
            parts.append(types.Part(text=block['text']))
        elif block['type'] == 'tool_use':
            parts.append(types.Part(function_call=types.FunctionCall(id=block['id'], name=block['name'], args=block['input'])))
    if not parts:
        raise ModelBackendError('Anthropic returned no usable text or tool call')
    if config.tools:
        parts[0].part_metadata = {'anthropic_content': blocks}
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=parts))])


class _Client:
    """Keep the existing client.models.generate_content seam for callers/tests."""
    def __init__(self):
        self.models = self
        self._gemini = None

    def generate_content(self, *, model, contents, config):
        if provider_name() == 'anthropic':
            return _anthropic_generate(model, contents, config)
        if not os.getenv('GEMINI_API_KEY'):
            raise ModelBackendError('Set GEMINI_API_KEY to use DEBUGGER_PROVIDER=gemini')
        if self._gemini is None:
            self._gemini = genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options=types.HttpOptions(
                timeout=120000, retry_options=types.HttpRetryOptions(attempts=2, http_status_codes=[500, 502, 503, 504])))
        return self._gemini.models.generate_content(model=model, contents=contents, config=config)


client = _Client()


def generate_content(*, model, contents, config):
    try:
        return client.models.generate_content(model=model, contents=contents, config=config)
    except errors.APIError as exc:
        raise ModelBackendError(f'Gemini model {model} failed (HTTP {exc.code}): ' + _redact(str(exc.message))) from None
