"""Validated scenario presets loaded from TOML configuration."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator

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


class ResolvedAuth(BaseModel):
    """Credentials resolved once from config and the process environment."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    username: str = Field(default="demo", repr=False)
    password: str = Field(default="automation", repr=False)

    @field_validator("username", "password")
    @classmethod
    def require_non_empty_credential(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resolved credentials must not be empty")
        return value


class AuthConfig(BaseModel):
    """Optional global authentication settings from a TOML document."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    username: str | None = Field(default=None, repr=False)
    password: str | None = Field(default=None, repr=False)
    username_env: str | None = Field(default=None, repr=False)
    password_env: str | None = Field(default=None, repr=False)

    @field_validator("username", "password")
    @classmethod
    def validate_literal_credential(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("username_env", "password_env")
    @classmethod
    def validate_environment_variable_name(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("must be a valid environment variable name")
        return value

    def resolve(self, environ: Mapping[str, str] | None = None) -> ResolvedAuth:
        """Resolve environment overrides without retaining a live environment lookup."""

        source = os.environ if environ is None else environ

        def resolve_one(
            literal: str | None,
            environment_name: str | None,
            default: str,
        ) -> str:
            if environment_name is not None and environment_name in source:
                value = source[environment_name]
                if not value.strip():
                    raise ValueError(
                        f"environment variable {environment_name!r} resolved to an empty credential"
                    )
                return value
            return literal if literal is not None else default

        return ResolvedAuth(
            username=resolve_one(self.username, self.username_env, "demo"),
            password=resolve_one(self.password, self.password_env, "automation"),
        )


class PresetDocument(BaseModel):
    """Top-level shape of a scenario TOML file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    auth: AuthConfig = Field(default_factory=AuthConfig)
    presets: dict[str, ScenarioDefaults] = Field(min_length=1)
    _resolved_auth: ResolvedAuth = PrivateAttr(default_factory=ResolvedAuth)

    @property
    def resolved_auth(self) -> ResolvedAuth:
        """Credentials resolved at load time for server runtime configuration."""

        return self._resolved_auth

    @field_validator("presets")
    @classmethod
    def validate_preset_names(
        cls,
        presets: dict[str, ScenarioDefaults],
    ) -> dict[str, ScenarioDefaults]:
        invalid = [name for name in presets if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name) is None]
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
        document = PresetDocument.model_validate(raw_document)
        object.__setattr__(document, "_resolved_auth", document.auth.resolve())
        return document
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False)
        )
        raise PresetConfigError(f"invalid preset config '{path}': {details}") from error
    except ValueError as error:
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
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
