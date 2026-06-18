import pytest

from forgelab.sdk.prompts import few_shot, system_prompt
from forgelab.sdk.validation import validate_llm_output


@pytest.mark.parametrize("domain", ["hardware", "threed", "mechanical"])
def test_system_prompt_nonempty_and_names_domain(domain):
    prompt = system_prompt(domain)
    assert isinstance(prompt, str) and prompt.strip()
    assert domain in prompt


@pytest.mark.parametrize("domain", ["hardware", "threed", "mechanical"])
def test_few_shot_examples_are_valid(domain):
    examples = few_shot(domain)
    assert examples, "expected at least one few-shot example"
    for user, assistant in examples:
        assert isinstance(user, str) and user.strip()
        document = validate_llm_output(assistant, domain=domain)
        assert document.domain.value == domain


@pytest.mark.parametrize("domain", ["hardware", "threed", "mechanical"])
def test_system_prompt_instructs_single_pass_build(domain):
    prompt = system_prompt(domain).lower()
    # The agent should assemble the whole document then validate once, rather
    # than iterating with repeated validate_document calls.
    assert "validate_document" in prompt
    assert "once" in prompt
    assert "single pass" in prompt or "one pass" in prompt


def test_system_prompt_unknown_domain_raises():
    with pytest.raises(KeyError):
        system_prompt("nope")


def test_few_shot_unknown_domain_raises():
    with pytest.raises(KeyError):
        few_shot("nope")


def test_system_prompt_states_installed_spec_version():
    from forgelab.spec import SPEC_VERSION

    assert SPEC_VERSION in system_prompt("threed")


def test_few_shot_version_comes_from_library_not_file(monkeypatch):
    import json

    from forgelab.sdk import prompts

    monkeypatch.setattr(prompts, "SPEC_VERSION", "9.9.9")
    _, assistant = prompts.few_shot("threed")[0]
    assert json.loads(assistant)["forgelab_version"] == "9.9.9"
