"""Small per-user vector collections; owner and vault predicates precede ranking."""
from __future__ import annotations

import math
from uuid import uuid4

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, JSON, String, Table, Text, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from service.identity import Identity, metadata, users

collections = Table("vector_collections", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey(users.c.id), unique=True, nullable=False))
memories = Table("memories", metadata,
    Column("collection_id", ForeignKey(collections.c.id), primary_key=True),
    Column("vault_id", String(36), primary_key=True),
    Column("note_id", String(36), primary_key=True),
    Column("revision", BigInteger, nullable=False),
    Column("content", Text, nullable=False),
    Column("vector", JSON, nullable=False))


def valid_vector(vector):
    return (isinstance(vector, list) and 1 <= len(vector) <= 4096
        and all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in vector)
        and 0 < sum(v * v for v in vector) < float("inf"))


def cosine(a, b):
    if len(a) != len(b):
        raise ValueError("Embedding model changed; rebuild the collection")
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))


class MemoryStore:
    def __init__(self, identity_store):
        self.engine = identity_store.engine

    def collection(self, user_id):
        try:
            with self.engine.begin() as conn:
                existing = conn.execute(select(collections.c.id).where(collections.c.user_id == user_id)).scalar_one_or_none()
                if existing:
                    return existing
                collection_id = str(uuid4())
                conn.execute(insert(collections).values(id=collection_id, user_id=user_id))
                return collection_id
        except IntegrityError:
            with self.engine.connect() as conn:
                return conn.execute(select(collections.c.id).where(collections.c.user_id == user_id)).scalar_one()

    @staticmethod
    def owned(identity: Identity):
        return (memories.c.collection_id == collections.c.id,
                collections.c.user_id == identity.user_id,
                memories.c.vault_id == identity.vault_id)

    def upsert(self, identity, note_id, revision, content, vector):
        if not valid_vector(vector):
            raise ValueError("Invalid embedding")
        collection_id = self.collection(identity.user_id)
        with self.engine.begin() as conn:
            # Serialize writes in this user's collection, including simultaneous first uploads.
            conn.execute(update(collections).where(collections.c.id == collection_id,
                collections.c.user_id == identity.user_id).values(id=collection_id))
            key = (memories.c.collection_id == collection_id, memories.c.vault_id == identity.vault_id,
                   memories.c.note_id == note_id)
            current = conn.execute(select(memories.c.revision).where(*key)).scalar_one_or_none()
            if current is not None:
                if revision > current:
                    conn.execute(update(memories).where(*key).values(revision=revision, content=content, vector=vector))
            else:
                count = len(conn.execute(select(memories.c.note_id).where(memories.c.collection_id == collection_id)).all())
                if count >= 1000:
                    raise ValueError("Collection capacity reached")
                conn.execute(insert(memories).values(collection_id=collection_id,
                    vault_id=identity.vault_id, note_id=note_id, revision=revision, content=content, vector=vector))

    def query(self, identity, vector, top_k):
        if not valid_vector(vector):
            raise ValueError("Invalid embedding")
        with self.engine.connect() as conn:
            rows = conn.execute(select(memories).join(collections).where(*self.owned(identity))).mappings().all()
        ranked = sorted(rows, key=lambda row: cosine(vector, row["vector"]), reverse=True)
        return [{"noteId": row["note_id"], "revision": row["revision"], "content": row["content"]}
                for row in ranked[:top_k]]

    def delete(self, identity, note_id):
        with self.engine.begin() as conn:
            owned_collection = select(collections.c.id).where(collections.c.user_id == identity.user_id)
            conn.execute(delete(memories).where(memories.c.collection_id.in_(owned_collection),
                memories.c.vault_id == identity.vault_id, memories.c.note_id == note_id))
