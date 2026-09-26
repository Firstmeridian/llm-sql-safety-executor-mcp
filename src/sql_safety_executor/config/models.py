"""Strict file schemas. No environment sources or implicit configuration search."""

from typing import Literal, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, hide_input_in_errors=True
    )

    @field_validator("*", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value, info):
        if get_origin(
            cls.model_fields[info.field_name].annotation
        ) is tuple and isinstance(value, list):
            return tuple(value)
        return value


class SecretSource(Model):
    value: SecretStr | None = Field(default=None, repr=False)
    env: str | None = Field(default=None, min_length=1)
    file: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_source(self):
        if sum(v is not None for v in (self.value, self.env, self.file)) != 1:
            raise ValueError("exactly_one_secret_source_required")
        return self


class Timeouts(Model):
    query_seconds: int = Field(default=30, ge=1)
    connect_seconds: int = Field(default=10, ge=1)


class ConnectionTimeouts(Model):
    query_seconds: int | None = Field(default=None, ge=1)
    connect_seconds: int | None = Field(default=None, ge=1)


class Defaults(Model):
    timeouts: Timeouts = Timeouts()


class Files(Model):
    connections: str = Field(min_length=1)
    skills: str | None = Field(default=None, min_length=1)


class Server(Model):
    default_connection: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    tool_timeout_seconds: float = Field(default=120, ge=0, allow_inf_nan=False)


class Tools(Model):
    schema_enabled: bool = Field(default=True, alias="schema")
    table_summary: bool = False
    large_table_threshold: int = Field(default=1000, ge=0)


class Limits(Model):
    result_rows: int = Field(default=100, ge=0)
    result_chars: int = Field(default=16000, ge=0)
    sql_chars: int = Field(default=20000, ge=0)
    schema_tables: int = Field(default=50, ge=0)
    overview_tables: int = Field(default=100, ge=0)


class Telemetry(Model):
    enabled: bool = False
    path: str = "../logs/tool_calls.jsonl"
    sample_rate: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)


class Logging(Model):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    path: str | None = None


class Observability(Model):
    telemetry: Telemetry = Telemetry()
    logging: Logging = Logging()


class ServerFile(Model):
    schema_version: Literal[1]
    files: Files
    server: Server
    tools: Tools = Tools()
    limits: Limits = Limits()
    defaults: Defaults = Defaults()
    observability: Observability = Observability()


class ReadPolicy(Model):
    mode: Literal["deny", "allowlist", "all"] = "deny"
    tables: tuple[str, ...] = ()
    allow_union: bool = False

    @model_validator(mode="after")
    def table_scope(self):
        if self.tables and self.mode != "allowlist":
            raise ValueError("tables_require_allowlist_mode")
        if any(not t.strip() or "*" in t for t in self.tables):
            raise ValueError("explicit_table_names_required")
        if self.allow_union and (
            self.mode == "deny" or self.mode == "allowlist" and not self.tables
        ):
            raise ValueError("union_requires_explicit_table_scope")
        return self


class ConnectionMutation(Model):
    enabled: bool = False
    skills: tuple[str, ...] = ()

    @field_validator("skills")
    @classmethod
    def skill_names(cls, value):
        import re

        if any(
            v != "*" and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", v) for v in value
        ):
            raise ValueError("invalid_skill_name")
        return value


class SQLite(Model):
    path: str = Field(min_length=1)
    progress_handler_interval: int = Field(default=100, ge=1)


class MySQL(Model):
    host: str = Field(min_length=1)
    user: str = Field(min_length=1)
    database: str = Field(min_length=1)
    password: SecretSource


class Connection(Model):
    type: Literal["mysql", "sqlite"]
    mysql: MySQL | None = None
    sqlite: SQLite | None = None
    read: ReadPolicy = ReadPolicy()
    mutation: ConnectionMutation = ConnectionMutation()
    timeouts: ConnectionTimeouts = ConnectionTimeouts()

    @model_validator(mode="after")
    def backend(self):
        if self.type == "mysql" and (self.mysql is None or self.sqlite is not None):
            raise ValueError("mysql_settings_required_sqlite_forbidden")
        if self.type == "sqlite" and (self.sqlite is None or self.mysql is not None):
            raise ValueError("sqlite_settings_required_mysql_forbidden")
        return self


class ConnectionsFile(Model):
    schema_version: Literal[1]
    connections: dict[str, Connection]

    @field_validator("connections")
    @classmethod
    def aliases(cls, value):
        import re

        if not value or any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", k) for k in value
        ):
            raise ValueError("nonempty_canonical_connection_aliases_required")
        return value


class Discovery(Model):
    default_detail: Literal["compact", "summary", "full"] = "summary"
    available_only: bool = True


class Readiness(Model):
    check_schema: bool = True


class SkillPolicy(Model):
    exclude_profiles: tuple[str, ...] = ()


class Preview(Model):
    ttl_seconds: int = Field(default=300, ge=1, le=86400)
    max_entries: int = Field(default=10000, ge=1, le=100000)


class MRTR(Model):
    enabled: bool = False


class Mutation(Model):
    enabled: bool = False
    allowed_connections: tuple[str, ...] = ()
    preview: Preview = Preview()
    mrtr: MRTR = MRTR()


class Audit(Model):
    queries: bool = False
    path: str = "../logs/skill_audit.jsonl"
    agent_id: str = "unknown"


class Skills(Model):
    enabled: bool = False
    directory: str = "../skills"
    discovery: Discovery = Discovery()
    readiness: Readiness = Readiness()
    policy: SkillPolicy = SkillPolicy()
    mutation: Mutation = Mutation()
    audit: Audit = Audit()

    @model_validator(mode="after")
    def switches(self):
        if self.mutation.mrtr.enabled and not (self.enabled and self.mutation.enabled):
            raise ValueError("mrtr_requires_skills_and_mutations")
        return self


class SkillsFile(Model):
    schema_version: Literal[1]
    skills: Skills = Skills()
