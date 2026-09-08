"""S3.3 PASS-WHEN: curriculum coverage status derivation unit tests (pure)."""

from bangla_gpt_api.services import coverage


def test_avg_of() -> None:
    assert coverage.avg_of([]) is None
    assert coverage.avg_of([80.0]) == 80.0
    assert coverage.avg_of([69.0, 71.0]) == 70.0
    assert coverage.avg_of([83.333, 90.0]) == 86.67


def test_mastered_requires_practice_and_threshold() -> None:
    # practiced + avg >= 70 -> mastered (exactly at threshold counts)
    assert coverage.derive_status(True, True, 70.0) == "mastered"
    assert coverage.derive_status(False, True, 95.5) == "mastered"
    # just below threshold -> practiced, not mastered
    assert coverage.derive_status(True, True, 69.9) == "practiced"


def test_practiced_without_graded_average_stays_practiced() -> None:
    # attempts exist but nothing graded yet (avg None) -> practiced
    assert coverage.derive_status(True, True, None) == "practiced"
    assert coverage.derive_status(False, True, None) == "practiced"
    # low average is still "practiced" (needs work), never "taught"
    assert coverage.derive_status(True, True, 12.0) == "practiced"


def test_taught_and_uncovered_precedence() -> None:
    # taught but never practiced
    assert coverage.derive_status(True, False, None) == "taught"
    # attempts without any assignment still count as practiced
    assert coverage.derive_status(False, True, 55.0) == "practiced"
    # neither
    assert coverage.derive_status(False, False, None) == "uncovered"


def test_threshold_is_configurable() -> None:
    assert coverage.derive_status(False, True, 65.0, mastered_min=60.0) == "mastered"
    assert coverage.derive_status(False, True, 65.0, mastered_min=70.0) == "practiced"


def test_is_taught_assignment_sources() -> None:
    # content alone teaches the subject
    assert coverage.is_taught(True, set(), "math")
    # exact per-subject ClassTeacher assignment
    assert coverage.is_taught(False, {"math"}, "math")
    # other-subject assignment does NOT cover it
    assert not coverage.is_taught(False, {"bangla"}, "math")
    # '' marker = assigned to all subjects for the class
    assert coverage.is_taught(False, {""}, "math")
    assert not coverage.is_taught(False, set(), "math")
