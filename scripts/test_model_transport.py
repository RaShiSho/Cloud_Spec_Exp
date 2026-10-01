"""Run in each baseline environment; all HTTP requests stay in MockTransport."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_transport import bind_litellm, bind_openai, completion_parameters
from profile_test_support import test_profile
from model_profiles import ConfigError, ROOT

HAS_OPENAI = importlib.util.find_spec("openai") is not None


class TransportParameterTests(unittest.TestCase):
    def test_null_temperature_and_token_limit_parameter(self):
        profile = test_profile(temperature=None, token_limit_parameter="max_completion_tokens")
        params = completion_parameters(profile, {"model": "wrong", "temperature": 0.8, "max_tokens": 10, "max_completion_tokens": 20, "extra_body": {"temperature": 0.9, "model": "wrong-again", "stream_options": {"include_usage": True}}})
        self.assertEqual(params["model"], "test-model")
        self.assertEqual(params["max_completion_tokens"], 4321)
        self.assertNotIn("max_tokens", params)
        self.assertNotIn("temperature", params)
        self.assertNotIn("model", params["extra_body"])
        self.assertNotIn("temperature", params["extra_body"])
        self.assertTrue(params["extra_body"]["stream_options"]["include_usage"])

    def test_litellm_route_and_key_are_explicit_for_sync_and_async(self):
        calls = []

        def completion(**kwargs):
            calls.append(kwargs)

        async def acompletion(**kwargs):
            calls.append(kwargs)

        sdk = types.SimpleNamespace(completion=completion, acompletion=acompletion)
        profile = test_profile()
        bind_litellm(profile, sdk)
        sdk.completion(model="other/provider", messages=[], api_base="http://wrong", api_key="wrong", drop_params=True)
        asyncio.run(sdk.acompletion(model="other/provider", messages=[]))
        for call in calls:
            self.assertEqual(call["model"], "openai/test-model")
            self.assertEqual(call["api_base"], profile.settings["base_url"])
            self.assertEqual(call["api_key"], profile.api_key)
            self.assertEqual(call["temperature"], profile.settings["temperature"])
            self.assertEqual(call["max_tokens"], 4321)
            self.assertFalse(call["drop_params"])


@unittest.skipUnless(HAS_OPENAI, "Run this test in a baseline environment with its pinned OpenAI SDK")
class InstalledSDKTests(unittest.TestCase):
    def trace_context(self, stack, path, profile):
        import openai
        if not hasattr(openai, "OpenAI"):
            self.skipTest("HTTP attempt tracing requires the modern OpenAI SDK")
        stack.enter_context(mock.patch.dict(os.environ, {"OCI_MODEL_EVENT_LOG": str(path)}))
        for cls in (openai.OpenAI, openai.AsyncOpenAI):
            for method in ("__init__", "_prepare_options"):
                stack.enter_context(mock.patch.object(cls, method, getattr(cls, method)))
        bind_openai(profile, openai)

    def test_http_trace_observes_sdk_retry_without_changing_response(self):
        import httpx
        import openai
        profile = test_profile()
        calls = []
        prompt = "private request text must not appear in diagnostics"

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(503, json={"error": {"message": "retry me"}}, headers={"retry-after-ms": "1"})
            return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": "test-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}, headers={"x-request-id": "upstream-request", "set-cookie": "private-cookie"})

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / "events.jsonl"
            self.trace_context(stack, path, profile)
            with httpx.Client(transport=httpx.MockTransport(handler)) as http:
                with openai.OpenAI(http_client=http, timeout=17, max_retries=1) as client:
                    response = client.chat.completions.create(model="wrong", messages=[{"role": "user", "content": prompt}])
                    self.assertEqual(response.choices[0].message.content, "ok")
                    self.assertEqual(client.timeout, 17)
                    self.assertEqual(client.max_retries, 1)
            text = path.read_text()
            rows = [json.loads(line) for line in text.splitlines()]
        starts = [row for row in rows if row["event"] == "model_http_request_started"]
        headers = [row for row in rows if row["event"] == "model_http_response_headers"]
        finishes = [row for row in rows if row["event"] == "model_http_request_finished"]
        self.assertEqual(len(calls), 2)
        self.assertEqual([row["attempt"] for row in starts], [1, 2])
        self.assertEqual([row["sdk_retry_count"] for row in starts], ["0", "1"])
        self.assertTrue(all(row["timeout"]["read"] == 17 for row in starts))
        self.assertEqual([row["status_code"] for row in headers], [503, 200])
        self.assertEqual(headers[-1]["headers"]["x-request-id"], "upstream-request")
        self.assertTrue(all(row["body_read"] for row in finishes))
        self.assertEqual(starts[-1]["request_id"], headers[-1]["request_id"])
        self.assertEqual(starts[-1]["request_id"], finishes[-1]["request_id"])
        self.assertNotEqual(starts[0]["request_id"], starts[1]["request_id"])
        for sensitive in (prompt, profile.api_key, "private-cookie", "retry me"):
            self.assertNotIn(sensitive, text)

    def test_http_trace_preserves_failure_and_records_nested_cause_after_headers(self):
        import httpcore
        import httpx
        import openai
        profile = test_profile()

        class BrokenBody(httpx.SyncByteStream):
            def __iter__(self):
                yield b"partial response"
                try:
                    raise httpcore.ReadError("upstream closed " + profile.api_key)
                except httpcore.ReadError as error:
                    raise httpx.ReadError("response read failed") from error

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / "events.jsonl"
            self.trace_context(stack, path, profile)
            with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenBody()))) as http:
                with openai.OpenAI(http_client=http, max_retries=0) as client:
                    with self.assertRaises(openai.APIConnectionError) as caught:
                        client.chat.completions.create(model="wrong", messages=[])
                    self.assertIsInstance(caught.exception.__cause__, httpx.ReadError)
            text = path.read_text()
            rows = [json.loads(line) for line in text.splitlines()]
        events = [row["event"] for row in rows]
        self.assertLess(events.index("model_http_response_headers"), events.index("model_http_request_failed"))
        failure = next(row for row in rows if row["event"] == "model_http_request_failed")
        self.assertEqual([item["type"] for item in failure["exception_chain"]], ["httpx.ReadError", "httpcore.ReadError"])
        self.assertIn("<redacted>", failure["exception_chain"][1]["message"])
        self.assertNotIn(profile.api_key, text)
        self.assertNotIn("partial response", text)
        self.assertNotIn("model_http_request_finished", events)

    def test_async_http_trace_preserves_timeout_exception_before_headers(self):
        import httpx
        import openai
        profile = test_profile()

        def handler(request):
            raise httpx.ReadTimeout("waiting for response headers", request=request)

        async def request():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                async with openai.AsyncOpenAI(http_client=http, max_retries=0) as client:
                    client._platform = "Linux"
                    with self.assertRaises(openai.APITimeoutError):
                        await client.chat.completions.create(model="wrong", messages=[])

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / "events.jsonl"
            self.trace_context(stack, path, profile)
            asyncio.run(request())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        events = [row["event"] for row in rows]
        self.assertNotIn("model_http_response_headers", events)
        failure = next(row for row in rows if row["event"] == "model_http_request_failed")
        self.assertEqual(failure["exception_chain"][0]["type"], "httpx.ReadTimeout")

    def test_final_http_request_uses_profile(self):
        self.check_profile(test_profile())

    def test_final_http_request_omits_temperature_and_uses_completion_limit(self):
        self.check_profile(test_profile(temperature=None, token_limit_parameter="max_completion_tokens"))

    def check_profile(self, profile):
        import openai
        captured = []
        reply = {"id": "offline", "object": "chat.completion", "created": 0, "model": "test-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}))
            if not hasattr(openai, "OpenAI"):
                from openai.api_requestor import APIRequestor

                def request(self, method, url, params=None, **kwargs):
                    captured.append((self.api_base + url, self.api_key, params))
                    return reply, False, self.api_key

                stack.enter_context(mock.patch.object(APIRequestor, "request", request))
                stack.enter_context(mock.patch.object(openai.ChatCompletion, "create", openai.ChatCompletion.create))
                for name in ("Completion", "Embedding"):
                    cls = getattr(openai, name)
                    stack.enter_context(mock.patch.object(cls, "create", cls.create))
                bind_openai(profile, openai)
                openai.ChatCompletion.create(model="wrong", api_key="wrong", api_base="https://wrong.example", temperature=0.9, max_tokens=1, messages=[])
                with self.assertRaises(ConfigError):
                    openai.Embedding.create(model="unconfigured", input="example")
            else:
                import httpx

                def handler(request):
                    captured.append((str(request.url), request.headers["Authorization"].removeprefix("Bearer "), json.loads(request.content)))
                    return httpx.Response(200, json=reply)

                for cls in (openai.OpenAI, openai.AsyncOpenAI):
                    for method in ("__init__", "_prepare_options"):
                        stack.enter_context(mock.patch.object(cls, method, getattr(cls, method)))
                bind_openai(profile, openai)
                with httpx.Client(transport=httpx.MockTransport(handler)) as http:
                    client = openai.OpenAI(base_url="https://wrong.example", api_key="wrong", http_client=http)
                    response = client.chat.completions.create(model="wrong", messages=[], temperature=0.9, max_tokens=1, extra_body={"model": "wrong-again", "temperature": 0.7})
                    self.assertEqual(response.choices[0].message.content, "ok")
                    with self.assertRaises(ConfigError):
                        client.embeddings.create(model="unconfigured", input="example")

                async def asynchronous():
                    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                        client = openai.AsyncOpenAI(base_url="https://wrong.example", api_key="wrong", http_client=http)
                        # Platform-header discovery starts a worker thread in
                        # newer SDKs; it is unrelated to model routing and can
                        # stall event-loop shutdown in restricted test hosts.
                        client._platform = "Linux"
                        await client.chat.completions.create(model="wrong", messages=[], temperature=0.9, max_tokens=1)

                asyncio.run(asynchronous())
        self.assertTrue(captured)
        for url, key, body in captured:
            self.assertEqual(url, profile.settings["base_url"] + "/chat/completions")
            self.assertEqual(key, profile.api_key)
            self.assertEqual(body["model"], profile.settings["model"])
            if profile.settings["temperature"] is None:
                self.assertNotIn("temperature", body)
            else:
                self.assertEqual(body["temperature"], profile.settings["temperature"])
            parameter = profile.settings["token_limit_parameter"]
            self.assertEqual(body[parameter], profile.settings["max_tokens"])
            self.assertNotIn("max_tokens" if parameter == "max_completion_tokens" else "max_completion_tokens", body)

    @unittest.skipUnless(importlib.util.find_spec("langchain_openai"), "Requires the PatchAgent environment")
    def test_patchagent_langchain_uses_chat_protocol_with_profile(self):
        import httpx
        import openai
        from langchain_openai import ChatOpenAI
        spec = importlib.util.spec_from_file_location("patchagent_profile_test", ROOT / "baselines" / "patchagent" / "launch.py")
        launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launch)
        profile = test_profile(model="gpt-5.5", temperature=None, token_limit_parameter="max_completion_tokens")
        captured = []

        def handler(request):
            captured.append((str(request.url), json.loads(request.content)))
            return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": "gpt-5.5", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}))
            for cls in (openai.OpenAI, openai.AsyncOpenAI):
                for method in ("__init__", "_prepare_options"):
                    stack.enter_context(mock.patch.object(cls, method, getattr(cls, method)))
            bind_openai(profile, openai)
            with httpx.Client(transport=httpx.MockTransport(handler)) as http:
                llm = launch.profile_chat_model(profile, ChatOpenAI, model="wrong", temperature=0.8, http_client=http)
                self.assertEqual(llm.invoke("hello").content, "ok")
        self.assertEqual(captured[0][0], profile.settings["base_url"] + "/chat/completions")
        self.assertEqual(captured[0][1]["model"], "gpt-5.5")
        self.assertEqual(captured[0][1]["max_completion_tokens"], 4321)
        self.assertNotIn("temperature", captured[0][1])


if __name__ == "__main__":
    unittest.main()
