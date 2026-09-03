# pipeline/observability.py
#
# LLM observability via Langfuse.
#
# Provides a lightweight initialization check and helper so the rest of the
# pipeline can import from one place.  The actual tracing is done via
# Langfuse's @observe decorator — add it to any function you want traced.
#
# Setup (free cloud tier):
#   1. Sign up at https://cloud.langfuse.com
#   2. Create a project → copy Public Key + Secret Key
#   3. Add to your .env:
#        LANGFUSE_PUBLIC_KEY=pk-lf-...
#        LANGFUSE_SECRET_KEY=sk-lf-...
#        LANGFUSE_HOST=https://cloud.langfuse.com   # optional, this is the default
#
# If the env vars are not set, every @observe call is a silent no-op — the
# pipeline runs normally, just without traces.
#
# Usage in this codebase:
#   from langfuse.decorators import observe, langfuse_context
#
#   @observe(as_type="generation")
#   def my_llm_call(prompt):
#       ...
#       langfuse_context.update_current_observation(
#           model="gpt-4o-mini",
#           usage={"input": prompt_tokens, "output": completion_tokens},
#       )
#       return result

import os
import logging

log = logging.getLogger(__name__)


def check_langfuse_config() -> bool:
    """Return True if Langfuse env vars are present."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def log_langfuse_status() -> None:
    """Log whether Langfuse tracing is active (called once at startup)."""
    # Check if the package is installed
    try:
        import langfuse as _lf
        pkg_version = getattr(_lf, "__version__", "unknown")
        pkg_installed = True
    except ImportError:
        pkg_installed = False
        pkg_version = None

    if not pkg_installed:
        log.warning("Langfuse package NOT installed — traces disabled.")
        return

    # Check if the decorator API is importable (API changed across major versions)
    try:
        from langfuse.decorators import observe as _obs, langfuse_context as _ctx  # noqa: F401
        decorator_ok = True
    except (ImportError, AttributeError) as e:
        decorator_ok = False
        log.warning(f"Langfuse v{pkg_version} installed but decorators unavailable ({e}) — traces disabled.")

    if not check_langfuse_config():
        log.warning(
            f"Langfuse v{pkg_version} installed but env vars missing "
            "(LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY). Traces disabled."
        )
        return

    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    log.info(f"Langfuse v{pkg_version} ready (decorators={'ok' if decorator_ok else 'BROKEN'}) — {host}")

    # Send a direct startup test trace so we can confirm end-to-end connectivity
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=host,
        )
        t = _client.trace(name="startup-ping", metadata={"pkg_version": pkg_version})
        _client.flush()
        log.info(f"Langfuse startup-ping trace sent OK (id={t.id})")
    except Exception as exc:
        log.warning(f"Langfuse startup-ping FAILED: {exc}")
