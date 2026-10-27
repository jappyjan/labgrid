import pytest
import subprocess
import textwrap
import threading

from labgrid.util.helper import processwrapper


def test_processwrapper_passes():
    processwrapper.check_output(["true"])


def test_processwrapper_fails():
    with pytest.raises(subprocess.CalledProcessError):
        processwrapper.check_output(["false"])


def test_processwrapper_output(tmpdir):
    content = textwrap.dedent(
        """\
        A
        B
        C
        """
    )

    tmpfile = tmpdir.join("output.txt")
    tmpfile.write(content)

    output = processwrapper.check_output(["cat", str(tmpfile)])

    assert output.decode("utf-8") == content


def test_processwrapper_input():
    content = textwrap.dedent(
        """\
        A
        B
        C
        """
    )

    output = processwrapper.check_output(["cat", "-"], input=content.encode("utf-8"))

    assert output.decode("utf-8") == content


def test_processwrapper_empty_input():
    output = processwrapper.check_output(["cat", "-"], input=b"")
    assert output.decode("utf-8") == ""


def _check_output_with_timeout(*args, timeout=10, **kwargs):
    # run in a daemon thread so a hanging check_output() fails the test
    # instead of blocking the test run forever
    result = {}

    def run():
        try:
            result["output"] = processwrapper.check_output(*args, **kwargs)
        except Exception as e:  # pylint: disable=broad-exception-caught
            result["exception"] = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"check_output() did not return within {timeout}s"
    if "exception" in result:
        raise result["exception"]
    return result["output"]


def test_processwrapper_returns_after_exit():
    # on macOS, reading the pty master returns EOF instead of raising EIO once
    # the child is gone, which must not make check_output() spin forever
    output = _check_output_with_timeout(["sh", "-c", "printf 'A\\nB\\nunterminated'"])
    assert output.decode("utf-8") == "A\nB\nunterminated"


def test_processwrapper_fails_after_exit():
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _check_output_with_timeout(["sh", "-c", "echo failed; exit 3"])
    assert excinfo.value.returncode == 3
    assert b"failed" in excinfo.value.output
