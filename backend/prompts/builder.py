from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, StringConstraints

_TEMPLATE_PATH = Path(__file__).with_name("system.md")

_PERSONA_MARKER = "{{persona}}"
_SCOPE_MARKER = "{{scope}}"
_CAPABILITY_RULES_MARKER = "{{capability_rules}}"
_OUTPUT_CONTRACT_MARKER = "{{output_contract}}"

_NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class StoreProfile(BaseModel):
    name: _NonEmptyText
    location: _NonEmptyText
    persona: _NonEmptyText
    scope: _NonEmptyText


def build_system_prompt(
    *,
    store_profile: StoreProfile,
    capability_rules: list[str],
    output_contract: str,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        _PERSONA_MARKER: _persona_text(store_profile),
        _SCOPE_MARKER: store_profile.scope,
        _CAPABILITY_RULES_MARKER: _format_rules(capability_rules),
        _OUTPUT_CONTRACT_MARKER: _required_text(output_contract, "output_contract"),
    }

    prompt = template
    for marker, value in replacements.items():
        if marker not in prompt:
            raise ValueError(f"System prompt template is missing marker {marker!r}.")
        prompt = prompt.replace(marker, value)

    return prompt


def _persona_text(store_profile: StoreProfile) -> str:
    return (
        f"Você é o atendente virtual da {store_profile.name}, "
        f"localizada em {store_profile.location}.\n\n{store_profile.persona}"
    )


def _format_rules(rules: list[str]) -> str:
    formatted = [
        f"- {' '.join(rule.split())}" for rule in rules if rule and rule.strip()
    ]
    if not formatted:
        raise ValueError("capability_rules must contain at least one non-empty rule.")
    return "\n".join(formatted)


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


__all__ = ["StoreProfile", "build_system_prompt"]
