import datetime as dt

import pytest

from vrgb_suite import sun

UTC = dt.timezone.utc


def test_settings_validates_and_clamps():
    s = sun.settings({"idle_timeout_seconds": "9999", "latitude": "95", "longitude": 10, "idle_enabled": 0})
    assert s["idle_timeout_seconds"] == 600
    assert s["latitude"] == 90.0
    assert s["idle_enabled"] is False


def test_settings_drops_bad_location():
    s = sun.settings({"latitude": "north", "longitude": 1})
    assert s["latitude"] is None and s["longitude"] is None


def test_equator_equinox_has_twelve_hour_day():
    rise, sett = sun.sun_times(0.0, 0.0, dt.date(2026, 3, 20))
    hours = (sett - rise).total_seconds() / 3600
    assert hours == pytest.approx(12.1, abs=0.15)
    assert rise.astimezone(UTC).hour == 6


@pytest.mark.parametrize("date,expected", [(dt.date(2026, 6, 21), True), (dt.date(2026, 12, 21), False)])
def test_polar_day_and_night(date, expected):
    assert sun.sun_times(78.2, 15.6, date) is expected  # Svalbard


def test_is_daytime():
    assert sun.is_daytime(0.0, 0.0, dt.datetime(2026, 3, 20, 12, tzinfo=UTC))
    assert not sun.is_daytime(0.0, 0.0, dt.datetime(2026, 3, 20, 23, tzinfo=UTC))


def test_day_off_requires_location_and_option():
    noon = dt.datetime(2026, 3, 20, 12, tzinfo=UTC)
    assert not sun.day_off_active({"day_off_enabled": True}, noon)
    assert not sun.day_off_active({"latitude": 0, "longitude": 0}, noon)
    assert sun.day_off_active({"day_off_enabled": True, "latitude": 0, "longitude": 0}, noon)
