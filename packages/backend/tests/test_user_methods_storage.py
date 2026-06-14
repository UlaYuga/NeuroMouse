"""Private, per-owner storage for user-uploaded methods."""

from __future__ import annotations

import pytest

from neuromouse_backend.storage import InMemoryBackendStore, SQLiteBackendStore

_META = {
    "required_inputs": ["meta.channels"],
    "params_schema": {"title": "P", "type": "object", "properties": {}},
    "output": {"fields": [{"path": "m.rows", "description": "", "unit": None}], "panel": None},
}


def _stores():
    return [InMemoryBackendStore(), SQLiteBackendStore(path=":memory:")]


@pytest.mark.parametrize("store", _stores())
def test_upsert_and_get_is_private_per_owner(store) -> None:
    store.upsert_user_method(
        owner_id="alice", method_id="higuchi_fd", name="Higuchi FD",
        version="1.0.0", source="method = object()", metadata=_META,
    )
    got = store.get_user_method("alice", "higuchi_fd")
    assert got is not None
    assert got.name == "Higuchi FD" and got.version == "1.0.0"
    assert got.metadata["required_inputs"] == ["meta.channels"]

    # Another user cannot see Alice's private method.
    assert store.get_user_method("bob", "higuchi_fd") is None
    assert list(store.list_user_methods("bob")) == []
    assert [m.method_id for m in store.list_user_methods("alice")] == ["higuchi_fd"]


@pytest.mark.parametrize("store", _stores())
def test_upsert_replaces_same_method_id(store) -> None:
    first = store.upsert_user_method(
        owner_id="alice", method_id="m", name="v1", version="0.1.0",
        source="a", metadata=_META,
    )
    second = store.upsert_user_method(
        owner_id="alice", method_id="m", name="v2", version="0.2.0",
        source="b", metadata=_META,
    )
    assert first.id == second.id  # stable id across re-upload
    assert first.created_at == second.created_at
    methods = list(store.list_user_methods("alice"))
    assert len(methods) == 1
    assert methods[0].name == "v2" and methods[0].source == "b"


@pytest.mark.parametrize("store", _stores())
def test_delete_user_method(store) -> None:
    store.upsert_user_method(
        owner_id="alice", method_id="m", name="n", version="0",
        source="s", metadata=_META,
    )
    assert store.delete_user_method("alice", "m") is True
    assert store.delete_user_method("alice", "m") is False
    assert store.get_user_method("alice", "m") is None
