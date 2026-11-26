import os
import re
from typing import Literal
from urllib.parse import urlsplit
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, PositiveInt, model_validator

ROOT = Path(__file__).resolve().parents[1]


class Rates(BaseModel):
    provider: Literal["openai", "glm", "gemini"] = "openai"
    context_limit: int = Field(default=131072, gt=0)
    input: Decimal = Field(gt=0)
    cache_write: Decimal | None = Field(ge=0)
    cache_read: Decimal | None = Field(ge=0)
    output: Decimal = Field(gt=0)


class Settings(BaseModel):
    default_model: str
    reasoning_effort: str = Field(pattern="^(low|medium|high)$")
    max_output_tokens: int = Field(ge=128, le=32000)
    max_budget_usd: Decimal = Field(gt=0, le=1)
    models: dict[str, Rates]

    @model_validator(mode="after")
    def configured_price(self):
        rates = self.models[self.default_model]
        if rates.cache_read is None or rates.cache_write is None:
            raise ValueError("启用模型前须补齐已核实的缓存单价")
        return self


class Viewport(BaseModel):
    width: PositiveInt = Field(le=4096)
    height: PositiveInt = Field(le=4096)


class Game(BaseModel):
    id: str
    url: str
    allowed_hosts: list[str]
    viewport: Viewport
    adapter: str
    release_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Persona(BaseModel):
    id: str
    name: str
    account_alias: str
    test_account: str = Field(pattern=r"^ai_[a-z0-9_]+$")
    profile: str
    initial_patience: int = Field(ge=0, le=10)
    quit_threshold: int = Field(ge=1, le=10)
    dimensions: list[str]


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load(game_id, persona_id, overrides):
    if not all(re.fullmatch("[a-z][a-z0-9_]*", s) for s in [game_id, persona_id]):
        raise ValueError("无效配置名")
    base = Path(os.getenv("PLAYTEST_GAMES_DIR", ROOT / "games")) / game_id
    settings = read_yaml(Path(os.getenv("PLAYTEST_MODELS_FILE", ROOT / "config/models.yaml")))
    settings.update({k: v for k, v in overrides.items() if v is not None})
    game = read_yaml(base / "game.yaml")
    if url := os.getenv("PLAYTEST_GAME_URL"):
        game.update(url=url, allowed_hosts=[urlsplit(url).netloc])
    if not game["allowed_hosts"] or urlsplit(game["url"]).netloc not in game["allowed_hosts"]:
        raise ValueError("Entry origin must be explicitly allowlisted")
    return (Game(**game), Persona(**read_yaml(base / "personas" / f"{persona_id}.yaml")),
            Settings(**settings))
