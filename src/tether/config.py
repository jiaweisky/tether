"""Typed, validated configuration loaded from a YAML file.

String values may reference environment variables explicitly with ``${VAR}``
(required), ``${VAR:-default}`` (optional) and ``$$`` for a literal ``$`` — the
same convention agentd uses. YAML therefore holds only references, never secret
values; resolved secrets come from the process environment or a loaded ``.env``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from tether.util.path_policy import compile_rules

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


class AuthConfig(BaseModel):
    type: Literal["bearer", "basic"] = "bearer"
    token: str | None = None
    username: str | None = None
    password: str | None = None


class ServerPoolEntry(BaseModel):
    id: str | None = None
    name: str
    backend: Literal["agentd", "opencode"] | None = None
    base_url: str
    token: str | None = None
    auth: AuthConfig | None = None
    working_directory: str | None = None
    default_agent: str | None = None
    default_model: str | None = None


@dataclass(frozen=True)
class ServerEndpoint:
    id: str
    name: str
    backend: str
    base_url: str
    auth: AuthConfig | None
    working_directory: str | None
    default_agent: str | None
    default_model: str | None


class ServerConfig(BaseModel):
    backend: Literal["agentd", "opencode"] = "agentd"
    base_url: str = "http://127.0.0.1:8787"
    token: str | None = None
    auth: AuthConfig | None = None
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
    # Isolated-project backend. agentd uses its control API; opencode uses
    # per-conversation worktrees on the endpoint below.
    backend: Literal["agentd", "opencode"] = "agentd"
    endpoint: str | None = None
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
    # Tether is the transport, not a second security policy. agentd's sandbox
    # and inboundPermissions own the boundary; auto-answer its asks so a normal
    # turn never parks on an avoidable HITL card. Operators can opt into HITL
    # per action with ``ask``.
    return {
        "read": "once",
        "glob": "once",
        "grep": "once",
        "webfetch": "once",
        "bash": "once",
        "write": "once",
        "edit": "once",
        "apply_patch": "once",
    }


class PermissionsConfig(BaseModel):
    auto: dict[str, PermissionAction] = Field(default_factory=_default_permission_auto)
    default: PermissionAction = "once"
    timeout_s: int = 300
    fallback: Literal["reject", "allow"] = "reject"
    poll_interval_s: int = 30
    # Non-question OpenCode forms (provider auth, MCP elicitation, ...).
    # off: never surface; admins: only direct chats started by an admin; all: any.
    rich_forms: Literal["off", "admins", "all"] = "off"

    def action_for(self, action: str) -> PermissionAction:
        return self.auto.get(action, self.default)


class CommandsConfig(BaseModel):
    prefix: str = "/"


class AdminConfig(BaseModel):
    """Per-channel/bot admin lists; unset falls back to ``group.admins``.

    An explicitly empty list means "no admins on this channel/bot" (it does not
    fall back). For WeChat, keys are bot ids, so admins can be scoped per bot.
    """

    wecom: list[str] | None = None
    feishu: list[str] | None = None
    qq: list[str] | None = None
    wechat: dict[str, list[str]] = Field(default_factory=dict)


class AccessConfig(BaseModel):
    allow_users: list[str] = Field(default_factory=list)
    allow_groups: list[str] = Field(default_factory=list)
    admins: AdminConfig = Field(default_factory=AdminConfig)


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


_WECHAT_BOT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class WeChatLoginVia(BaseModel):
    """One (channel, sender) that may start a QR login for a bot."""

    channel: Literal["wecom", "feishu", "qq", "wechat"]
    user: str

    @field_validator("user")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("login_via.user must not be empty")
        return value.strip()


class WeChatBotConfig(BaseModel):
    """One WeChat bot identity (a QR-logged-in personal account)."""

    id: str
    enabled: bool = True
    identity: ChannelIdentity = Field(default_factory=ChannelIdentity)
    # Who may start `/login wechat` for this bot, from which channel.
    login_via: list[WeChatLoginVia] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _WECHAT_BOT_ID.match(value):
            raise ValueError(
                "wechat bot id must match [a-z0-9][a-z0-9_-]{0,31} "
                "(it is a hidden route-key segment)"
            )

        return value

    def spec(self) -> WeChatBotSpec:
        return WeChatBotSpec(
            id=self.id,
            enabled=self.enabled,
            identity=self.identity,
            login_via=tuple(self.login_via),
        )


@dataclass(frozen=True)
class WeChatBotSpec:
    """A resolved WeChat bot slot."""

    id: str
    enabled: bool
    identity: ChannelIdentity
    login_via: tuple[WeChatLoginVia, ...] = ()

    @property
    def slot(self) -> str:
        """Stable key for binding records and route keys."""
        return self.id

    @property
    def instance_id(self) -> str:
        return f"wechat@{self.id}"


class WeChatChannelConfig(BaseModel):
    enabled: bool = False
    qr_timeout_s: int = 480
    bots: list[WeChatBotConfig] = Field(default_factory=list)

    @field_validator("qr_timeout_s")
    @classmethod
    def _positive_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("channels.wechat.qr_timeout_s must be > 0")
        return value

    def bot_specs(self) -> list[WeChatBotSpec]:
        return [bot.spec() for bot in self.bots]

    def spec_for(self, bot_id: str) -> WeChatBotSpec | None:
        for bot in self.bots:
            if bot.id == bot_id:
                return bot.spec()

        return None

    def bot_for_login(self, channel: str, user: str) -> WeChatBotSpec | None:
        """Resolve the bare ``/login wechat`` command for a sender."""
        for bot in self.bots:
            for via in bot.login_via:
                if via.channel == channel and via.user == user:
                    return bot.spec()

        return None

    def account_identity(self, bot_id: str) -> ChannelIdentity:
        """The per-bot identity override (WeChat has no channel-level one)."""
        spec = self.spec_for(bot_id)
        return spec.identity if spec is not None else ChannelIdentity()


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

    def identity_for_account(self, channel: str, account: str | None) -> ChannelIdentity:
        """The per-bot identity override (currently WeChat)."""
        if not account:
            return ChannelIdentity()

        sub = getattr(self, channel, None)
        resolve = getattr(sub, "account_identity", None)

        return resolve(account) if callable(resolve) else ChannelIdentity()


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

    def admins_for(self, channel: str, account: str | None = None) -> list[str]:
        """Admins for a conversation: account/channel override, else global."""
        admins = self.access.admins

        if channel == "wechat":
            key = account or "default"
            if key in admins.wechat:
                return list(admins.wechat[key])
            return list(self.group.admins)

        specific = getattr(admins, channel, None)
        if specific is not None:
            return list(specific)

        return list(self.group.admins)

    def server_endpoints(self) -> list[ServerEndpoint]:
        """Resolved endpoints, preserving legacy single-base behaviour."""
        if self.server.pool:
            endpoints: list[ServerEndpoint] = []
            for entry in self.server.pool:
                auth = entry.auth
                if auth is None and entry.token:
                    auth = AuthConfig(type="bearer", token=entry.token)
                endpoints.append(
                    ServerEndpoint(
                        id=entry.id or entry.name,
                        name=entry.name,
                        backend=entry.backend or self.server.backend,
                        base_url=entry.base_url.rstrip("/"),
                        auth=auth,
                        working_directory=entry.working_directory,
                        default_agent=entry.default_agent,
                        default_model=entry.default_model,
                    )
                )
            return endpoints

        auth = self.server.auth
        if auth is None and self.server.token:
            auth = AuthConfig(type="bearer", token=self.server.token)
        return [
            ServerEndpoint(
                id="default",
                name="default",
                backend=self.server.backend,
                base_url=self.server.base_url.rstrip("/"),
                auth=auth,
                working_directory=self.server.working_directory,
                default_agent=None,
                default_model=None,
            )
        ]

    def endpoint_for_base(self, base_url: str) -> ServerEndpoint | None:
        base = base_url.rstrip("/")
        for endpoint in self.server_endpoints():
            if endpoint.base_url.rstrip("/") == base:
                return endpoint
        return None

    def server_bases(self) -> list[tuple[str, str, str | None]]:
        """(name, base_url, working_directory) tuples for the pool (or single base)."""
        return [
            (endpoint.name, endpoint.base_url, endpoint.working_directory)
            for endpoint in self.server_endpoints()
        ]

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


def default_db_path(config_path: str | Path) -> Path:
    """Per-config state DB path, next to the config file.

    The config file identifies the bridge instance; deriving the path from its
    resolved location keeps two configs (or two checkouts) from sharing routes
    and WeChat tokens. The final component is always ``state.sqlite3`` so it is
    not mistaken for a config database.
    """
    config = Path(config_path).expanduser().resolve()
    instance = re.sub(r"[^A-Za-z0-9._-]+", "_", config.stem).strip("._-") or "instance"

    return config.parent / ".tether" / instance / "state.sqlite3"


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()

    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")

    return Config.model_validate(_expand_env(raw))


def validate_startup(config: Config) -> None:
    """Reject configurations that are unsafe or unusable at startup."""
    if config.projects.mode == "isolated":
        _validate_isolated_projects(config)

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

    _validate_server_endpoints(config)
    _validate_wechat(config.channels.wechat)
    _validate_wechat_logins(config)
    _validate_admins(config)


def _validate_isolated_projects(config: Config) -> None:
    projects = config.projects
    if not projects.source_directory:
        raise ValueError("projects.mode=isolated requires projects.source_directory")

    source = Path(projects.source_directory)
    base = Path(projects.base_dir)
    if not source.is_absolute() or not base.is_absolute():
        raise ValueError("projects.source_directory and projects.base_dir must be absolute")

    source_resolved = source.resolve()
    base_resolved = base.resolve()
    if source_resolved == base_resolved:
        raise ValueError("projects.base_dir must not be the source project directory")
    if base_resolved.is_relative_to(source_resolved):
        raise ValueError("projects.base_dir must not be inside projects.source_directory")
    if source_resolved.is_relative_to(base_resolved):
        raise ValueError("projects.source_directory must not be inside projects.base_dir")

    if projects.backend == "agentd":
        if not projects.control_url:
            raise ValueError(
                "projects.mode=isolated with backend=agentd requires projects.control_url"
            )
        return

    endpoint = next(
        (item for item in config.server_endpoints() if item.id == projects.endpoint),
        None,
    )
    if endpoint is None:
        raise ValueError(
            "projects.mode=isolated with backend=opencode requires projects.endpoint "
            "to name a configured endpoint"
        )
    if endpoint.backend != "opencode":
        raise ValueError("projects.endpoint must reference an opencode endpoint")
    if projects.isolation != "worktree":
        raise ValueError("projects.backend=opencode only supports isolation=worktree")
    if projects.sandbox is not None and projects.sandbox.process != "none":
        raise ValueError("projects.backend=opencode does not support sandbox.process")


def _validate_server_endpoints(config: Config) -> None:
    endpoints = config.server_endpoints()
    seen_ids: set[str] = set()
    by_base: dict[str, list[ServerEndpoint]] = {}

    for endpoint in endpoints:
        if not endpoint.id.strip():
            raise ValueError("server endpoint id must not be empty")
        if endpoint.id in seen_ids:
            raise ValueError(f"duplicate server endpoint id: {endpoint.id!r}")
        seen_ids.add(endpoint.id)

        if endpoint.working_directory is not None and not Path(
            endpoint.working_directory
        ).is_absolute():
            raise ValueError(
                f"server endpoint {endpoint.id!r} working_directory must be absolute"
            )

        by_base.setdefault(endpoint.base_url, []).append(endpoint)

    for base_url, matches in by_base.items():
        if len(matches) < 2:
            continue
        if any(endpoint.backend != "opencode" for endpoint in matches):
            raise ValueError(
                f"multiple server endpoints share {base_url!r}; only opencode endpoints "
                "may share a base_url"
            )


def _validate_wechat_logins(config: Config) -> None:
    """Every enabled WeChat bot needs a mapped, reachable login channel."""
    wechat = config.channels.wechat
    if not wechat.enabled:
        return

    enabled_channels = {
        "wecom": config.channels.wecom.enabled,
        "feishu": config.channels.feishu.enabled,
        "qq": config.channels.qq.enabled,
        "wechat": config.channels.wechat.enabled,
    }
    allowed_users = set(config.access.allow_users)

    for bot in wechat.bots:
        reachable = [via for via in bot.login_via if enabled_channels[via.channel]]
        if not reachable:
            raise ValueError(
                f"channels.wechat.bots[{bot.id!r}].login_via has no enabled channel; "
                "there is no CLI login fallback"
            )

        if allowed_users and not any(via.user in allowed_users for via in reachable):
            raise ValueError(
                f"channels.wechat.bots[{bot.id!r}].login_via has no user permitted by "
                "access.allow_users, so the login command would be dropped"
            )


def _validate_admins(config: Config) -> None:
    for name in ("wecom", "feishu", "qq"):
        values = getattr(config.access.admins, name)
        if values is not None and any(not value.strip() for value in values):
            raise ValueError(f"access.admins.{name} must not contain empty ids")

    known_slots = {spec.slot for spec in config.channels.wechat.bot_specs()}
    for slot, values in config.access.admins.wechat.items():
        if slot not in known_slots:
            raise ValueError(
                f"access.admins.wechat.{slot!r} does not match a configured WeChat "
                f"account slot ({', '.join(sorted(known_slots))})"
            )

        if any(not value.strip() for value in values):
            raise ValueError(
                f"access.admins.wechat.{slot!r} must not contain empty ids"
            )


def _validate_wechat(wechat: WeChatChannelConfig) -> None:
    """Validate bot ids, identities and login mappings."""
    specs = wechat.bot_specs()
    if wechat.enabled and not specs:
        raise ValueError("channels.wechat.enabled requires at least one bot")

    slots = [spec.slot for spec in specs]
    if len(slots) != len(set(slots)):
        raise ValueError("channels.wechat.bots contains duplicate ids")

    for spec in specs:
        name = (spec.identity.display_name or "").strip()
        if not name:
            raise ValueError(
                f"channels.wechat.bots[{spec.slot!r}].identity.display_name is "
                "required: WeChat exposes no bot name or remark name"
            )

        if not spec.login_via:
            raise ValueError(
                f"channels.wechat.bots[{spec.slot!r}].login_via is required: "
                "there is no CLI login, so a bot without a mapped channel cannot "
                "be logged in"
            )

    seen_logins: dict[tuple[str, str], str] = {}
    for spec in specs:
        for via in spec.login_via:
            key = (via.channel, via.user)
            previous = seen_logins.get(key)
            if previous is not None and previous != spec.slot:
                raise ValueError(
                    f"login_via {via.channel}:{via.user} maps to both "
                    f"{previous!r} and {spec.slot!r}; it must map to one bot"
                )

            seen_logins[key] = spec.slot
