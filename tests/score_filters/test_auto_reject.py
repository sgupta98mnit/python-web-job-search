from score_filters.auto_reject import auto_reject_reason


def _call(**overrides):
    base = dict(
        is_job=True,
        score=80,
        location="San Francisco, CA",
        remote=False,
        min_score=35,
        enforce_usa=True,
    )
    base.update(overrides)
    return auto_reject_reason(**base)


def test_us_high_score_passes():
    assert _call() is None


def test_low_score_tagged():
    assert _call(score=20) == "low_score"


def test_non_usa_tagged():
    assert _call(location="Bangalore, India") == "non_usa_location"


def test_both_tags_joined():
    tags = _call(score=10, location="London, UK")
    assert tags is not None
    parts = set(tags.split(","))
    assert parts == {"low_score", "non_usa_location"}


def test_is_job_false_skipped():
    # Non-job rows are handled elsewhere; we don't add tags to them.
    assert _call(is_job=False, score=10, location="London, UK") is None


def test_enforce_usa_off_ignores_location():
    assert _call(location="Bangalore, India", enforce_usa=False) is None


def test_ambiguous_location_not_rejected():
    assert _call(location="Remote", remote=True) is None
