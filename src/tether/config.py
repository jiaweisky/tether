"""Typed, validated configuration loaded from a YAML file.

String values may reference environment variables explicitly with ``${VAR}``
(required), ``${VAR:-default}`` (optional) and ``$$`` for a literal ``$`` — the
same convention agentd uses. YAML therefore holds only references, never secret
values; resolved secrets come from the process environment or a loaded ``.env``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from .util.path_policy import compile_rules

# ``$$`` (a literal ``$``) or ``${VAR}`` / ``${VAR:-default}``.
_ENV_REF = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

Isolation = Literal["shared", "isolated"]
IsolationImpl = Literal["none", "copy", "worktree", "overlay"]
BusyDelivery = Literal["queue", "steer"]
CrossUserDelivery = Literal["queue", "steer_same_user"]
HitlScope = Literal["initiator", "participants", "admins"]
CommandScope = Literal["initiator", "admins"]
IdentityInject = Literal["once", "always", "on_change"]
IdentitySource = Literal["im", "agent", "config"]
StreamingMode = Literal["auto", "native", "edit", "chunk", "final"]
ReasoningStyle = Literal["collapsible", "separate", "inline"]
CowMode = Literal["auto", "reflink", "clonefile"]
PermissionAction = Literal["once", "always", "reject", "ask"]


class ServerPoolEntry(BaseModel):
    name: str
    base_url: str
    token: str | None = None
    working_directory: str | None = None
    default_agent: str | None = None
    default_model: str | None = None


class ServerConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8787"
    token: str | None = None
    request_timeout_s: float = 30.0
    sse_reconnect_ms: int = 1000
    # The single base's working directory, when it is known (used for the media
    # spool path); pool entries carry their own.
    working_directory: str | None = None
    pool: list[ServerPoolEntry] = Field(default_factory=list)


class AgentConfig(BaseModel):
    # Optional overrides. When unset the agent and model are discovered from
    # agentd (GET /api/agent; createSession omits the model so agentd picks its
    # default), so the bridge does not restate agentd's configuration.
    default_agent: str | None = None
    default_model: str | None = None


class ModelConfig(BaseModel):
    # Optional override of the model context window (tokens) for the usage line;
    # by default it comes from GET /api/model (`contextLimit`). Unset hides the
    # percentage only when the API also omits it.
    context_limit: int | None = None

    @field_validator("context_limit")
    @classmethod
    def _positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("model.context_limit must be > 0")
        return v


class CowConfig(BaseModel):
    mode: CowMode = "auto"
    base_readonly: bool = True


class InboundPermissionRule(BaseModel):
    action: str
    resource: str = "*"
    effect: str = "ask"


class SandboxConfig(BaseModel):
    # OS-level command sandbox for a leased instance (agentd's sandbox.process):
    # none | bwrap | seatbelt.
    process: str = "none"
    failure_policy: Literal["fail-closed", "fail-open"] = "fail-closed"


class ProjectsConfig(BaseModel):
    # Either everyone shares one project, or each conversation leases its own
    # view of the source project.
    mode: Isolation = "shared"
    # Isolation implementation, used when mode=isolated (agentd's control API).
    isolation: IsolationImpl = "worktree"
    # Parent directory for created views and per-instance state roots.
    base_dir: str = "/var/lib/tether/workspaces"
    ttl_s: int = 3600
    max_leases: int = 32
    # The commit-ish a worktree view starts from.
    git_base_ref: str = "HEAD"
    cow: CowConfig = Field(default_factory=CowConfig)
    # mode=isolated: agentd's control API and the source project to derive views from.
    control_url: str | None = None
    control_token: str | None = None
    source_directory: str | None = None
    # mode=isolated: the tool policy for the leased instance (empty = agentd's
    # read-only default). Same shape as agentd's server inboundPermissions.
    inbound_permissions: list[InboundPermissionRule] = Field(default_factory=list)
    # mode=isolated: the OS command sandbox for the leased instance (none =
    # agentd pass-through). Same shape as agentd's server sandbox.
    sandbox: SandboxConfig | None = None


class SessionsConfig(BaseModel):
    idle_reset_s: int = 0
    busy_delivery: BusyDelivery = "queue"
    max_active_routes: int = 1000
    # On the first message after a restart, verify a loaded route's session still
    # exists on agentd and recreate it if not (handles a lost/rotated agentd root).
    validate_session: bool = True
    # On shutdown, interrupt in-progress turns and reject their pending
    # interactions. Default false so a bridge restart does not disturb a turn or
    # consume a parked permission (it resumes after restart).
    interrupt_on_shutdown: bool = False
    # Cross-check active turns against agentd every N seconds and finish any whose
    # session is no longer running (a lost `session.status idle` would otherwise
    # block the conversation forever). 0 disables the watchdog.
    turn_watchdog_s: int = 30


class DedupConfig(BaseModel):
    ttl_s: int = 600


class GroupConfig(BaseModel):
    inject_speaker: bool = True
    speaker_format: str = "[{name}]: {text}"
    mention_others: bool = True
    reply_with_mention: bool = True
    cross_user_delivery: CrossUserDelivery = "queue"
    admins: list[str] = Field(default_factory=list)
    hitl_scope: HitlScope = "initiator"
    command_scope: CommandScope = "initiator"


class IdentityConfig(BaseModel):
    inject: IdentityInject = "on_change"
    source: IdentitySource = "im"
    display_name: str | None = None
    description: str | None = None
    warn_on_mismatch: bool = True
    sync_participants: bool = False
    preamble_tag: str = "bridge-context"


class StreamingConfig(BaseModel):
    mode: StreamingMode = "auto"
    min_interval_ms: int = 700
    idle_progress_ms: int = 2000
    boundary_flush: bool = True
    max_live_chars: int = 4000
    rate_limit_backoff: float = 2.0
    show_tools: bool = True
    show_reasoning: bool = False
    reasoning_style: ReasoningStyle = "collapsible"
    show_usage: bool = True
    max_chars_override: int | None = None

    @field_validator("min_interval_ms")
    @classmethod
    def _positive_interval(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("streaming.min_interval_ms must be > 0")
        return v


def _default_media_sources() -> list[Literal["tool_media", "changed_files"]]:
    return ["tool_media"]


class MediaOutboundConfig(BaseModel):
    sources: list[Literal["tool_media", "changed_files"]] = Field(
        default_factory=_default_media_sources
    )
    image_max_bytes: int = 10485760
    # WHEN: auto-forward files the agent writes/edits. Off by default — during
    # development, edits are usually incidental, not something to push to chat.
    auto_files: bool = False
    # WHETHER: ordered glob patterns matched against a file's resolved absolute
    # path. Default-deny — a file is sent only when the last matching pattern is a
    # positive one. Empty = no path may be sent (only the explicit /send command).
    patterns: list[str] = Field(default_factory=list)

    @field_validator("patterns")
    @classmethod
    def _valid_patterns(cls, patterns: list[str]) -> list[str]:
        try:
            compile_rules(patterns, None)
        except re.error as exc:
            raise ValueError(f"invalid glob pattern: {exc}") from exc
        return patterns


class MediaConfig(BaseModel):
    # Outbound size cap (path-based files, /send, remote url fetch). Inbound
    # delivery — inline / provider file / url / downsample / spool — is owned by
    # agentd's `servers[].media` policy, not the bridge.
    max_bytes: int = 52428800
    # Connector guard: do not download an attachment the platform declares larger
    # than this (protects against pulling a huge file before the download). It is
    # not a delivery decision — that belongs to agentd.
    max_attachment_bytes: int = 26214400
    fetch_url_outbound: bool = False
    outbound: MediaOutboundConfig = Field(default_factory=MediaOutboundConfig)


def _default_permission_auto() -> dict[str, PermissionAction]:
    return {
        "read": "once",
        "glob": "once",
        "grep": "once",
        "webfetch": "ask",
        "bash": "ask",
        "write": "ask",
        "edit": "ask",
        "apply_patch": "ask",
    }


class PermissionsConfig(BaseModel):
    auto: dict[str, PermissionAction] = Field(default_factory=_default_permission_auto)
    default: PermissionAction = "ask"
    timeout_s: int = 300
    fallback: Literal["reject", "allow"] = "reject"
    poll_interval_s: int = 30

    def action_for(self, action: str) -> PermissionAction:
        return self.auto.get(action, self.default)


class CommandsConfig(BaseModel):
    prefix: str = "/"


class AccessConfig(BaseModel):
    allow_users: list[str] = Field(default_factory=list)
    allow_groups: list[str] = Field(default_factory=list)


class ChannelIdentity(BaseModel):
    """Per-channel override of the bot's name/description.

    Empty fields fall back to the global ``identity`` config, then to whatever
    the platform exposes (e.g. Feishu's ``bot/v3/info``).
    """

    display_name: str | None = None
    description: str | None = None


class WeComChannelConfig(BaseModel):
    enabled: bool = False
    bot_id: str | None = None
    secret: str | None = None
    welcome_text: str | None = None
    # Long-connection reconnect backoff ceiling (ms). The SDK hard-codes 30s; a
    # smaller value recovers from a network blip faster (at more attempts).
    reconnect_max_ms: int = 30000
    identity: ChannelIdentity = Field(default_factory=ChannelIdentity)


class FeishuChannelConfig(BaseModel):
    enabled: bool = False
    app_id: str | None = None
    app_secret: str | None = None
    identity: ChannelIdentity = Field(default_factory=ChannelIdentity)


class QQChannelConfig(BaseModel):
    enabled: bool = False
    appid: str | None = None
    secret: str | None = None
    identity: ChannelIdentity = Field(default_factory=ChannelIdentity)


class WeChatChannelConfig(BaseModel):
    enabled: bool = False
    cred_path: str = "~/.wechatbot/credentials.json"
    identity: ChannelIdentity = Field(default_factory=ChannelIdentity)


class ChannelsConfig(BaseModel):
    wecom: WeComChannelConfig = Field(default_factory=WeComChannelConfig)
    feishu: FeishuChannelConfig = Field(default_factory=FeishuChannelConfig)
    qq: QQChannelConfig = Field(default_factory=QQChannelConfig)
    wechat: WeChatChannelConfig = Field(default_factory=WeChatChannelConfig)

    def identity_for(self, channel: str) -> ChannelIdentity:
        """The per-channel identity override, if the channel has one."""
        sub = getattr(self, channel, None)
        override = getattr(sub, "identity", None)
        return override if isinstance(override, ChannelIdentity) else ChannelIdentity()


class MetricsConfig(BaseModel):
    # Optional HTTP endpoint exposing GET /healthz and GET /metrics
    # (e.g. "127.0.0.1:9091"); unset = no listener.
    listen: str | None = None
    # Also log a structured "metrics" event every N seconds (0 disables).
    log_interval_s: int = 60


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_logs: bool = Field(default=True, alias="json")

    model_config = {"populate_by_name": True}


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    group: GroupConfig = Field(default_factory=GroupConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    access: AccessConfig = Field(default_factory=AccessConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    # Watch config.yaml and hot-apply a safe subset (group/access/permissions/
    # commands/identity/sessions/media) without a restart.
    reload: bool = False

    def server_bases(self) -> list[tuple[str, str, str | None]]:
        """(name, base_url, working_directory) tuples for the pool (or single base)."""
        if self.server.pool:
            return [(e.name, e.base_url, e.working_directory) for e in self.server.pool]
        return [("default", self.server.base_url, None)]

    def server_token(self, base_url: str) -> str | None:
        """Bearer token for a base URL (pool entry, else the top-level token)."""
        base = base_url.rstrip("/")
        for entry in self.server.pool:
            if entry.base_url.rstrip("/") == base:
                return entry.token
        return self.server.token


def _expand_env(value: Any) -> Any:
    """Recursively resolve ``${VAR}`` references in YAML string values."""
    if isinstance(value, str):
        return _expand_str(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _expand_str(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(0) == "$$":
            return "$"
        name, default = match.group(1), match.group(2)
        value = os.environ.get(name)
        if value is None:
            if default is None:
                raise ValueError(f"environment variable {name} is not set")
            return default
        return value

    return _ENV_REF.sub(replace, text)


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    return Config.model_validate(_expand_env(raw))


def validate_startup(config: Config) -> None:
    """Reject configurations that are unsafe or unusable at startup."""
    if config.projects.mode == "isolated" and not (
        config.projects.control_url and config.projects.source_directory
    ):
        raise ValueError(
            "projects.mode=isolated requires projects.control_url and projects.source_directory"
        )
    if config.channels.wecom.enabled:
        wecom = config.channels.wecom.identity
        name = wecom.display_name or config.identity.display_name
        description = wecom.description or config.identity.description
        if not (name and description):
            raise ValueError(
                "channels.wecom requires a display_name and description — set "
                "channels.wecom.identity (or the global identity), since WeCom does "
                "not expose the bot's name or description"
            )
