"""bin/self-update.sh: fast-forward the pipeline checkout before a run.

Exercised against real throwaway git repos (an "origin" and a clone standing
in for the pipeline checkout) because the failure modes that matter — dirty
tree, diverged history, unreachable remote — are git behaviours, not shell
syntax.
"""

import pathlib
import subprocess

REPO = pathlib.Path(__file__).parents[2]
SCRIPT = REPO / "bin" / "self-update.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "HOME": "/nonexistent",  # ignore user gitconfig (signing, hooks)
    "PATH": "/usr/bin:/bin",
}


def git(cwd, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=GIT_ENV, check=True,
                          capture_output=True, text=True)


def head(cwd):
    return git(cwd, "rev-parse", "HEAD").stdout.strip()


def run_script(checkout, watch="bin/daily.sh"):
    return subprocess.run(["bash", str(SCRIPT), str(checkout), watch],
                          env=GIT_ENV, capture_output=True, text=True)


def make_pair(tmp_path):
    """origin with one commit + a clone of it; returns (origin, checkout)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-b", "main")
    (origin / "bin").mkdir()
    (origin / "bin" / "daily.sh").write_text("echo v1\n")
    (origin / "other.txt").write_text("v1\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "v1")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    return origin, checkout


def test_up_to_date_is_a_quiet_success(tmp_path):
    _, checkout = make_pair(tmp_path)
    before = head(checkout)
    r = run_script(checkout)
    assert r.returncode == 0
    assert head(checkout) == before


def test_fast_forwards_to_origin(tmp_path):
    origin, checkout = make_pair(tmp_path)
    (origin / "other.txt").write_text("v2\n")
    git(origin, "commit", "-am", "v2")
    r = run_script(checkout)
    assert r.returncode == 0
    assert head(checkout) == head(origin)


def test_exit_3_when_the_watched_file_changed(tmp_path):
    origin, checkout = make_pair(tmp_path)
    (origin / "bin" / "daily.sh").write_text("echo v2\n")
    git(origin, "commit", "-am", "new daily.sh")
    r = run_script(checkout)
    assert r.returncode == 3  # caller must re-exec the new script
    assert head(checkout) == head(origin)


def test_dirty_tree_is_never_touched(tmp_path):
    origin, checkout = make_pair(tmp_path)
    (origin / "other.txt").write_text("v2\n")
    git(origin, "commit", "-am", "v2")
    before = head(checkout)
    (checkout / "other.txt").write_text("local edit\n")
    r = run_script(checkout)
    assert r.returncode == 0  # skipped, not failed
    assert head(checkout) == before
    assert (checkout / "other.txt").read_text() == "local edit\n"


def test_diverged_history_stays_put(tmp_path):
    origin, checkout = make_pair(tmp_path)
    (origin / "other.txt").write_text("v2\n")
    git(origin, "commit", "-am", "v2")
    (checkout / "other.txt").write_text("local commit\n")
    git(checkout, "commit", "-am", "local")
    before = head(checkout)
    r = run_script(checkout)
    assert r.returncode == 0  # ff-only refused; run continues on old code
    assert head(checkout) == before


def test_unreachable_remote_never_fails_the_pipeline(tmp_path):
    origin, checkout = make_pair(tmp_path)
    git(checkout, "remote", "set-url", "origin", str(tmp_path / "gone"))
    before = head(checkout)
    r = run_script(checkout)
    assert r.returncode == 0
    assert head(checkout) == before
