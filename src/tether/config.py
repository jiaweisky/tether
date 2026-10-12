"""Typed, validated configuration loaded from a YAML file.

Only non-secret settings live in YAML; secrets are read from the environment by
the connectors and the agent client when they are constructed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

Isolation = Literal["auto", "shared", "per_conversation"]
ProviderName = Literal["shared", "pool", "worktree", "overlay", "container", "remote"]
OnConflict = Literal["isolate", "reject"]
SwitchGuard = Literal["reject", "migrate"]
BusyDelivery = Literal["queue", "steer"]
CrossUserDelivery = Literal["queue", "steer_same_user"]
HitlScope = Literal["initiator", "participants", "admins"]
CommandScope = Literal["initiator", "admins"]
IdentityInject = Literal["once", "always", "on_change"]
IdentitySource = Literal["im", "agent", "config"]
StreamingMode = Literal["auto", "native", "edit", "chunk", "final"]
ReasoningStyle = Literal["collapsible", "separate", "inline"]
CowMode = Literal["auto", "overlayfs", "reflink", "clonefile"]
ContainerRuntime = Literal["docker", "podman", "k8s"]
PermissionAction = Literal["once", "always", "reject", "ask"]


class ServerPoolEntry(BaseModel):
    name: str
    base_url: str
    token_env: str = "AGENTSERVE_TOKEN"
    working_directory: str | None = None
    default_agent: str | None = None


class ServerConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8787"
    token_env: str = "AGENTSERVE_TOKEN"
    request_timeout_s: float = 30.0
    sse_reconnect_ms: int = 1000
    pool: list[ServerPoolEntry] = Field(default_factory=list)


class AgentConfig(BaseModel):
    default_agent: str = "build"
    default_model: str | None = None
    subagent_depth: int | None = None
    writable: dict[str, bool] = Field(default_factory=dict)
    switch_guard: SwitchGuard = "reject"


class ModelConfig(BaseModel):
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


class ContainerConfig(BaseModel):
    runtime: ContainerRuntime = "docker"
    image: str = "ghcr.io/jiaweisky/agentserve:latest"
    network: str = "none"
    cpus: str = "2"
    memory: str = "2g"
    read_only_root: bool = True


class ProjectsConfig(BaseModel):
    isolation: Isolation = "auto"
    provider: ProviderName = "pool"
    on_conflict: OnConflict = "isolate"
    base_dir: str = "/var/lib/tether/workspaces"
    ttl_s: int = 3600
    max_leases: int = 32
    git_base_ref: str = "origin/HEAD"
    supervisor_command: str | None = None
    cow: CowConfig = Field(default_factory=CowConfig)
    container: ContainerConfig = Field(default_factory=ContainerConfig)


class SessionsConfig(BaseModel):
    idle_reset_s: int = 0
    busy_delivery: BusyDelivery = "queue"
    max_active_routes: int = 1000


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
    queue_backup_hint: bool = True


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


class MediaConfig(BaseModel):
    inline_limit_bytes: int = 10485760
    max_bytes: int = 52428800
    spool_dir: str = "{working_dir}/.tether/spool"
    fetch_url_outbound: bool = False
    outbound: MediaOutboundConfig = Field(default_factory=MediaOutboundConfig)

    @model_validator(mode="after")
    def _inline_le_max(self) -> MediaConfig:
        if self.inline_limit_bytes > self.max_bytes:
            raise ValueError("media.inline_limit_bytes must be <= media.max_bytes")
        return self


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


class WeComChannelConfig(BaseModel):
    enabled: bool = False
    bot_id_env: str = "WECOM_BOT_ID"
    secret_env: str = "WECOM_BOT_SECRET"


class FeishuChannelConfig(BaseModel):
    enabled: bool = False
    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"


class QQChannelConfig(BaseModel):
    enabled: bool = False
    appid_env: str = "QQ_BOT_APPID"
    secret_env: str = "QQ_BOT_SECRET"


class WeChatChannelConfig(BaseModel):
    enabled: bool = False
    cred_path: str = "~/.wechatbot/credentials.json"


class ChannelsConfig(BaseModel):
    wecom: WeComChannelConfig = Field(default_factory=WeComChannelConfig)
    feishu: FeishuChannelConfig = Field(default_factory=FeishuChannelConfig)
    qq: QQChannelConfig = Field(default_factory=QQChannelConfig)
    wechat: WeChatChannelConfig = Field(default_factory=WeChatChannelConfig)


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
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def resolve_secret(self, env_name: str) -> str | None:
        return os.environ.get(env_name)

    def server_bases(self) -> list[tuple[str, str, str | None]]:
        """(name, base_url, working_directory) tuples for the pool (or single base)."""
        if self.server.pool:
            return [(e.name, e.base_url, e.working_directory) for e in self.server.pool]
        return [("default", self.server.base_url, None)]

    def writable_override(self, agent: str) -> bool | None:
        return self.agent.writable.get(agent)


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    return Config.model_validate(raw)


def validate_startup(
    config: Config, *, known_agents: set[str] | None = None, writable_agents: set[str] | None = None
) -> None:
    """Reject configurations that are unsafe or unusable at startup.

    ``known_agents`` and ``writable_agents`` are optional because they require
    querying the agent service; supply them once it is reachable.
    """
    if config.projects.isolation == "shared" and writable_agents:
        raise ValueError(
            f"projects.isolation=shared is unsafe with writable agents: {sorted(writable_agents)}"
        )
    if known_agents is not None:
        unknown = set(config.agent.writable) - known_agents
        if unknown:
            raise ValueError(f"agent.writable lists unknown agents: {sorted(unknown)}")
    spool = config.media.spool_dir
    if "{working_dir}" not in spool:
        root = Path(spool).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        if not os.access(root, os.W_OK):
            raise ValueError(f"spool_dir is not writable: {root}")


def resolve_spool_dir(template: str, working_dir: str | None) -> Path:
    wd = working_dir or os.getcwd()
    return Path(template.replace("{working_dir}", wd)).expanduser()
