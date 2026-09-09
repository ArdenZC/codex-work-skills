"""Single source of truth for Courseware Gold speaker-script thresholds.

The hard floor is a fail-closed lower boundary.  The normal range is the
authoring target used by the Gold closure review; it is not a schema quota.
"""

GOLD_BENCHMARK_VERSION = "courseware-content-gold-benchmark-v1"
HARD_FLOOR_CHARS_PER_LECTURE_MINUTE = 80
NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE = 120
NORMAL_TARGET_MAX_CHARS_PER_LECTURE_MINUTE = 160
NEAR_FLOOR_UPPER_CHARS_PER_LECTURE_MINUTE = 96
BELOW_NORMAL_PASS_MAX_RATIO = 0.25
BELOW_NORMAL_DEGRADED_RATIO = 0.50


def script_rate(meaningful_chars: int, lecture_minutes: int) -> float | None:
    """Return meaningful characters per lecture minute for a planned page."""

    if lecture_minutes <= 0:
        return None
    return meaningful_chars / lecture_minutes
