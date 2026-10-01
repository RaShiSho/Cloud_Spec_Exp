"""Bind upstream clients to the selected profile, before importing any agents.

Some baselines hard-code sampling parameters or construct a new client at each
step. These small SDK adapters apply the experiment's declared parameters to
every chat-completion request, including auxiliary repair/summarization calls.
"""
from __future__ import annotations

import functools
import os
from typing import Any

from model_profiles import ConfigError, ResolvedProfile
from experiment_trace import trace_model_request


def completion_parameters(profile: ResolvedProfile, kwargs: dict[str, Any]) -> dict[str, Any]:
    result = dict(kwargs)
    settings = profile.settings
    result["model"] = settings["model"]
    for key in ("temperature", "max_tokens", "max_completion_tokens"):
        result.pop(key, None)
    if settings["temperature"] is not None:
        result["temperature"] = settings["temperature"]
    result[settings["token_limit_parameter"]] = settings["max_tokens"]
    # extra_body is merged after the normal request arguments by the SDK.
    if isinstance(result.get("extra_body"), dict):
        result["extra_body"] = {key: value for key, value in result["extra_body"].items() if key not in {"model", "temperature", "max_tokens", "max_completion_tokens"}}
    return result


def bind_openai(profile: ResolvedProfile, sdk: Any = None) -> None:
    if sdk is None:
        import openai as sdk
    settings = profile.settings
    os.environ["OPENAI_API_KEY"] = profile.api_key
    os.environ["OPENAI_BASE_URL"] = settings["base_url"]
    os.environ["OPENAI_API_BASE_URL"] = settings["base_url"]
    if not hasattr(sdk, "OpenAI"):
        # RepairAgent pins openai 0.27.x.
        sdk.api_key = profile.api_key
        sdk.api_base = settings["base_url"]
        original = sdk.ChatCompletion.create

        @functools.wraps(original)
        def create(*args: Any, **kwargs: Any) -> Any:
            params = completion_parameters(profile, kwargs)
            params.update(api_key=profile.api_key, api_base=settings["base_url"])
            trace_model_request(settings, params)
            return original(*args, **params)

        sdk.ChatCompletion.create = create

        def unsupported_request(*args: Any, **kwargs: Any) -> Any:
            raise ConfigError("The selected profile supports chat completions only; an unconfigured model API was requested")

        for name in ("Completion", "Embedding"):
            if hasattr(sdk, name):
                getattr(sdk, name).create = unsupported_request
        return

    for client_name in ("OpenAI", "AsyncOpenAI"):
        client_class = getattr(sdk, client_name)
        original_init = client_class.__init__

        def make_init(original: Any) -> Any:
            @functools.wraps(original)
            def initialize(self: Any, *args: Any, **kwargs: Any) -> None:
                kwargs.update(api_key=profile.api_key, base_url=settings["base_url"])
                original(self, *args, **kwargs)
            return initialize

        client_class.__init__ = make_init(original_init)
        # Apply after LiteLLM's parameter conversions, and merge extra_json here
        # so the SDK cannot later restore a conflicting extra_body value.
        original_prepare = client_class._prepare_options

        def prepare_options(client: Any, options: Any) -> None:
            body = {**(options.json_data or {}), **(options.extra_json or {})}
            if str(options.url).rstrip("/").endswith("/chat/completions"):
                options.json_data = completion_parameters(profile, body)
                options.extra_json = None
                client.api_key = profile.api_key
                client.base_url = settings["base_url"]
                trace_model_request(settings, options.json_data)
            elif "model" in body:
                raise ConfigError("The selected profile supports chat completions only; an unconfigured model API was requested")

        def make_prepare(original: Any) -> Any:
            if client_name == "AsyncOpenAI":
                @functools.wraps(original)
                async def prepare_async(self: Any, options: Any) -> Any:
                    prepare_options(self, options)
                    return await original(self, options)
                return prepare_async

            @functools.wraps(original)
            def prepare(self: Any, options: Any) -> Any:
                prepare_options(self, options)
                return original(self, options)
            return prepare

        client_class._prepare_options = make_prepare(original_prepare)


def bind_litellm(profile: ResolvedProfile, sdk: Any = None) -> None:
    if sdk is None:
        import litellm as sdk

    def parameters(kwargs: dict[str, Any]) -> dict[str, Any]:
        params = completion_parameters(profile, kwargs)
        params.update(model="openai/" + profile.settings["model"], custom_llm_provider="openai", api_base=profile.settings["base_url"], api_key=profile.api_key, drop_params=False)
        return params

    original = sdk.completion

    @functools.wraps(original)
    def completion(*args: Any, **kwargs: Any) -> Any:
        if args:
            kwargs["model"] = args[0]
            args = args[1:]
        return original(*args, **parameters(kwargs))

    sdk.completion = completion
    original_async = sdk.acompletion

    @functools.wraps(original_async)
    async def acompletion(*args: Any, **kwargs: Any) -> Any:
        if args:
            kwargs["model"] = args[0]
            args = args[1:]
        return await original_async(*args, **parameters(kwargs))

    sdk.acompletion = acompletion
