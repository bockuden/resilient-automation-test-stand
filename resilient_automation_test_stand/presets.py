"""Validated scenario presets loaded from TOML configuration."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


Scenario = Literal[
    "success",
    "transient",
    "permanent",
    "slow",
    "resume",
    "dom-change",
    "duplicates",
]


class ScenarioDefaults(BaseModel):
    """Defaults that a request may override with query parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario: Scenario = "success"
    protected: bool = False
    total_pages: int = Field(default=4, ge=1, le=20)
    fail_for: int = Field(default=2, ge=0, le=10)
    failure_delay_ms: int = Field(default=0, ge=0, le=30_000)
    delay_ms: int = Field(default=1500, ge=0, le=30_000)
    fail_page: int = Field(default=3, ge=1, le=20)


class PresetDocument(BaseModel):
    """Top-level shape of a scenario TOML file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    presets: dict[str, ScenarioDefaults] = Field(min_length=1)

    @field_validator("presets")
    @classmethod
    def validate_preset_names(
        cls,
        presets: dict[str, ScenarioDefaults],
    ) -> dict[str, ScenarioDefaults]:
        invalid = [
            name
            for name in presets
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name) is None
        ]
        if invalid:
            raise ValueError(
                "preset names must use lowercase letters, digits, '.', '_', or '-': "
                + ", ".join(sorted(invalid))
            )
        return presets


class PresetConfigError(ValueError):
    """Raised when a preset document cannot be read or validated."""


def load_preset_document(path: Path) -> PresetDocument:
    try:
        with path.open("rb") as config_file:
            raw_document = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PresetConfigError(f"cannot read preset config '{path}': {error}") from error

    try:
        return PresetDocument.model_validate(raw_document)
    except ValidationError as error:
        raise PresetConfigError(f"invalid preset config '{path}': {error}") from error


def preset_url(
    preset_name: str,
    preset: ScenarioDefaults,
    base_url: str,
) -> str:
    parts = urlsplit(base_url)
    query = list(parse_qsl(parts.query, keep_blank_values=True))
    values = {"run_id": preset_name, **preset.model_dump()}
    query.extend(
        (name, str(value).lower() if isinstance(value, bool) else str(value))
        for name, value in values.items()
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
