"""Unified Relational Database Storage Engine (SQLAlchemy Core/ORM).

Provides database models and session factories supporting both local SQLite
(`sqlite:///data/rpg_agent.sqlite3`) and cloud Neon PostgreSQL (`DATABASE_URL`).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Generator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Session as ORMSession, sessionmaker

from rachel.config import KEY_FILE, get_default_db_url

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base ORM declarative class."""
    pass


class Tenant(Base):
    """Tenants table: stores primary tenant record mapped to SSO sub or 'local'."""
    __tablename__ = "tenants"

    tenant_id: Column[str] = Column(String(255), primary_key=True, default="local")
    external_user_id: Column[str | None] = Column(String(255), nullable=True, index=True)
    created_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantApiKey(Base):
    """Hashed proxy keys issued to third-party clients (e.g. sk-local-..., sk-tenant-...)."""
    __tablename__ = "tenant_api_keys"

    id: Column[str] = Column(String(255), primary_key=True)
    tenant_id: Column[str] = Column(String(255), nullable=False, index=True, default="local")
    key_hash: Column[str] = Column(String(255), nullable=False, unique=True, index=True)
    prefix: Column[str] = Column(String(32), nullable=False, default="sk-local-")
    name: Column[str] = Column(String(255), nullable=False, default="Default Key")
    created_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Column[datetime.datetime | None] = Column(DateTime(timezone=True), nullable=True)
    is_active: Column[bool] = Column(Boolean, nullable=False, default=True)


class TenantCredential(Base):
    """Stores LLM provider credentials per tenant."""
    __tablename__ = "tenant_credentials"

    tenant_id: Column[str] = Column(String(255), primary_key=True, default="local")
    provider: Column[str] = Column(String(64), primary_key=True)
    api_key: Column[str] = Column(Text, nullable=False)
    updated_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantSetting(Base):
    """Stores tenant settings and active provider selection."""
    __tablename__ = "tenant_settings"

    tenant_id: Column[str] = Column(String(255), primary_key=True, default="local")
    active_provider: Column[str] = Column(String(64), nullable=False, default="openrouter_byok")
    default_model: Column[str | None] = Column(String(255), nullable=True)
    reasoning_format: Column[str | None] = Column(String(64), nullable=True)
    updated_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Session(Base):
    """RPG session state and turn history stored as a denormalized JSON blob."""
    __tablename__ = "sessions"

    tenant_id: Column[str] = Column(String(255), primary_key=True, default="local")
    session_id: Column[str] = Column(String(255), primary_key=True)
    turns_data: Column[str] = Column(Text, nullable=False, default="{}")
    updated_at: Column[datetime.datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


_engines: dict[str, Any] = {}
_sessionmakers: dict[Any, sessionmaker] = {}


def get_engine(db_url: str | None = None) -> Any:
    """Return an SQLAlchemy Engine for the target database URL."""
    url = db_url or get_default_db_url()
    if url not in _engines:
        if url.startswith("sqlite"):
            parsed_path = url.replace("sqlite:///", "")
            if parsed_path and not parsed_path.startswith(":memory:"):
                Path(parsed_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        else:
            engine = create_engine(url, pool_pre_ping=True)
        _engines[url] = engine
    return _engines[url]


def get_sessionmaker(engine: Any = None) -> sessionmaker:
    """Return a sessionmaker bound to the given engine or default engine."""
    eng = engine or get_engine()
    if eng not in _sessionmakers:
        _sessionmakers[eng] = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return _sessionmakers[eng]


def get_db_session(engine: Any = None) -> Generator[ORMSession, None, None]:
    """Context generator returning an ORM session."""
    sm = get_sessionmaker(engine)
    session = sm()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def hash_key(raw_key: str) -> str:
    """Return SHA-256 hash string for an API key."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def seed_bootstrap_key(session: ORMSession, tenant_id: str = "local") -> None:
    """Auto-seed default tenant and bootstrap client API key if missing."""
    tenant = session.query(Tenant).filter_by(tenant_id=tenant_id).first()
    if not tenant:
        tenant = Tenant(tenant_id=tenant_id)
        session.add(tenant)
        session.flush()

    raw_key = None
    if KEY_FILE.exists():
        try:
            raw_key = KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if not raw_key:
        import os
        raw_key = os.environ.get("RACHEL_PROXY_KEY", "rachel-local-default-key")

    kh = hash_key(raw_key)

    existing_key = session.query(TenantApiKey).filter_by(tenant_id=tenant_id).first()
    if not existing_key:
        prefix = "sk-local-" if tenant_id == "local" else "sk-tenant-"
        bootstrap_key = TenantApiKey(
            id=f"key_{tenant_id}_default",
            tenant_id=tenant_id,
            key_hash=kh,
            prefix=prefix,
            name="Bootstrap Proxy Key",
            is_active=True,
        )
        session.add(bootstrap_key)
        logger.info("Auto-seeded bootstrap proxy key for tenant '%s'", tenant_id)

    session.commit()


def init_db(db_url: str | None = None, engine: Any = None) -> Any:
    """Initialize database schema and seed bootstrap keys."""
    eng = engine or get_engine(db_url)
    Base.metadata.create_all(bind=eng)

    sm = get_sessionmaker(eng)
    with sm() as session:
        seed_bootstrap_key(session, tenant_id="local")

    return eng
