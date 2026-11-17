"""The documentation of the suite cites only files and anchors that exist, and points to the core contract.

No database: reads the Markdown of the repository.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s*(```|~~~)")
# Files of every app's documentation_root, cited by the root documents without a package.
APP_DOCUMENTS = {"docs/spec.md", "docs/adr.md", "docs/service-api.md"}
SKIPPED = {".git", ".venv", ".claude", "node_modules", "dist", "var", "__pycache__"}


def documents():
    found = [ROOT / "README.md", ROOT / "AGENTS.md"]
    for path in sorted(ROOT.rglob("*.md")):
        parts = set(path.relative_to(ROOT).parts)
        if not SKIPPED & parts and path not in found and ("docs" in parts or path.name == "AGENTS.md"):
            found.append(path)
    return found


def prose_lines(path):
    inside = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            yield number, line


def slug(title):
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title).replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    seen, result = {}, set()
    for _, line in prose_lines(path):
        match = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if match:
            base = slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            result.add(base if count == 0 else f"{base}-{count}")
    return result


def test_relative_links_and_anchors_resolve():
    problems = []
    for document in documents():
        for number, line in prose_lines(document):
            line = re.sub(r"`[^`]*`", "", line)
            for match in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", line):
                target = match.group(1)
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue
                file_part, _, anchor = target.partition("#")
                resolved = (document.parent / file_part).resolve() if file_part else document
                where = f"{document.relative_to(ROOT).as_posix()}:{number}"
                if not resolved.exists():
                    problems.append(f"{where} -> missing file {target}")
                elif anchor and resolved.suffix == ".md" and anchor not in anchors(resolved):
                    problems.append(f"{where} -> missing anchor {target}")
    assert problems == []


def test_cited_suite_paths_exist():
    problems = []
    for document in documents():
        for number, line in prose_lines(document):
            for span in re.findall(r"`([^`]+)`", line):
                if not re.match(r"^(docs|tools|tests|med_[a-z]+)/[\w./-]+$", span) or span in APP_DOCUMENTS:
                    continue
                base = document.parent if span.startswith("docs/") and document.parent.name != "docs" else ROOT
                candidates = (ROOT / span, base / span, document.parent.parent / span)
                if not any(path.exists() for path in candidates) and not span.startswith("tests/apps/"):
                    problems.append(f"{document.relative_to(ROOT).as_posix()}:{number} -> {span}")
    assert problems == []


def test_every_app_agents_file_points_to_the_root_one():
    for manifest in sorted(ROOT.glob("med_*/manifest.json")):
        agents = manifest.parent / "AGENTS.md"
        assert agents.is_file(), f"{manifest.parent.name} has no AGENTS.md"
        assert "../AGENTS.md" in agents.read_text(encoding="utf-8")


def test_root_agents_points_to_the_installed_core_contract():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    reference = re.search(r"^\s*SKELETON_REF:\s*(\S+)", workflow, re.M).group(1)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert f"https://github.com/alaorneto/skeleton/blob/{reference}/AGENTS.md" in agents
