from unittest import mock

import pytest
from google.genai import errors

from app import gemini


def api_error(cls, code, status):
    return cls(code, {"error": {"code": code, "message": status.lower(), "status": status}})


OVERLOADED = api_error(errors.ServerError, 503, "UNAVAILABLE")
RATE_LIMITED = api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED")
FORBIDDEN = api_error(errors.ClientError, 403, "PERMISSION_DENIED")


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_model", "primary")
    monkeypatch.setattr(gemini.settings, "gemini_fallback_models", ["fallback-1", "fallback-2"])


def fake_generate(*outcomes):
    calls = []

    def generate(model, **kwargs):
        calls.append(model)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return generate, calls


def test_falls_back_on_transient_errors(models):
    generate, calls = fake_generate(OVERLOADED, RATE_LIMITED, "response")
    with mock.patch.object(gemini.client.models, "generate_content", side_effect=generate):
        assert gemini._generate(["prompt"]) == ("response", "fallback-2")
    assert calls == ["primary", "fallback-1", "fallback-2"]


def test_does_not_fall_back_on_permanent_errors(models):
    generate, calls = fake_generate(FORBIDDEN)
    with mock.patch.object(gemini.client.models, "generate_content", side_effect=generate):
        with pytest.raises(errors.ClientError):
            gemini._generate(["prompt"])
    assert calls == ["primary"]


def test_raises_when_every_model_is_busy(models):
    generate, calls = fake_generate(OVERLOADED, OVERLOADED, OVERLOADED)
    with mock.patch.object(gemini.client.models, "generate_content", side_effect=generate):
        with pytest.raises(errors.ServerError):
            gemini._generate(["prompt"])
    assert len(calls) == 3


@pytest.mark.parametrize("error, transient", [(OVERLOADED, True), (RATE_LIMITED, True), (FORBIDDEN, False),
                                              (ValueError("x"), False)])
def test_is_transient(error, transient):
    assert gemini.is_transient(error) is transient
