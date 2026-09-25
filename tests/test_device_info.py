from calpi.system import device_info as di


def test_decode_throttled():
    assert not any(di.decode_throttled("0x0").values())
    f = di.decode_throttled("0x50005")
    assert f["undervoltage_now"] and f["throttled_now"] and f["undervoltage_past"] and f["throttled_past"]
    assert not f["freq_capped_now"]
    f = di.decode_throttled("0x80000")
    assert f["soft_temp_limit_past"] and not f["undervoltage_now"]
    assert not any(di.decode_throttled("garbage").values())


def test_power_codes():
    assert di.power_codes(di.decode_throttled("0x50005")) == (["POWER_UNDERVOLTAGE"], [])
    assert di.power_codes(di.decode_throttled("0x50000")) == ([], ["POWER_THROTTLED_PAST"])
    assert di.power_codes(di.decode_throttled("0x0")) == ([], [])
    assert di.power_codes(di.decode_throttled("0x8")) == (["TEMP_HIGH"], [])


def test_parsers():
    assert di.parse_measure_temp("temp=48.3'C\n") == 48.3
    assert di.parse_measure_temp("") is None
    assert di.parse_throttled_output("throttled=0x50005") == 0x50005
    assert di.parse_throttled_output("error") is None


def test_collect_without_vcgencmd(monkeypatch):
    monkeypatch.setattr(di, "_vcgencmd", lambda *a: None)
    info = di.collect("/")
    assert not info.power_known and info.temp_c is None and not info.undervoltage_now
    assert info.disk_free is not None


def test_thresholds():
    assert di.DeviceInfo(temp_c=81.0).temp_high and not di.DeviceInfo(temp_c=70).temp_high
    assert di.DeviceInfo(disk_free=100 * 1024 * 1024).disk_low
