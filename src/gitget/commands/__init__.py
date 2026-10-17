"""Command implementations.

Each command is a function ``(context, args) -> int`` returning a process exit
code.  Keeping them out of ``cli.py`` keeps argument parsing and business logic
separable (and testable).
"""
