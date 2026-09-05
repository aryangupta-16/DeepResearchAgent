"""Unit tests for the LLM provider factory."""

import pytest

import app.llm.factory as factory
from app.common.exceptions import LLMNotConfiguredError
from app.config.settings import Settings
from app.llm.providers.openai import OpenAIProvider


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "llm_provider": "",
        "llm_model": "",
        "llm_timeout": 60.0,
        "openai_base_url": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "google_api_key": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_no_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings())
    with pytest.raises(LLMNotConfiguredError):
        factory.get_llm_provider()


def test_unsupported_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(llm_provider="gpt-x"))
    with pytest.raises(LLMNotConfiguredError):
        factory.get_llm_provider()


def test_unimplemented_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory, "get_settings", lambda: _settings(llm_provider="anthropic", anthropic_api_key="k")
    )
    with pytest.raises(LLMNotConfiguredError):
        factory.get_llm_provider()


def test_openai_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(llm_provider="openai"))
    with pytest.raises(LLMNotConfiguredError):
        factory.get_llm_provider()


def test_explicit_provider_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings default to no provider, but the explicit arg names openai.
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(openai_api_key="sk-test"))
    provider = factory.get_llm_provider("openai")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_openai_success_uses_model_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _settings(
            llm_provider="openai",
            llm_model="gpt-4.1-mini",
            openai_api_key="sk-test",
        ),
    )
    provider = factory.get_llm_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4.1-mini"
    assert provider.api_key == "sk-test"