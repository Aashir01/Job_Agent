"""Configuration. Every knob the spec names is a setting, not a literal."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ── Infrastructure ────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""
    agent_key: str = ""  # shared secret for machine routes (GH Actions, dashboard)
    environment: Literal["dev", "prod"] = "dev"

    # ── LLM providers (§8) ────────────────────────────────────────────────
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_cheap_model: str = "gemini-2.0-flash"
    gemini_good_model: str = "gemini-2.0-flash"
    groq_cheap_model: str = "llama-3.1-8b-instant"
    groq_good_model: str = "llama-3.3-70b-versatile"

    # OpenRouter reaches many models behind one key. When set it is tried first;
    # the fallbacks are used for both tiers when a free model is rate-limited.
    # Ordered by what actually returns parseable JSON: the reasoning models were
    # slower and, with reasoning on, spent the whole budget thinking.
    openrouter_api_key: str = ""
    openrouter_cheap_model: str = "inclusionai/ling-3.0-flash-fin:free"
    openrouter_good_model: str = "nvidia/nemotron-3.5-lightning:free"
    openrouter_fallback_models: str = (
        "poolside/laguna-s-2.1:free,nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    openrouter_disable_reasoning: bool = True

    # ── Embeddings ────────────────────────────────────────────────────────
    # 'hashing' is deterministic, dependency-free and fits a 256MB machine.
    # 'gemini' uses text-embedding-004 with output_dimensionality=384.
    embedding_provider: Literal["hashing", "gemini"] = "hashing"
    embedding_dim: int = 384

    # ── Quota budget (§8) ─────────────────────────────────────────────────
    llm_calls_per_batch: int = 300
    max_outbound_emails_per_day: int = 30      # §10 hard cap
    max_extension_submits_per_day: int = 20    # §10 hard cap
    http_timeout_s: float = 20.0
    scout_concurrency: int = 6

    # ── Priority weighting (§2) ───────────────────────────────────────────
    weight_remote_fte: float = 1.00
    weight_relocation: float = 0.70
    weight_contract: float = 0.40

    # ── Review tiers (§7) ─────────────────────────────────────────────────
    tier_fast_lane_min: int = 85
    tier_standard_min: int = 70
    tier_marginal_min: int = 60   # below this, no package is built at all

    # ── Scout ─────────────────────────────────────────────────────────────
    dedupe_cosine_threshold: float = 0.92      # §6
    job_max_age_days: int = 21
    scout_max_jobs_per_batch: int = 600

    # ── Tailor ────────────────────────────────────────────────────────────
    tailor_bullet_count: int = 12
    tailor_min_bullet_strength: int = 2

    # ── Outreach ──────────────────────────────────────────────────────────
    resend_api_key: str = ""
    hunter_api_key: str = ""
    from_email: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # ── Sponsorship register URLs (§6). Overridable: the Home Office
    #    republishes under a dated filename every few weeks.
    register_url_uk: str = ""
    register_url_nl: str = ""
    register_url_ca: str = ""

    # ── Notifications ─────────────────────────────────────────────────────
    # After every batch the system pushes a digest of what it found. Enable any
    # subset; each is independent and a failure in one never blocks the others.
    #
    # Telegram is the recommended default: free, instant on a phone, and set up
    # in two minutes (talk to @BotFather for a token, then @userinfobot for your
    # chat id). WhatsApp has no free first-party API — use notify_webhook_url
    # with a relay such as CallMeBot if you want messages there.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    notify_webhook_url: str = ""          # generic JSON POST; covers WhatsApp relays
    notify_email: str = ""                # digest recipient, via Resend
    dashboard_url: str = ""               # so a digest can link to the queue

    notify_top_n: int = 8                 # how many packages to list in a digest
    notify_on_empty: bool = False         # say nothing when a run found nothing
    notify_on_error: bool = True          # always report a failed run

    # ── Chaser cadence (§6) ───────────────────────────────────────────────
    follow_up_1_days: int = 3
    follow_up_2_days: int = 10
    ghost_after_days: int = 30

    # ── Gmail reply detection (§6 Chaser). Read-only scope is enough. ──────
    google_client_id: str = ""
    google_client_secret: str = ""
    gmail_refresh_token: str = ""

    track_weights_map: dict = Field(default_factory=dict, exclude=True)

    @property
    def openrouter_fallbacks(self) -> list[str]:
        return [m.strip() for m in self.openrouter_fallback_models.split(",") if m.strip()]

    @property
    def track_weights(self) -> dict[str, float]:
        return {
            "remote_fte": self.weight_remote_fte,
            "relocation": self.weight_relocation,
            "contract": self.weight_contract,
        }

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key or self.gemini_api_key or self.groq_api_key)

    @property
    def notify_channels(self) -> list[str]:
        """Which digest channels are configured, in delivery order."""
        configured = []
        if self.telegram_bot_token and self.telegram_chat_id:
            configured.append("telegram")
        if self.discord_webhook_url:
            configured.append("discord")
        if self.slack_webhook_url:
            configured.append("slack")
        if self.notify_webhook_url:
            configured.append("webhook")
        if self.notify_email and self.resend_api_key and self.from_email:
            configured.append("email")
        return configured


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
