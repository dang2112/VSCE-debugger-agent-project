"""Transport-only regression tests; no credentials or external network required."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from google.genai import types
from agents import llm_backend as backend
from orchestrator.state import GeneratedPatch

REAL_CLIENT = httpx.Client


class AnthropicBackendTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-only-key', 'DEBUGGER_PROVIDER': 'anthropic'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def transport(self, handler):
        return patch.object(backend.httpx, 'Client', side_effect=lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handler)))

    def test_tool_calls_results_and_native_thinking_blocks_round_trip(self):
        original = [
            {'type': 'thinking', 'thinking': 'Test-only reasoning placeholder', 'signature': 'opaque'},
            {'type': 'tool_use', 'id': 'toolu_123', 'name': 'read_file', 'input': {'path': 'a.py'}},
        ]
        bodies = []
        def handler(request):
            self.assertEqual(request.headers['x-api-key'], 'test-only-key')
            body = json.loads(request.content)
            bodies.append(body)
            if len(bodies) == 1:
                return httpx.Response(200, json={'content': original, 'stop_reason': 'tool_use'})
            return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'Diagnosis'}], 'stop_reason': 'end_turn'})
        history = [types.Content(role='user', parts=[types.Part(text='debug')])]
        config = types.GenerateContentConfig(system_instruction='Debug source', tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name='read_file', parameters_json_schema={'type': 'object', 'properties': {'path': {'type': 'string'}}})])])
        with self.transport(handler):
            first = backend.generate_content(model='claude-sonnet-5-5', contents=history, config=config)
            content = first.candidates[0].content
            content = types.Content.model_validate(content.model_dump(mode='json'))  # Disk checkpoint round trip.
            self.assertEqual(content.parts[0].function_call.id, 'toolu_123')
            history.extend([content, types.Content(role='user', parts=[types.Part(function_response=types.FunctionResponse(
                id='toolu_123', name='read_file', response={'content': 'source'}))])])
            second = backend.generate_content(model='claude-sonnet-5-5', contents=history, config=config)
        self.assertEqual(second.text, 'Diagnosis')
        self.assertEqual(bodies[1]['messages'][1]['content'], original)
        self.assertEqual(bodies[1]['messages'][2]['content'][0]['tool_use_id'], 'toolu_123')
        self.assertEqual(bodies[1]['tools'][0]['name'], 'read_file')

    def test_structured_output_schema_and_sampling_compatibility(self):
        def handler(request):
            body = json.loads(request.content)
            schema = body['output_config']['format']['schema']
            self.assertEqual(body['output_config']['format']['type'], 'json_schema')
            self.assertFalse(schema['additionalProperties'])
            self.assertNotIn('maxLength', schema['properties']['diff'])
            self.assertIn('maxLength', schema['properties']['diff']['description'])
            self.assertFalse(schema['properties']['base_hashes']['additionalProperties'])
            self.assertNotIn('temperature', body)
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"diff":"example"}'}]})
        with self.transport(handler):
            result = backend.generate_content(model='claude-sonnet-5-5', contents='make a patch', config=types.GenerateContentConfig(
                response_json_schema=GeneratedPatch.model_json_schema(), response_mime_type='application/json', temperature=.1))
        self.assertEqual(json.loads(result.text)['diff'], 'example')

    def test_missing_key_is_an_explicit_setup_error(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), patch.object(backend.httpx, 'Client') as client:
            with self.assertRaisesRegex(backend.ModelBackendError, 'Set ANTHROPIC_API_KEY'):
                backend.generate_content(model='claude-sonnet-5-5', contents='hello', config=types.GenerateContentConfig())
            client.assert_not_called()

    def test_auth_errors_are_redacted_and_not_retried(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(401, json={'error': {'message': 'Invalid test-only-key'}})
        with self.transport(handler):
            with self.assertRaises(backend.ModelBackendError) as error:
                backend.generate_content(model='claude-sonnet-5-5', contents='hello', config=types.GenerateContentConfig())
        self.assertEqual(len(requests), 1)
        self.assertNotIn('test-only-key', str(error.exception))
        self.assertIn('[redacted]', str(error.exception))

    def test_transient_overload_is_retried_once(self):
        requests = []
        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(529, json={'error': {'message': 'Overloaded'}})
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'OK'}]})
        with self.transport(handler), patch.object(backend.time, 'sleep'):
            result = backend.generate_content(model='claude-sonnet-5-5', contents='hello', config=types.GenerateContentConfig())
        self.assertEqual(result.text, 'OK')
        self.assertEqual(len(requests), 2)

    def test_truncated_or_refused_answers_do_not_become_success(self):
        for reason in ('max_tokens', 'refusal'):
            with self.subTest(reason=reason), self.transport(lambda request: httpx.Response(200, json={
                'stop_reason': reason, 'content': [{'type': 'text', 'text': 'partial'}]})):
                with self.assertRaisesRegex(backend.ModelBackendError, reason):
                    backend.generate_content(model='claude-sonnet-5-5', contents='hello', config=types.GenerateContentConfig())

    def test_old_gemini_calls_without_ids_receive_matching_anthropic_ids(self):
        messages = backend._claude_messages([
            types.Content(role='user', parts=[types.Part(text='debug')]),
            types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name='read_file', args={'path': 'a.py'}))]),
            types.Content(role='user', parts=[types.Part(function_response=types.FunctionResponse(name='read_file', response={'ok': True}))]),
        ])
        self.assertEqual(messages[1]['content'][0]['id'], messages[2]['content'][0]['tool_use_id'])

    def test_stage_selection_defaults_to_claude_and_can_be_overridden(self):
        with patch.dict(os.environ, {'DEBUGGER_MODEL': '', 'DEBUGGER_AGENT_MODEL': '', 'DEBUGGER_STRUCTURED_MODEL': 'claude-sonnet-4-6'}):
            self.assertEqual(backend.model_for('agent'), 'claude-sonnet-5-5')
            self.assertEqual(backend.model_for('structured'), 'claude-sonnet-4-6')


if __name__ == '__main__':
    unittest.main()
