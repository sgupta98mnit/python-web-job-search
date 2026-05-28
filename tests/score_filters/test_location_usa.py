import pytest

from score_filters.location_usa import is_usa_location


@pytest.mark.parametrize(
    "location",
    [
        "San Francisco, CA",
        "New York, NY",
        "Remote - US",
        "Remote (US)",
        "Austin, Texas",
        "United States",
        "USA",
        "Seattle, WA, USA",
        "Boston, Massachusetts",
        "Washington, D.C.",
        "Buffalo, NY",
    ],
)
def test_clearly_us(location):
    assert is_usa_location(location, remote=False) is True


@pytest.mark.parametrize(
    "location",
    [
        "Bangalore, India",
        "Hyderabad, India",
        "Toronto, ON, Canada",
        "Vancouver, BC",
        "London, UK",
        "Dublin, Ireland",
        "Berlin, Germany",
        "Singapore",
        "Sydney, Australia",
        "Sao Paulo, Brazil",
        "Mexico City, Mexico",
        "Remote - EMEA",
        "Remote (India)",
        "Tokyo, Japan",
    ],
)
def test_clearly_non_us(location):
    assert is_usa_location(location, remote=False) is False


@pytest.mark.parametrize(
    "location,remote",
    [
        ("", False),
        ("", True),
        ("Remote", True),
        ("Earth", False),
        ("Anywhere", True),
    ],
)
def test_ambiguous(location, remote):
    assert is_usa_location(location, remote=remote) is None


def test_state_abbrev_not_word_substring():
    # "scan" contains "ca" but the abbrev regex requires comma/space delimiter.
    assert is_usa_location("scan group", remote=False) is None
