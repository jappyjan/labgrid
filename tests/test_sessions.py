"""Concurrent real CLI processes using the real coordinator and reservation queue."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import psutil


def cli(*args, check=True):
    return subprocess.run([sys.executable, "-m", "labgrid.remote.client", *args],
                          capture_output=True, text=True, timeout=15, check=check)


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    # Each run owns its port, even when another suite/coordinator runs locally.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    monkeypatch.setenv("LG_COORDINATOR", f"127.0.0.1:{port}")
    with (tmp_path / "coordinator.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "labgrid.remote.coordinator", "-l", f"127.0.0.1:{port}"],
            cwd=tmp_path, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(.05)
            yield SimpleNamespace(suspend_tree=lambda: process.send_signal(signal.SIGSTOP),
                                  resume_tree=lambda: process.send_signal(signal.SIGCONT))
        finally:
            process.send_signal(signal.SIGCONT)
            process.terminate()
            process.wait(timeout=15)


@pytest.fixture
def places(coordinator):
    for name in ("reader-a", "reader-b"):
        cli("-p", name, "create")
        cli("-p", name, "set-tags", "board=reader")
    yield
    for name in ("reader-a", "reader-b"):
        cli("-p", name, "release", "--kick", check=False)
        cli("-p", name, "delete")


def start(tmp_path, name, *, place=None, code="import time; time.sleep(60)", timeout=10):
    marker = tmp_path / f"{name}.json"
    script = ("import os,json; from pathlib import Path; "
              f"Path({str(marker)!r}).write_text(json.dumps(dict(os.environ, CHILD_PID=str(os.getpid())))); " + code)
    args = ["-p", place] if place else []
    process = subprocess.Popen(
        [sys.executable, "-m", "labgrid.remote.client", *args, "session",
         "--filter", "board=reader", "--purpose", name, "--artifacts", str(tmp_path),
         "--wait-timeout", str(timeout), "--", "python", "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process, marker


def ready(process, marker):
    deadline = time.monotonic() + 12
    while not marker.exists():
        assert process.poll() is None, process.communicate()
        assert time.monotonic() < deadline
        time.sleep(.05)
    return json.loads(marker.read_text())


def stop(process):
    if process.poll() is None:
        process.terminate()
    return process.communicate(timeout=12)


def assert_free():
    for name in ("reader-a", "reader-b"):
        assert "acquired: None" in cli("-p", name, "show").stdout
    assert not cli("reservations").stdout.strip()


def test_parallel_sessions_queue_and_identity(places, tmp_path):
    first, marker = start(tmp_path, "first", place="reader-a")
    processes = [first]
    try:
        identity = ready(first, marker)
        # Same host/user outside the session cannot borrow or release its claim.
        assert cli("-p", "reader-a", "release", check=False).returncode == 1
        second, marker2 = start(tmp_path, "second", place="reader-a")
        processes.append(second)
        third, marker3 = start(tmp_path, "third")
        processes.append(third)
        other = ready(third, marker3)
        assert other["LG_PLACE"] == "reader-b"
        assert identity["LG_USERNAME"] != other["LG_USERNAME"]
        assert identity["LG_ARTIFACTS"] != other["LG_ARTIFACTS"]
        assert not marker2.exists()
        stop(first)
        queued = ready(second, marker2)
        assert queued["LG_PLACE"] == "reader-a"
        assert queued["LG_USERNAME"] != identity["LG_USERNAME"]
    finally:
        for process in processes:
            stop(process)
    assert_free()


@pytest.mark.parametrize("outcome", ["success", "failure", "sigint", "sigterm", "claim-lost"])
def test_session_lifecycle(places, tmp_path, outcome):
    code = "raise SystemExit(7)" if outcome == "failure" else "pass" if outcome == "success" else "import time; time.sleep(60)"
    process, marker = start(tmp_path, outcome, place="reader-a", code=code)
    try:
        env = ready(process, marker)
        if outcome in ("sigint", "sigterm"):
            process.send_signal(signal.SIGINT if outcome == "sigint" else signal.SIGTERM)
        elif outcome == "claim-lost":
            cli("-p", "reader-a", "release", "--kick")
        stdout, stderr = process.communicate(timeout=15)
        expected = {"success": 0, "failure": 7, "sigint": 130, "sigterm": 143}
        if outcome in expected:
            assert process.returncode == expected[outcome], (stdout, stderr)
        else:
            assert process.returncode != 0
        assert not psutil.pid_exists(int(env["CHILD_PID"]))
        metadata = json.loads((Path(env["LG_ARTIFACTS"]) / "session.json").read_text())
        assert metadata["purpose"] == outcome
        assert metadata["state"] == "finished"
    finally:
        stop(process)
    assert_free()


def test_killed_parent_requires_explicit_recovery(places, tmp_path):
    process, marker = start(tmp_path, "killed", place="reader-a")
    env = ready(process, marker)
    try:
        process.kill()
        process.wait(timeout=5)
        assert env["LG_USERNAME"] in cli("-p", "reader-a", "show").stdout
        contender, marker2 = start(tmp_path, "blocked", place="reader-a", timeout=.5)
        contender.communicate(timeout=15)
        assert contender.returncode == 1
        assert not marker2.exists()
    finally:
        # Deliberate operator recovery stops the orphaned operation first.
        os.killpg(int(env["CHILD_PID"]), signal.SIGKILL)
        cli("cancel-reservation", env["LG_TOKEN"])
        cli("-p", "reader-a", "release", "--kick")
        process.communicate(timeout=10)
    assert_free()


def test_wait_timeout_cleans_reservation_without_releasing_owner(places, tmp_path):
    first, marker = start(tmp_path, "owner", place="reader-a")
    try:
        env = ready(first, marker)
        second, marker2 = start(tmp_path, "timeout", place="reader-a", timeout=.5)
        stdout, stderr = second.communicate(timeout=15)
        assert second.returncode == 1, (stdout, stderr)
        assert "timed out" in stderr
        assert not marker2.exists()
        assert env["LG_USERNAME"] in cli("-p", "reader-a", "show").stdout
        # The timed out request is gone; the owner's reservation remains.
        assert cli("reservations").stdout.count("Reservation '") == 1
    finally:
        stop(first)
    assert_free()


def test_interrupt_during_cleanup_still_releases(places, coordinator, tmp_path):
    process, marker = start(tmp_path, "cleanup-interrupt", place="reader-a",
                            code="import time; time.sleep(.5)")
    ready(process, marker)
    try:
        # Child finishes while cleanup's coordinator RPC cannot complete.
        coordinator.suspend_tree()
        time.sleep(1)
        assert process.poll() is None
        process.terminate()
    finally:
        coordinator.resume_tree()
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode == 143, (stdout, stderr)
    assert_free()
