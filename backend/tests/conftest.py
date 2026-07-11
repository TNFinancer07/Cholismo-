"""Test bootstrap — isolate the event store BEFORE any app import.

The store is a module-level singleton keyed on EVENT_DB_PATH at first use: the env var
must be set before `app.*` modules are imported by the test session.
"""
import os
import tempfile

os.environ["EVENT_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="cholismo-test-"),
                                           "events.db")
