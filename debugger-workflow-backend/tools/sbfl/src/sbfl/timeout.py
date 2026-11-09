"""Cooperative deadlines for Python test bodies, including tracing overhead."""
from __future__ import annotations

import argparse
import math
import time

import pytest


def positive_seconds(value):
    try:
        seconds = float(value)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("timeout must be a positive number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return seconds


class TestDeadline:
    def __init__(self, seconds, recorder):
        self.seconds = seconds
        self.expires = time.monotonic() + seconds
        self.recorder = recorder
        self.expired = False

    def trace(self, frame, event, arg):
        if time.monotonic() >= self.expires:
            self.expired = True
            pytest.skip(f"SBFL test body exceeded {self.seconds:g} seconds")
        self.recorder.trace(frame, event, arg)
        return self.trace
