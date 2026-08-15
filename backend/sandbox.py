"""
backend/sandbox.py
──────────────────
Execution sandbox for LLM-generated Pandas code.

Two implementations are provided:

┌────────────────────────┬──────────────────────────────────────────────────────┐
│ Class                  │ When to use                                          │
├────────────────────────┼──────────────────────────────────────────────────────┤
│ DockerSandbox          │ Production — full isolation via Docker               │
│ LocalSubprocessSandbox │ Dev fallback — subprocess, no Docker required        │
└────────────────────────┴──────────────────────────────────────────────────────┘

The module-level ``get_sandbox()`` factory auto-selects the right implementation:
it tries to contact the Docker daemon and falls back to ``LocalSubprocessSandbox``
if Docker is unavailable, logging a clear warning.

Dataset Versioning
──────────────────
Sandbox execution is *immutable*: the input CSV (``data_v0.csv``) is never
overwritten. Instead, the generated code writes to a fresh ``output.csv``
inside the ephemeral work directory. After execution succeeds and passes the
row-drop guardrail, the output is promoted to ``data_v{N+1}.csv`` in the
original session directory.

Hard Guardrail — Row-Drop Protection
─────────────────────────────────────
After successful execution, the sandbox compares the row counts of the input
and output CSVs. If the output has fewer than 80 % of the input's rows, the
output is deleted and a ``DataDestructionError`` is returned. This prevents
accidental or malicious mass row deletion by LLM-generated code.

DockerSandbox security model
────────────────────────────
┌─────────────────────────────────────────────────────────────────────┐
│ Constraint            │ Enforcement                                  │
├───────────────────────┼──────────────────────────────────────────────┤
│ No network access     │ network_mode="none"                          │
│ Memory cap            │ mem_limit="256m"                             │
│ CPU cap               │ nano_cpus=1_000_000_000  (1 vCPU)           │
│ Wall-clock timeout    │ threading.Timer → container.stop() / kill() │
│ Ephemeral filesystem  │ tempfile.mkdtemp() + shutil.rmtree (finally)│
│ No host-process exec  │ Docker container isolation                   │
│ Read-only image layer │ writable bind-mount limited to /sandbox      │
│ Row-drop guardrail    │ >20 % row loss → output deleted, error       │
└─────────────────────────────────────────────────────────────────────┘

Usage
─────
    from backend.sandbox import get_sandbox

    sandbox = get_sandbox()          # auto-selects Docker or subprocess
    result  = sandbox.run(python_code="print(df.shape)", csv_path="/session/data_v0.csv")

    # result == {
    #     "success": True,
    #     "stdout": "(1000, 9)\\n",
    #     "stderr": "",
    #     "new_csv_path": "/session/data_v1.csv",
    # }
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import pandas as pd

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Shared constants ───────────────────────────────────────────────────────────

# Path *inside* the Docker container where the temp dir is mounted.
_CONTAINER_WORKDIR = "/sandbox"

_INPUT_CSV_NAME  = "input.csv"
_OUTPUT_CSV_NAME = "output.csv"
_SCRIPT_NAME     = "script.py"

# If the output CSV has fewer than this fraction of input rows, block the write.
_ROW_DROP_THRESHOLD = 0.8

# Regex to extract the version index from filenames like ``data_v0.csv``.
_VERSION_RE = re.compile(r"data_v(\d+)\.csv$", re.IGNORECASE)


# ── Version helpers ────────────────────────────────────────────────────────────


def _parse_version(csv_path: str) -> tuple[int, int, str]:
    """
    Extract the version index from a ``data_v{N}.csv`` filename.

    Returns
    -------
    (current_version, next_version, next_filename)

    Falls back to ``(0, 1, "data_v1.csv")`` when the pattern does not match.
    """
    basename = os.path.basename(csv_path)
    match = _VERSION_RE.search(basename)
    if match:
        current = int(match.group(1))
    else:
        current = 0
    next_ver = current + 1
    return current, next_ver, f"data_v{next_ver}.csv"


def _check_row_guardrail(
    input_csv: str,
    output_csv: str,
) -> dict | None:
    """
    Hard guardrail: compare row counts between the input and output CSVs.

    If the output has fewer than ``_ROW_DROP_THRESHOLD`` (80 %) of the input
    rows, delete the output CSV and return a failure result dict.

    Returns ``None`` if the guardrail passes.
    """
    try:
        input_rows = len(pd.read_csv(input_csv))
        output_rows = len(pd.read_csv(output_csv))
    except Exception as exc:
        logger.warning("Row-guardrail CSV read failed: %s", exc)
        return None  # cannot enforce — let the result through

    if input_rows > 0 and output_rows < (_ROW_DROP_THRESHOLD * input_rows):
        logger.warning("Guardrail Triggered: Output blocked due to destructive row drop.")
        logger.warning(
            "Row-drop guardrail triggered: input=%d, output=%d (threshold=%.0f%%)",
            input_rows,
            output_rows,
            _ROW_DROP_THRESHOLD * 100,
        )
        try:
            os.remove(output_csv)
        except OSError:
            pass
        return {
            "success": False,
            "stdout": "",
            "stderr": (
                "DataDestructionError: The LLM attempted to drop more than 20% "
                "of the dataset rows. Operation blocked."
            ),
            "new_csv_path": "",
        }

    return None


# ── Sandbox protocol (structural typing) ──────────────────────────────────────

@runtime_checkable
class Sandbox(Protocol):
    """Structural interface satisfied by both sandbox implementations."""

    def run(self, python_code: str, csv_path: str) -> dict:
        """
        Execute *python_code* against the CSV at *csv_path*.

        Returns
        -------
        dict with keys:
            ``success``      — bool, True iff execution completed without error.
            ``stdout``       — str, captured stdout.
            ``stderr``       — str, captured stderr / error message.
            ``new_csv_path`` — str, absolute path to the versioned output CSV
                               (empty string on failure).
        """
        ...


# ── LocalSubprocessSandbox ─────────────────────────────────────────────────────


class LocalSubprocessSandbox:
    """
    Development fallback sandbox — runs generated code in a child subprocess
    using the current Python interpreter.

    ⚠️  No network isolation or memory caps.  Use only during local development
    when Docker Desktop is unavailable.  Switch to ``DockerSandbox`` in production.
    """

    TIMEOUT_SEC: int = 10

    def run(self, python_code: str, csv_path: str) -> dict:
        """
        Write *python_code* to a temp script, copy the CSV in, run it via
        subprocess, check the row-drop guardrail, and promote the output to
        the next version in the session directory.
        """
        if not os.path.isfile(csv_path):
            return self._error_result(f"Input CSV not found: {csv_path}")

        _current_ver, _next_ver, next_filename = _parse_version(csv_path)
        session_dir = os.path.dirname(csv_path)

        tempdir: Optional[str] = None
        try:
            tempdir = tempfile.mkdtemp(prefix="datify_dev_")

            # Copy the CSV into the temp dir as the fixed input name.
            host_input_csv = os.path.join(tempdir, _INPUT_CSV_NAME)
            host_output_csv = os.path.join(tempdir, _OUTPUT_CSV_NAME)
            shutil.copy2(csv_path, host_input_csv)

            # Build the script — reads input.csv, writes output.csv.
            preamble = textwrap.dedent(
                f"""\
                import pandas as pd
                import numpy as np

                csv_path = r"{host_input_csv}"
                df = pd.read_csv(csv_path)
                """
            )
            postamble = textwrap.dedent(
                f"""\

                # ── Auto-save ──────────────────────────────────────────────
                if isinstance(df, pd.DataFrame):
                    df.to_csv(r"{host_output_csv}", index=False)
                """
            )

            script_path = os.path.join(tempdir, _SCRIPT_NAME)
            Path(script_path).write_text(
                preamble + python_code + postamble, encoding="utf-8"
            )

            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SEC,
            )

            success = result.returncode == 0

            if not success:
                return {
                    "success": False,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "new_csv_path": "",
                }

            # ── Row-drop guardrail ─────────────────────────────────────────
            if os.path.isfile(host_output_csv):
                guardrail_fail = _check_row_guardrail(host_input_csv, host_output_csv)
                if guardrail_fail is not None:
                    return guardrail_fail

                # Promote the output to the session directory.
                new_csv_path = os.path.join(session_dir, next_filename)
                shutil.copy2(host_output_csv, new_csv_path)
            else:
                # Script ran but produced no output file — keep input as-is.
                new_csv_path = csv_path

            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "new_csv_path": new_csv_path,
            }

        except subprocess.TimeoutExpired:
            logger.error(
                f"Sandbox Error: Execution crashed - Timed out after {self.TIMEOUT_SEC}s."
            )
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    f"[LocalSubprocessSandbox] Execution timed out after "
                    f"{self.TIMEOUT_SEC}s."
                ),
                "new_csv_path": "",
            }
        except Exception as exc:
            logger.error(f"Sandbox Error: Execution crashed - {str(exc)}")
            return self._error_result(f"Unexpected sandbox error: {exc}")
        finally:
            if tempdir is not None:
                shutil.rmtree(tempdir, ignore_errors=True)

    @staticmethod
    def _error_result(message: str) -> dict:
        logger.error("LocalSubprocessSandbox error: %s", message)
        return {"success": False, "stdout": "", "stderr": message, "new_csv_path": ""}


# ── DockerSandbox ──────────────────────────────────────────────────────────────


class DockerSandbox:
    """
    Production sandbox — spins up an ephemeral ``datify-sandbox:latest``
    container, mounts a temporary host directory as ``/sandbox``, copies the
    input CSV, executes the supplied Pandas script, and returns structured output.

    Parameters
    ----------
    image:
        Docker image to use.  Must have ``pandas`` and ``numpy`` installed.
    mem_limit:
        Docker memory limit string (e.g. ``"256m"``).
    timeout_sec:
        Seconds before the container is force-stopped.
    """

    def __init__(
        self,
        image: Optional[str] = None,
        mem_limit: Optional[str] = None,
        timeout_sec: Optional[int] = None,
    ) -> None:
        self.image       = image       or settings.SANDBOX_IMAGE
        self.mem_limit   = mem_limit   or settings.SANDBOX_MEM_LIMIT
        self.timeout_sec = timeout_sec if timeout_sec is not None else settings.SANDBOX_TIMEOUT_SEC

        # Lazily initialised — avoids hard crash at import time if daemon is down.
        self._client = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, python_code: str, csv_path: str) -> dict:
        """
        Execute *python_code* inside an isolated Docker container.

        The generated code may reference:
            - ``df``       — ``pd.DataFrame`` pre-loaded from the input CSV.
            - ``csv_path`` — container-side path to ``input.csv``.
            - ``pd``       — pandas module.
            - ``np``       — numpy module.

        Mutations to ``df`` are written to a *new* versioned CSV via the
        bind mount. The original input CSV is never overwritten.

        Returns
        -------
        dict with keys: ``success`` (bool), ``stdout`` (str), ``stderr`` (str),
        ``new_csv_path`` (str).
        """
        # Lazy import — keeps the module importable even when docker SDK is absent.
        try:
            import docker
            import docker.errors
            from docker.models.containers import Container as _Container
        except ImportError:
            return self._error_result(
                "The 'docker' Python SDK is not installed. "
                "Run: pip install docker"
            )

        if not os.path.isfile(csv_path):
            return self._error_result(f"Input CSV not found on host: {csv_path}")

        _current_ver, _next_ver, next_filename = _parse_version(csv_path)
        session_dir = os.path.dirname(csv_path)

        tempdir   = None
        container = None
        timer     = None
        timed_out = threading.Event()

        try:
            client = self._get_client()

            # 1. Ephemeral temp directory on the host.
            tempdir = tempfile.mkdtemp(prefix="datify_sandbox_")
            logger.debug("Created sandbox tempdir: %s", tempdir)

            # 2. Copy CSV into the temp dir as the fixed input name.
            host_input_csv = os.path.join(tempdir, _INPUT_CSV_NAME)
            host_output_csv = os.path.join(tempdir, _OUTPUT_CSV_NAME)
            shutil.copy2(csv_path, host_input_csv)

            # 3. Assemble the full script — reads input.csv, writes output.csv.
            container_input = f"{_CONTAINER_WORKDIR}/{_INPUT_CSV_NAME}"
            container_output = f"{_CONTAINER_WORKDIR}/{_OUTPUT_CSV_NAME}"

            preamble = textwrap.dedent(
                f"""\
                import pandas as pd
                import numpy as np

                csv_path = "{container_input}"
                df = pd.read_csv(csv_path)
                """
            )
            postamble = textwrap.dedent(
                f"""\

                # ── Auto-save ────────────────────────────────────────────────────────────
                if isinstance(df, pd.DataFrame):
                    df.to_csv("{container_output}", index=False)
                """
            )

            full_script = preamble + python_code + postamble
            host_script = os.path.join(tempdir, _SCRIPT_NAME)
            Path(host_script).write_text(full_script, encoding="utf-8")

            logger.debug("Launching sandbox container (image=%s)", self.image)

            # 4. Launch container — detached so the kill-timer can reach it.
            container = client.containers.run(
                image=self.image,
                command=["python", f"{_CONTAINER_WORKDIR}/{_SCRIPT_NAME}"],
                volumes={tempdir: {"bind": _CONTAINER_WORKDIR, "mode": "rw"}},
                # ── Security constraints ────────────────────────────────────
                network_mode="none",
                mem_limit=self.mem_limit,
                memswap_limit=self.mem_limit,   # disables swap
                nano_cpus=1_000_000_000,        # 1 vCPU hard cap
                user="1000:1000",
                read_only=True,
                # ── Lifecycle ───────────────────────────────────────────────
                remove=False,   # we remove manually after reading logs
                detach=True,
                stdout=True,
                stderr=True,
            )

            # 5. Arm the wall-clock timeout.
            def _timeout_handler() -> None:
                timed_out.set()
                logger.warning(
                    "Sandbox timeout (%ss) exceeded — stopping container %s",
                    self.timeout_sec, container.short_id,
                )
                try:
                    container.stop(timeout=2)
                except Exception:
                    try:
                        container.kill()
                    except Exception:
                        pass

            timer = threading.Timer(self.timeout_sec, _timeout_handler)
            timer.start()

            # 6. Block until the container finishes (or is killed by the timer).
            exit_code = container.wait()["StatusCode"]
            timer.cancel()

            # 7. Collect output.
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            if timed_out.is_set():
                return {
                    "success": False,
                    "stdout": stdout,
                    "stderr": (
                        f"[DockerSandbox] Execution timed out after {self.timeout_sec}s "
                        f"and the container was forcibly stopped.\n{stderr}"
                    ).strip(),
                    "new_csv_path": "",
                }

            if exit_code != 0:
                return {
                    "success": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "new_csv_path": "",
                }

            # 8. Row-drop guardrail & version promotion.
            if os.path.isfile(host_output_csv):
                guardrail_fail = _check_row_guardrail(host_input_csv, host_output_csv)
                if guardrail_fail is not None:
                    return guardrail_fail

                new_csv_path = os.path.join(session_dir, next_filename)
                shutil.copy2(host_output_csv, new_csv_path)
            else:
                # Script ran but produced no output file — keep input as-is.
                new_csv_path = csv_path

            logger.debug("Sandbox exited (code=%s, success=True)", exit_code)
            return {
                "success": True,
                "stdout": stdout,
                "stderr": stderr,
                "new_csv_path": new_csv_path,
            }

        except Exception as exc:
            # Catch docker.errors.ImageNotFound, DockerException, etc.
            err_type = type(exc).__name__
            msg = f"[DockerSandbox] {err_type}: {exc}"
            if "ImageNotFound" in err_type:
                msg = (
                    f"Docker image '{self.image}' not found. "
                    f"Build it with: docker build -t {self.image} ./backend"
                )
            logger.error(f"Sandbox Error: Execution crashed - {str(exc)}")
            return self._error_result(msg)

        finally:
            if timer is not None and timer.is_alive():
                timer.cancel()
            if container is not None:
                try:
                    container.remove(force=True)
                    logger.debug("Sandbox container removed.")
                except Exception:
                    pass
            if tempdir is not None:
                self._cleanup(tempdir)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    @staticmethod
    def _error_result(message: str) -> dict:
        logger.error("DockerSandbox error: %s", message)
        return {"success": False, "stdout": "", "stderr": message, "new_csv_path": ""}

    @staticmethod
    def _cleanup(tempdir: str) -> None:
        try:
            shutil.rmtree(tempdir, ignore_errors=True)
            logger.debug("Cleaned up sandbox tempdir: %s", tempdir)
        except Exception as exc:
            logger.warning("Failed to clean up tempdir %s: %s", tempdir, exc)


# ── Factory ────────────────────────────────────────────────────────────────────


def get_sandbox() -> DockerSandbox | LocalSubprocessSandbox:
    """
    Return the best available sandbox for the current environment.

    Priority:
    1. ``DockerSandbox``          — if Docker daemon is reachable.
    2. ``LocalSubprocessSandbox`` — fallback for local development.
    """
    try:
        import docker
        client = docker.from_env()
        client.ping()
        logger.info("Docker daemon reachable — using DockerSandbox.")
        return DockerSandbox()
    except Exception as exc:
        logger.warning(
            "Docker unavailable (%s) — falling back to LocalSubprocessSandbox. "
            "This is NOT suitable for production.",
            exc,
        )
        return LocalSubprocessSandbox()
