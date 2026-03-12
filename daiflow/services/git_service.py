import asyncio
import logging

logger = logging.getLogger(__name__)


async def _run(cmd: list[str], cwd: str, timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Git operation timed out after {timeout}s")
    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        # Log full details for debugging, return sanitized message to caller
        logger.error("Git command failed: %s | stderr: %s", " ".join(cmd), stderr_text)
        # Provide a user-friendly error without exposing full paths
        short_cmd = cmd[1] if len(cmd) > 1 else cmd[0]
        raise RuntimeError(f"Git {short_cmd} failed: {stderr_text[:200]}")
    return stdout.decode().strip()


async def checkout_branch(local_path: str, branch: str):
    """Checkout or create a branch."""
    try:
        await _run(["git", "checkout", branch], cwd=local_path)
    except RuntimeError:
        await _run(["git", "checkout", "-b", branch], cwd=local_path)


async def get_diff(local_path: str, branch: str = "") -> str:
    """Get git diff for the current branch against its merge-base with main."""
    if branch:
        # Try to diff against merge-base with common default branches
        for base in ("main", "master"):
            try:
                merge_base = await _run(["git", "merge-base", base, branch], cwd=local_path)
                return await _run(["git", "diff", merge_base], cwd=local_path)
            except RuntimeError:
                continue
        # Fallback: diff against HEAD (shows uncommitted changes)
        return await _run(["git", "diff", "HEAD"], cwd=local_path)
    return await _run(["git", "diff", "HEAD"], cwd=local_path)


async def commit(local_path: str, message: str):
    """Stage tracked changes and commit."""
    await _run(["git", "add", "-u"], cwd=local_path)
    await _run(["git", "add", "."], cwd=local_path)
    await _run(["git", "commit", "-m", message], cwd=local_path)


async def push(local_path: str, branch: str):
    """Push to remote."""
    await _run(["git", "push", "-u", "origin", branch], cwd=local_path)
