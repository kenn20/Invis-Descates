"""Persistent account/device identity. Bearer credentials never enter the database."""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import (Boolean, Column, ForeignKey, Integer, MetaData, String,
                        Table, create_engine, insert, select, update)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

metadata = MetaData()
users = Table("users", metadata,
    Column("id", String(36), primary_key=True),
    Column("google_subject", String(255), nullable=False, unique=True))
vaults = Table("vaults", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False))
devices = Table("devices", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("name", String(80), nullable=False, default="Obsidian"),
    Column("installation_id", String(36), nullable=False),
    Column("vault_id", ForeignKey("vaults.id"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", Integer, nullable=False),
    Column("revoked", Boolean, nullable=False, default=False))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    user_id: str
    device_id: str
    installation_id: str
    vault_id: str


class IdentityStore:
    def __init__(self, database_url: str):
        options = {"pool_pre_ping": True, "hide_parameters": True}
        if database_url.startswith("postgresql"):
            options.update(pool_size=2, max_overflow=0, pool_timeout=5, connect_args={"connect_timeout": 5})
        if database_url == "sqlite://":
            options.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.engine = create_engine(database_url, **options)

    def initialize(self):
        """Run explicitly during deployment; never mutate schemas on request startup."""
        metadata.create_all(self.engine)

    def user_for_google(self, subject: str) -> str:
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise ValueError("Invalid subject")
        try:
            with self.engine.begin() as conn:
                user = conn.execute(select(users.c.id).where(users.c.google_subject == subject)).scalar_one_or_none()
                if user:
                    return user
                user = str(uuid4())
                conn.execute(insert(users).values(id=user, google_subject=subject))
                return user
        except IntegrityError:
            # Concurrent logins resolve to the same account; never match by email.
            with self.engine.connect() as conn:
                return conn.execute(select(users.c.id).where(users.c.google_subject == subject)).scalar_one()

    def issue_device(self, conn, user_id: str, installation_id: str, vault_id: str, name="Obsidian"):
        owner = conn.execute(select(vaults.c.user_id).where(vaults.c.id == vault_id)).scalar_one_or_none()
        if owner is not None and owner != user_id:
            raise PermissionError("Ownership mismatch")
        if owner is None:
            conn.execute(insert(vaults).values(id=vault_id, user_id=user_id))
        conn.execute(update(devices).where(devices.c.user_id == user_id,
            devices.c.installation_id == installation_id, devices.c.vault_id == vault_id).values(revoked=True))
        token = secrets.token_urlsafe(32)
        device_id = str(uuid4())
        conn.execute(insert(devices).values(id=device_id, user_id=user_id, name=name,
            installation_id=installation_id, vault_id=vault_id, token_hash=digest(token),
            expires_at=int(time.time()) + 90 * 86400, revoked=False))
        return token, device_id

    def authenticate(self, token: str | None) -> Identity | None:
        if not token:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(select(devices).where(devices.c.token_hash == digest(token),
                devices.c.revoked.is_(False), devices.c.expires_at > int(time.time()))).mappings().first()
            if not row:
                return None
            return Identity(row["user_id"], row["id"], row["installation_id"], row["vault_id"])

    def revoke(self, identity: Identity):
        with self.engine.begin() as conn:
            conn.execute(update(devices).where(devices.c.id == identity.device_id,
                devices.c.user_id == identity.user_id).values(revoked=True))

    @staticmethod
    def owns(identity: Identity, payload: dict) -> bool:
        return (payload.get("installationId") == identity.installation_id
                and payload.get("vaultId") == identity.vault_id)
