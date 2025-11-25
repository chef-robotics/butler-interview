from __future__ import annotations

import pathlib
import sys
from datetime import datetime

from chefrobotics.butler.routes.jobs import create_size_based_batches
from chefrobotics.butler.routes.jobs import estimate_json_size


# Ensure the butler src directory is on the Python path so we can import
# the module directly
butler_src_path = (
    pathlib.Path(__file__).resolve().parents[3] / "edge" / "butler" / "src"
)
if str(butler_src_path) not in sys.path:
    sys.path.insert(0, str(butler_src_path))


def test_create_size_based_batches_splits_on_size_limit():
    """Ensure batches are split when the payload size limit is reached."""
    # Prepare two small job updates
    job_updates = [
        {"job_id": "1", "data": "x"},
        {"job_id": "2", "data": "y"},
    ]
    job_update_times = [datetime.utcnow(), datetime.utcnow()]

    # Calculate a max size that fits exactly the first job (including JSON array
    # overhead)
    max_size_bytes = estimate_json_size(job_updates[0]) + 2  # 2 bytes for []

    # Execute batching
    batches, batch_times = create_size_based_batches(
        job_updates, max_size_bytes, job_update_times
    )

    # Expect two separate batches, each containing one job update
    assert len(batches) == 2
    assert batches[0] == [job_updates[0]]
    assert batches[1] == [job_updates[1]]

    # Batch update times should correspond to the last job in each batch
    assert batch_times == [job_update_times[0], job_update_times[1]]


def _max_size_for_k_items(example_item: dict, k: int) -> int:
    """Compute max_size_bytes to allow exactly k items per batch.

    Uses the same sizing logic as create_size_based_batches:
    - Sum of item sizes
    - Plus one byte comma separators between items
    - Plus 2 bytes for enclosing JSON array []
    """
    per_item_bytes = estimate_json_size(example_item)
    return k * per_item_bytes + (k - 1) + 2


def _make_items(n: int) -> list[dict]:
    """Create n dicts of identical JSON size and stable order."""
    # Using a single-char key and single-digit values keeps size identical for 0..9
    return [{"i": i} for i in range(n)]


def _make_times(n: int) -> list[datetime]:
    return [datetime.utcnow() for _ in range(n)]


def test_correct_batch_sizes_basic():
    items = _make_items(10)
    times = _make_times(len(items))
    # Target k=3 items per batch → expect 4 batches: 3,3,3,1
    k = 3
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, batch_times = create_size_based_batches(items, max_size, times)

    sizes = [len(b) for b in batches]
    assert sizes == [3, 3, 3, 1]
    # Batch times correspond to last item in each batch
    assert batch_times == [times[2], times[5], times[8], times[9]]


def test_order_preservation():
    items = _make_items(9)
    times = _make_times(len(items))
    k = 4
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, _ = create_size_based_batches(items, max_size, times)

    flattened = [elem for batch in batches for elem in batch]
    assert flattened == items  # Exact order preserved


def test_input_output_match():
    items = _make_items(7)
    times = _make_times(len(items))
    k = 3
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, _ = create_size_based_batches(items, max_size, times)

    flattened = [elem for batch in batches for elem in batch]
    assert flattened == items


def test_edge_empty_input():
    batches, batch_times = create_size_based_batches([], 100, [])
    assert batches == []
    assert batch_times == []


def test_edge_batch_size_larger_than_input():
    items = _make_items(3)
    times = _make_times(len(items))
    # Make k much larger than input size
    k = 10
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, batch_times = create_size_based_batches(items, max_size, times)

    assert len(batches) == 1
    assert batches[0] == items
    assert batch_times == [times[-1]]


def test_edge_batch_size_one():
    items = _make_items(5)
    times = _make_times(len(items))
    k = 1
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, batch_times = create_size_based_batches(items, max_size, times)

    assert [len(b) for b in batches] == [1, 1, 1, 1, 1]
    # Each batch time is the time of its sole item
    assert batch_times == times


def test_edge_batch_size_equal_to_input():
    items = _make_items(7)
    times = _make_times(len(items))
    k = len(items)
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, batch_times = create_size_based_batches(items, max_size, times)

    assert len(batches) == 1
    assert batches[0] == items
    assert batch_times == [times[-1]]


def test_edge_not_divisible_final_batch_smaller():
    items = _make_items(10)
    times = _make_times(len(items))
    k = 4  # 10 items -> batches of 4,4,2
    max_size = _max_size_for_k_items({"i": 0}, k)

    batches, batch_times = create_size_based_batches(items, max_size, times)

    assert [len(b) for b in batches] == [4, 4, 2]
    # Batch times should be the last element's time in each batch
    assert batch_times == [times[3], times[7], times[9]]


def test_edge_single_job_exceeds_max_size(capsys):
    # Create a large item that exceeds max size
    large_item = {"i": 0, "large_field": "x" * 1000}
    items = [large_item]
    times = _make_times(len(items))
    max_size = estimate_json_size({"i": 0}) + 10
    batches, batch_times = create_size_based_batches(items, max_size, times)
    assert batches == []
    assert batch_times == []

    # verify a warning was printed (prevents silent exclusion)
    out = capsys.readouterr().out
    assert "exceeds max batch size" in out
