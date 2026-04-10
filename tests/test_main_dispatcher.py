"""Tests for the siv/__main__.py unified CLI dispatcher."""
import subprocess
import sys
import pytest


def test_help_flag():
    result = subprocess.run(
        [sys.executable, "-m", "siv", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "inspect" in result.stdout
    assert "score" in result.stdout
    assert "generate" in result.stdout


def test_no_args_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "siv"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "inspect" in result.stdout


def test_unknown_command_exits_2():
    result = subprocess.run(
        [sys.executable, "-m", "siv", "frobnicate"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "Unknown command" in result.stderr


def test_inspect_help():
    result = subprocess.run(
        [sys.executable, "-m", "siv", "inspect", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "candidate" in result.stdout.lower() or "candidate" in result.stderr.lower()
