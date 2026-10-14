"""Unit tests for repository tools and boundary enforcement."""

import pytest
from lifecore_swe.tools.filesystem import ControlledFileSystemTool
from lifecore_swe.tools.diff import DiffTool
from lifecore_swe.tools.test_runner import TestRunnerTool

REPO_PATH = "/lifecore-swe/fixtures/buggy_repo"


def test_list_files():
    fs = ControlledFileSystemTool(REPO_PATH)
    files = fs.list_files()
    assert "event_processor/filters.py" in files
    assert "TASK.md" in files
    assert "tests/test_pipeline.py" in files


def test_boundary_escape_prevention():
    fs = ControlledFileSystemTool(REPO_PATH)
    with pytest.raises(PermissionError):
        fs.read_file("../../pyproject.toml")


def test_search_and_read():
    fs = ControlledFileSystemTool(REPO_PATH)
    results = fs.search_text("is_in_window")
    assert len(results) > 0
    first_file = results[0]["file"]
    content = fs.read_file(first_file)
    assert "def is_in_window" in content


def test_diff_tool():
    diff_tool = DiffTool(REPO_PATH)
    res = diff_tool.get_diff()
    assert "files_changed" in res
    assert isinstance(res["files_changed"], list)


def test_test_runner_tool():
    runner = TestRunnerTool(REPO_PATH)
    res = runner.run_tests()
    assert "exit_code" in res
    assert "summary" in res
