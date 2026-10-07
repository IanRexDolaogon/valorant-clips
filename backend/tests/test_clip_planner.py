import pytest

from app.services.clip_planner import window


@pytest.mark.parametrize("kill,offset,duration,before,after,expected", [
    (5000, 2000, 10000, 3000, 2000, (4000, 9000)),
    (5000, -4000, 10000, 3000, 2000, (0, 3000)),
    (0, 0, 10000, 3000, 2000, (0, 2000)),
    (9000, 0, 10000, 3000, 2000, (6000, 10000)),
    (1000, -2000, 10000, 3000, 2000, None),
    (10000, 0, 10000, 3000, 2000, None),
    (0, 0, 0, 3000, 2000, None),
])
def test_window_handles_offsets_and_recording_boundaries(kill, offset, duration, before, after, expected):
    assert window(kill, offset, duration, before, after) == expected


def test_window_rejects_invalid_padding():
    with pytest.raises(ValueError):
        window(1000, 0, 5000, -1, 1000)
