"""Close the issues of a pull request merged into a branch that is not the default one.

    python tools/close_stacked_issues.py        # PR_NUMBER, BASE_REF and GH_TOKEN in the environment

GitHub closes the issues a pull request cites with ``Closes``, ``Fixes`` or ``Resolves`` only when
it merges into the default branch. A stacked pull request (whose base is the branch of the previous
one) merges elsewhere, so this script closes them, with a comment naming the pull request and the
branch, and reconciles the parent epic with the dev-workflow commands (a close made with the
workflow token triggers no other workflow, so the epic is handled here).

The pull request body is read through the API and treated as text; no code of the pull request runs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

CLOSING = re.compile(r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s+#(\d+)\b")
SKILL = ".claude/skills/dev-workflow/scripts/github_issues.py"


def closing_references(text: str) -> list[int]:
    """The issue numbers cited with a closing keyword, in order, without repetition."""
    seen: list[int] = []
    for match in CLOSING.finditer(text or ""):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def gh(*args: str) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"gh {' '.join(args)} failed")
    return done.stdout


def main() -> int:
    number = os.environ["PR_NUMBER"]
    base = os.environ["BASE_REF"]
    repository = os.environ["GITHUB_REPOSITORY"]
    body = json.loads(gh("api", f"repos/{repository}/pulls/{number}"))["body"] or ""
    closed = []
    for issue in closing_references(body):
        state = json.loads(gh("api", f"repos/{repository}/issues/{issue}"))
        if "pull_request" in state or state["state"] != "open":
            continue
        gh(
            "issue",
            "comment",
            str(issue),
            "--repo",
            repository,
            "--body",
            f"Fechada pelo merge de #{number} na branch `{base}` (PR empilhado). "
            "O código chega à branch padrão com o merge da branch empilhada.",
        )
        gh("issue", "close", str(issue), "--repo", repository, "--reason", "completed")
        closed.append(issue)
        for command in ("sync-checklist", "close-epic"):
            subprocess.run([sys.executable, SKILL, command, "--parent-of", str(issue)], check=False)
    print(f"Closed: {', '.join(f'#{item}' for item in closed) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
