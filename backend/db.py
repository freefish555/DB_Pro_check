"""Small relational core. Immutable source snapshots live in JSON, not mutable UI state."""
import os
import time
import uuid
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA = Path(os.environ.get('REVIEW_DATA_DIR', 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{(DATA / "review.db").as_posix()}')
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False, 'timeout': 30} if DATABASE_URL.startswith('sqlite') else {}, pool_pre_ping=True)
if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_config(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class User(Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(Text)
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0)


class LoginSession(Base):
    __tablename__ = 'sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[float] = mapped_column(Float)


class Project(Base):
    __tablename__ = 'projects'
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Member(Base):
    __tablename__ = 'members'
    __table_args__ = (UniqueConstraint('project_id', 'user_id'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    role: Mapped[str] = mapped_column(String(20), default='reviewer')


class Document(Base):
    __tablename__ = 'documents'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    role: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')


class Knowledge(Base):
    __tablename__ = 'knowledge'
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[str] = mapped_column(String(30))
    level: Mapped[int | None] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(30), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft')
    content: Mapped[dict] = mapped_column(JSON)
    published_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))


class ModelConfig(Base):
    __tablename__ = 'model_config'
    base_url: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(150))
    key_encrypted: Mapped[str] = mapped_column(Text, default='')
    external: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout: Mapped[int] = mapped_column(Integer, default=120)


class ModelService(Base):
    __tablename__ = 'model_services'
    name: Mapped[str] = mapped_column(String(150))
    base_url: Mapped[str] = mapped_column(Text, unique=True)
    protocol: Mapped[str] = mapped_column(String(40), default='chat_completions')
    models: Mapped[list] = mapped_column(JSON, default=list)
    external: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class UserModelProfile(Base):
    __tablename__ = 'user_model_profiles'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey('model_services.id'))
    model: Mapped[str] = mapped_column(String(150))
    key_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Run(Base):
    __tablename__ = 'runs'
    __table_args__ = (UniqueConstraint('project_id', 'request_key'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))
    modules: Mapped[list] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base):
    __tablename__ = 'tasks'
    project_id: Mapped[str | None] = mapped_column(ForeignKey('projects.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease: Mapped[str] = mapped_column(String(36), default='')
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(Text, default='')
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    finished_at: Mapped[float | None] = mapped_column(Float)


class RedactionBatch(Base):
    __tablename__ = 'redaction_batches'
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    token_map_encrypted: Mapped[str] = mapped_column(Text, default='')
    terms_encrypted: Mapped[str] = mapped_column(Text, default='')
    list_hash: Mapped[str] = mapped_column(String(64), default='')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[float | None] = mapped_column(Float)


class RedactionApproval(Base):
    __tablename__ = 'redaction_approvals'
    __table_args__ = (UniqueConstraint('run_id', 'task_id'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    list_hash: Mapped[str] = mapped_column(String(64))


class ReviewDecision(Base):
    __tablename__ = 'review_decisions'
    __table_args__ = (UniqueConstraint('run_id', 'row_id'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), index=True)
    row_id: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    note: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Issue(Base):
    __tablename__ = 'issues'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('tasks.id'))
    chapter: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    object_name: Mapped[str] = mapped_column(Text, default='')
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    machine: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    note: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(Integer, default=1)


class Audit(Base):
    __tablename__ = 'audit'
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    project_id: Mapped[str | None] = mapped_column(ForeignKey('projects.id'), index=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


def public(row, exclude=()):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}

