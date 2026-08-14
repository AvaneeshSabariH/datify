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
└─────────────────────────────────────────────────────────────────────┘

Usage
─────
    from backend.sandbox import get_sandbox

    sandbox = get_sandbox()          # auto-selects Docker or subprocess
    result  = sandbox.run(python_code="print(df.shape)", csv_path="/data/sales.csv")

    # result == {
    #     "success": True,
    #     "stdout": "(1000, 9)\\n",
    #     "stderr": "",
    # }
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Shared constants ───────────────────────────────────────────────────────────

# Path *inside* the Docker container where the temp dir is mounted.
_CONTAINER_WORKDIR = "/sandbox"

_INPUT_CSV_NAME = "input.csv"
_SCRIPT_NAME    = "script.py"

# Preamble prepended to every user script — provides df, csv_path, pd, np.
_SCRIPT_PREAMBLE = textwrap.dedent(
    f"""\
    import pandas as pd
    import numpy as np

    csv_path = "{_CONTAINER_WORKDIR}/{_INPUT_CSV_NAME}"
    df = pd.read_csv(csv_path)
    """
)

# Postamble: write any df mutations back to the CSV.
_SCRIPT_POSTAMBLE = textwrap.dedent(
    f"""\

    # ── Auto-save ────────────────────────────────────────────────────────────
    if isinstance(df, pd.DataFrame):
        df.to_csv(csv_path, index=False)
    """
)


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
            ``success`` — bool, True iff execution completed without error.
            ``stdout``  — str, captured stdout.
            ``stderr``  — str, captured stderr / error message.
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
        subprocess, copy the (possibly mutated) CSV back, and clean up.
        """
        if not os.path.isfile(csv_path):
            return self._error_result(f"Input CSV not found: {csv_path}")

        tempdir: Optional[str] = None
        try:
            tempdir = tempfile.mkdtemp(prefix="datify_dev_")

            # Copy the CSV into the temp dir.
            host_csv = os.path.join(tempdir, _INPUT_CSV_NAME)
            shutil.copy2(csv_path, host_csv)

            # Build the script with host-side csv_path (subprocess uses host paths).
            preamble = textwrap.dedent(
                f"""\
                import pandas as pd
                import numpy as np

                csv_path = r"{host_csv}"
                df = pd.read_csv(csv_path)
                """
            )
            postamble = textwrap.dedent(
                f"""\

                # ── Auto-save ──────────────────────────────────────────────
                if isinstance(df, pd.DataFrame):
                    df.to_csv(r"{host_csv}", index=False)
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

            # Copy the (possibly mutated) CSV back to the original location.
            if success and os.path.isfile(host_csv):
                shutil.copy2(host_csv, csv_path)

            return {
                "success": success,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    f"[LocalSubprocessSandbox] Execution timed out after "
                    f"{self.TIMEOUT_SEC}s."
                ),
            }
        except Exception as exc:
            logger.exception("Unexpected error in LocalSubprocessSandbox.run()")
            return self._error_result(f"Unexpected sandbox error: {exc}")
        finally:
            if tempdir is not None:
                shutil.rmtree(tempdir, ignore_errors=True)

    @staticmethod
    def _error_result(message: str) -> dict:
        logger.error("LocalSubprocessSandbox error: %s", message)
        return {"success": False, "stdout": "", "stderr": message}


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
            - ``df``       — ``pd.DataFrame`` pre-loaded from *csv_path*.
            - ``csv_path`` — container-side path to ``input.csv``.
            - ``pd``       — pandas module.
            - ``np``       — numpy module.

        Mutations to ``df`` are written back to the host CSV via the bind mount.

        Returns
        -------
        dict with keys: ``success`` (bool), ``stdout`` (str), ``stderr`` (str).
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

        tempdir   = None
        container = None
        timer     = None
        timed_out = threading.Event()

        try:
            client = self._get_client()

            # 1. Ephemeral temp directory on the host.
            tempdir = tempfile.mkdtemp(prefix="datify_sandbox_")
            logger.debug("Created sandbox tempdir: %s", tempdir)

            # 2. Copy CSV into the temp dir.
            host_csv_path = os.path.join(tempdir, _INPUT_CSV_NAME)
            shutil.copy2(csv_path, host_csv_path)

            # 3. Assemble the full script.
            full_script   = _SCRIPT_PREAMBLE + python_code + _SCRIPT_POSTAMBLE
            host_script   = os.path.join(tempdir, _SCRIPT_NAME)
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

            # 8. Copy the mutated CSV back to the host original path.
            if exit_code == 0 and os.path.isfile(host_csv_path):
                shutil.copy2(host_csv_path, csv_path)

            if timed_out.is_set():
                return {
                    "success": False,
                    "stdout": stdout,
                    "stderr": (
                        f"[DockerSandbox] Execution timed out after {self.timeout_sec}s "
                        f"and the container was forcibly stopped.\n{stderr}"
                    ).strip(),
                }

            success = exit_code == 0
            logger.debug("Sandbox exited (code=%s, success=%s)", exit_code, success)
            return {"success": success, "stdout": stdout, "stderr": stderr}

        except Exception as exc:
            # Catch docker.errors.ImageNotFound, DockerException, etc.
            err_type = type(exc).__name__
            msg = f"[DockerSandbox] {err_type}: {exc}"
            if "ImageNotFound" in err_type:
                msg = (
                    f"Docker image '{self.image}' not found. "
                    f"Build it with: docker build -t {self.image} ./backend"
                )
            logger.exception("Docker error during sandbox execution")
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
        return {"success": False, "stdout": "", "stderr": message}

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
