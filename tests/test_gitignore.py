"""Check repository ignore policy with Git, independently of the user's index."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_local_skills_are_ignored_except_explicit_bundled_directories(tmp_path: Path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required to check repository ignore rules")

    # Isolate the temporary repository from user Git configuration and overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(
        [git, "init", "--quiet", "--template=", str(tmp_path)],
        env=env, check=True, capture_output=True,
    )
    shutil.copyfile(Path(__file__).resolve().parents[1] / ".gitignore", tmp_path / ".gitignore")

    cases = {
        "skills/my-report/skill_def.md": True,
        "skills/my-report/nested/query.sql": True,
        "skills/sample-custom-report/skill_def.md": True,
        "skills/sample-monthly-sales-report-copy/skill_def.md": True,
        "skills/sample-monthly-sales-report/skill_def.md": False,
        "skills/sample-monthly-sales-report-sqlite/skill_def.md": False,
        "skills/sample-update-order-status/mutation.py": False,
        "skills/sample-reset-order-to-pending/mutation.py": False,
        "skills/_lib/skill_loader.py": True,
        "skills/_lib/__pycache__/skill_loader.cpython-312.pyc": True,
        "skills/sample-update-order-status/__pycache__/mutation.cpython-312.pyc": True,
        "skills/SKILLS.md": True,
        "skills/_audit.jsonl": True,
        "docs/security/SAFETY.md": False,
        "tests/fixtures/skills/my-report/skill_def.md": False,
    }
    for relative_path in cases:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    result = subprocess.run(
        [git, "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=tmp_path, env=env, input="\0".join(cases) + "\0",
        text=True, capture_output=True, check=True,
    )
    ignored = set(result.stdout.rstrip("\0").split("\0"))
    assert ignored == {path for path, should_ignore in cases.items() if should_ignore}
