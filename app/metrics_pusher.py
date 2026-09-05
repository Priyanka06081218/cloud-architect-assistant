# app/metrics_pusher.py
#
# Minimal Prometheus remote_write encoder.
# Pushes metrics to Grafana Cloud without any protobuf library —
# the wire format is encoded directly in Python.
#
# Prometheus remote_write proto schema (the only fields we need):
#
#   WriteRequest  { repeated TimeSeries timeseries = 1; }
#   TimeSeries    { repeated Label labels = 1; repeated Sample samples = 2; }
#   Label         { string name = 1; string value = 2; }
#   Sample        { double value = 1; int64 timestamp_ms = 2; }

import struct
import time
import logging
import requests

log = logging.getLogger(__name__)



def _varint(n: int) -> bytes:
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _field_len(num: int, data: bytes) -> bytes:
    """Wire type 2 (length-delimited)."""
    tag = _varint((num << 3) | 2)
    return tag + _varint(len(data)) + data


def _field_64(num: int, value: float) -> bytes:
    """Wire type 1 (64-bit / double)."""
    tag = _varint((num << 3) | 1)
    return tag + struct.pack("<d", value)


def _field_varint(num: int, value: int) -> bytes:
    """Wire type 0 (varint / int64)."""
    tag = _varint((num << 3) | 0)
    # Handle negative int64 as unsigned 64-bit
    if value < 0:
        value = value + (1 << 64)
    return tag + _varint(value)


def _encode_label(name: str, value: str) -> bytes:
    n = name.encode()
    v = value.encode()
    return _field_len(1, n) + _field_len(2, v)


def _encode_sample(value: float, ts_ms: int) -> bytes:
    return _field_64(1, value) + _field_varint(2, ts_ms)


def _encode_timeseries(labels: dict, value: float, ts_ms: int) -> bytes:
    msg = b""
    for k, v in sorted(labels.items()):
        msg += _field_len(1, _encode_label(k, v))
    msg += _field_len(2, _encode_sample(value, ts_ms))
    return msg


def _encode_write_request(ts_list: list[bytes]) -> bytes:
    msg = b""
    for ts in ts_list:
        msg += _field_len(1, ts)
    return msg



def push_metrics(metric_families, url: str, username: str, token: str) -> None:
    """Push Prometheus metric families to Grafana Cloud remote_write."""
    try:
        import snappy
    except ImportError:
        log.warning("python-snappy not available; skipping push")
        return

    ts_ms = int(time.time() * 1000)
    ts_list: list[bytes] = []

    for family in metric_families:
        for sample in family.samples:
            v = sample.value
            if v != v:          # skip NaN
                continue
            labels = dict(sample.labels)
            labels["__name__"] = sample.name
            ts_list.append(_encode_timeseries(labels, v, ts_ms))

    if not ts_list:
        return

    body = snappy.compress(_encode_write_request(ts_list))
    resp = requests.post(
        url,
        data=body,
        headers={
            "Content-Type":    "application/x-protobuf",
            "Content-Encoding": "snappy",
            "X-Prometheus-Remote-Write-Version": "0.1.0",
        },
        auth=(username, token),
        timeout=10,
    )
    resp.raise_for_status()
    log.info(f"Grafana push OK ({len(ts_list)} series)")
