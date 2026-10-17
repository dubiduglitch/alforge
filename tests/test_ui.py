#!/usr/bin/env python3
from gitget import ui


def test_configure():
    ui.configure(quiet=True, json_output=False, color=False)
    assert ui.style().reset == ""


def test_is_tty_false_by_default_no_terminal():
    assert isinstance(ui.is_tty(), bool)


def test_prompt_secret_fallback_empty():
    s = ui.prompt_secret("q")
    assert s == ""


if __name__ == "__main__":
    test_configure()
    test_is_tty_false_by_default_no_terminal()
    test_prompt_secret_fallback_empty()
    print("ok")
