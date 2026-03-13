import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# Valid git branch name: starts with word char, allows word chars, dots, slashes, hyphens
_BRANCH_RE = re.compile(r'^[\w][\w./-]*$')


def validate_branch_name(branch: str):
    """Validate that a branch name is safe for git commands.

    Rejects names that could be interpreted as git flags (starting with -)
    or contain characters invalid for filenames/git refs.
    """
    if not branch or not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")
    if '..' in branch or branch.endswith('.lock') or branch.endswith('/'):
        raise ValueError(f"Invalid branch name: {branch!r}")


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


async def clone_or_pull(git_url: str, target_dir: str, timeout: int = 300) -> str:
    """Clone a repo if not yet cloned, otherwise pull latest.

    Returns the absolute path to the cloned repo directory.
    """
    from pathlib import Path

    target = Path(target_dir)
    if (target / ".git").exists():
        logger.info("Repo already cloned at %s, pulling latest...", target_dir)
        await _run(["git", "pull", "--ff-only"], cwd=target_dir, timeout=timeout)
    else:
        target.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning %s into %s ...", git_url, target_dir)
        await _run(["git", "clone", git_url, target_dir], cwd=str(target.parent), timeout=timeout)
    return target_dir


async def checkout_branch(local_path: str, branch: str):
    """Checkout or create a branch. Creates if it doesn't exist."""
    validate_branch_name(branch)
    try:
        await _run(["git", "checkout", "-b", branch], cwd=local_path)
    except RuntimeError:
        # Branch already exists — just switch to it
        await _run(["git", "checkout", branch], cwd=local_path)


async def get_diff(local_path: str, branch: str = "") -> str:
    """Get git diff for the current branch against its merge-base with main.

    Uses `git add -N .` first to include untracked (new) files in the diff.
    This only registers new files in the index without staging their content,
    so it won't affect commits.
    """
    # Make untracked files visible to git diff
    try:
        await _run(["git", "add", "-N", "."], cwd=local_path)
    except RuntimeError:
        pass

    if branch:
        validate_branch_name(branch)
        # Try to diff against merge-base with common default branches
        for base in ("main", "master"):
            try:
                merge_base = await _run(["git", "merge-base", base, branch], cwd=local_path)
                return await _run(["git", "diff", merge_base], cwd=local_path)
            except RuntimeError:
                continue
        # Fallback: diff against HEAD (shows uncommitted changes)
        logger.info("No main/master base found for branch %s, falling back to HEAD diff", branch)
        return await _run(["git", "diff", "HEAD"], cwd=local_path)
    return await _run(["git", "diff", "HEAD"], cwd=local_path)


async def get_head_hash(local_path: str) -> str:
    """Get the current HEAD commit hash."""
    return await _run(["git", "rev-parse", "HEAD"], cwd=local_path)


async def get_diff_between(local_path: str, hash_before: str, hash_after: str) -> str:
    """Get diff between two commit hashes."""
    return await _run(["git", "diff", hash_before, hash_after], cwd=local_path)


async def commit(local_path: str, message: str):
    """Stage all changes and commit.

    Uses 'git add .' which respects .gitignore rules.
    """
    await _run(["git", "add", "."], cwd=local_path)
    await _run(["git", "commit", "-m", message], cwd=local_path)


async def push(local_path: str, branch: str):
    """Push to remote."""
    validate_branch_name(branch)
    await _run(["git", "push", "-u", "origin", branch], cwd=local_path)


async def fetch_remote(local_path: str, timeout: int = 120) -> None:
    """Fetch latest from origin."""
    await _run(["git", "fetch", "origin"], cwd=local_path, timeout=timeout)


async def get_remote_head(local_path: str, branch: str = "") -> str | None:
    """Get the commit hash of a remote branch (origin/<branch>).

    Tries origin/main then origin/master if branch is not specified.
    Returns None if no remote branch is found.
    """
    candidates = [branch] if branch else ["main", "master"]
    for b in candidates:
        try:
            return await _run(["git", "rev-parse", f"origin/{b}"], cwd=local_path)
        except RuntimeError:
            continue
    return None
