from __future__ import annotations

from tether.util.path_policy import PathPolicy, compile_glob


def test_glob_translation():
    assert compile_glob("/a/**").match("/a/b/c.txt")
    assert compile_glob("/a/*.txt").match("/a/x.txt")
    assert not compile_glob("/a/*.txt").match("/a/b/c.txt")  # * stays in one segment
    assert compile_glob("**/.env").match("/a/b/.env")
    assert compile_glob("/a/secrets/").match("/a/secrets/x")  # trailing / = its contents


def test_default_deny_and_negation(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / ".env").write_text("x")
    (tmp_path / "docs" / "a.txt").write_text("y")
    policy = PathPolicy([f"{tmp_path}/**", "!**/.env"])
    assert policy.allowed(tmp_path / "docs" / "a.txt", working_dir=str(tmp_path))
    assert not policy.allowed(tmp_path / ".env", working_dir=str(tmp_path))


def test_bare_name_matches_nothing(tmp_path):
    (tmp_path / "a.txt").write_text("z")
    policy = PathPolicy(["a.txt"])
    assert not policy.allowed(tmp_path / "a.txt", working_dir=str(tmp_path))


def test_working_dir_placeholder(tmp_path):
    (tmp_path / "x.md").write_text("z")
    policy = PathPolicy(["{working_dir}/**"])
    assert policy.allowed(tmp_path / "x.md", working_dir=str(tmp_path))


def test_parent_escape_is_blocked(tmp_path):
    (tmp_path / "outside.txt").write_text("secret")
    project = tmp_path / "proj"
    project.mkdir()
    policy = PathPolicy(["{working_dir}/**"])
    assert not policy.allowed(project / ".." / "outside.txt", working_dir=str(project))
