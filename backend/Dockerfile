# ─────────────────────────────────────────────────────────────────────────────
# Datify Sandbox Image
# ─────────────────────────────────────────────────────────────────────────────
# Minimal Python 3.11 image with the data-science dependencies pre-installed.
# This image is used exclusively by DockerSandbox to run LLM-generated code
# in an isolated, network-less, memory-capped container.
#
# Build:
#   docker build -t datify-sandbox:latest ./backend
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Prevents Python from writing .pyc files and enables unbuffered stdout/stderr
# so container logs are captured in real-time by the Docker SDK.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the runtime dependencies required inside the sandbox.
# No dev tools, no shells beyond what's needed for `python` invocation.
RUN pip install --no-cache-dir \
    pandas==2.2.2 \
    numpy==1.26.4

# The sandbox tempdir is bind-mounted here at runtime.
# The directory is created so it exists even if the mount is delayed.
RUN mkdir -p /sandbox

WORKDIR /sandbox

# Drop to a non-root user for an additional layer of defence.
RUN useradd --no-create-home --shell /bin/false sandbox_user
USER sandbox_user

# Default command — overridden by DockerSandbox to run the generated script.
CMD ["python", "--version"]
