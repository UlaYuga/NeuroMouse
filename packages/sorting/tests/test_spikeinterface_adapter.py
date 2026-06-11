from __future__ import annotations

import pytest


def test_spikeinterface_adapter_is_import_guarded() -> None:
    pytest.importorskip("spikeinterface", reason="SpikeInterface is optional")

    from neuromouse_sorting.spikeinterface_adapter import SpikeInterfaceSorter

    sorter = SpikeInterfaceSorter(sorter_name="kilosort4")

    assert sorter.available
    assert sorter.name == "spikeinterface:kilosort4"
