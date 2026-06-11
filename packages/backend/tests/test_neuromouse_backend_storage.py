from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from neuromouse_backend.storage import SQLiteBackendStore


def dataset_for(channel_count: int, frequency_count: int, time_count: int) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    frequencies = [float(8 + index) for index in range(frequency_count)]
    psd = [
        [
            float((channel_index + 1) * (frequency_index + 1))
            for frequency_index in range(frequency_count)
        ]
        for channel_index in range(channel_count)
    ]
    time = [float(index) for index in range(time_count)]
    values = [
        [float(channel_index + index) for index in range(time_count)]
        for channel_index in range(channel_count)
    ]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {"frequencies": frequencies, "psd": psd},
        "centroid": {"time_relative": time, "values": values},
        "geometry": {"time": time},
    }


@given(
    name=st.one_of(st.none(), st.text(alphabet=st.characters(max_codepoint=126), max_size=24)),
    channel_count=st.integers(min_value=1, max_value=6),
    frequency_count=st.integers(min_value=1, max_value=6),
    time_count=st.integers(min_value=1, max_value=6),
    method_id=st.text(
        alphabet=st.characters(min_codepoint=48, max_codepoint=122),
        min_size=1,
        max_size=24,
    ),
)
@settings(max_examples=40, deadline=None, derandomize=True)
def test_sqlite_store_crud_round_trips_sessions_dataset_versions_jobs_and_events(
    name: str | None,
    channel_count: int,
    frequency_count: int,
    time_count: int,
    method_id: str,
) -> None:
    dataset = dataset_for(channel_count, frequency_count, time_count)
    result = {"method": method_id, "channels": channel_count}

    with tempfile.TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "backend.sqlite3"
        store = SQLiteBackendStore(db_path)
        session = store.create_session(name=name, dataset=dataset)
        assert session.dataset_version == 1
        assert store.get_session(session.id) == session
        assert list(store.list_sessions()) == [session]

        job = store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id=method_id,
            params={"frequency_count": frequency_count},
        )
        assert job.status == "queued"
        assert job.events[0]["status"] == "queued"

        store.append_job_event(job.id, status="running")
        completed = store.append_job_event(job.id, status="completed", result=result)
        assert completed.result == result
        assert [event["status"] for event in completed.events] == ["queued", "running", "completed"]
        store.close()

        reopened = SQLiteBackendStore(db_path)
        assert reopened.get_session(session.id) == session
        assert reopened.get_job(job.id) == completed
        reopened.close()
