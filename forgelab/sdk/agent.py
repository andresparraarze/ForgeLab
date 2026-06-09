"""ForgeAgent — natural language to a validated ForgeDocument via Claude."""

from typing import Any

from forgelab.core import LLMOutputError
from forgelab.sdk.prompts import system_prompt
from forgelab.sdk.schema import domain_schema
from forgelab.sdk.validation import validate_llm_output
from forgelab.spec import ForgeDocument

_TOOL_NAME = "emit_forgelab"


class ForgeAgent:
    """Wraps the Anthropic API to produce validated ForgeLab documents.

    Example:
        agent = ForgeAgent()
        doc = agent.design("a blinky LED board", domain="hardware")
    """

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-8",
        client: Any | None = None,
        max_tokens: int = 8192,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._client = client
            return
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ForgeAgent requires the Anthropic SDK. Install it with: "
                'pip install "forgelab[agent]"'
            ) from exc
        self._client = anthropic.Anthropic()

    def design(self, prompt: str, *, domain: str) -> ForgeDocument:
        """Turn a natural-language request into a validated ForgeDocument."""
        schema = domain_schema(domain)
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt(domain),
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": f"Emit a valid ForgeLab {domain} document.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return validate_llm_output(block.input, domain=domain)
        raise LLMOutputError("Claude did not return a ForgeLab tool call.")
