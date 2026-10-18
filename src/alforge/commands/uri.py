"""``handle-uri`` - what a browser launches through ``alforge://``.

The URI is only a *request*: we resolve it, fetch the release, show the exact
artifact in a graphical dialog, and act only if the human approves.  This is the
same pipeline as ``alforge install``, so checksum verification, package-name
validation and the "one writer" lock still apply.

There is no terminal here -- a web page started us -- so every outcome is also
reported on screen.  stderr goes nowhere: the browser discards it.
"""

from __future__ import annotations

from .. import installer, ui, uri
from ..errors import AlforgeError, UsageError
from ..records import record_check, record_install
from ..targets import resolve


def cmd_handle_uri(context, args) -> int:  # noqa: ANN001
    try:
        return _handle(context, args)
    except AlforgeError as exc:
        _report_failure(exc.message, exc.hint)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - the browser hides the traceback
        _report_failure("alforge could not complete the request", f"{type(exc).__name__}: {exc}")
        raise


def _report_failure(message: str, hint: str | None) -> None:
    """Log to the audit trail and, because nobody sees the terminal, on screen."""
    ui.error(message)
    if hint:
        ui.detail(hint)
    ui.gui_error(message, hint=hint)


def _handle(context, args) -> int:  # noqa: ANN001
    request = uri.parse(args.uri)
    if not request.spec:
        raise UsageError(f"the {request.verb!r} action needs a target")
    target = resolve(context, request.spec)

    # Fetch first so the dialog can name the exact artifact that would be
    # installed, and so a project that publishes nothing installable is reported
    # *before* anything is asked.  Nothing is downloaded yet.
    candidate = installer.plan(context, target)
    question = (
        f"{request.verb.capitalize()} {candidate.asset.name} "
        f"({candidate.release.tag or 'release'}) from {candidate.target}?"
    )
    if not ui.confirm_gui(question):
        if ui.dialog_tool() is None:
            ui.error("no graphical dialog is available to approve a browser request")
            ui.detail("install zenity or kdialog, then try the button again")
        else:
            ui.info(f"{candidate.target}: not approved, nothing was changed")
        return 0

    # The human approved, so nothing below may prompt again.
    ui.set_assume_yes(True)

    if request.verb == "track":
        if context.dry_run:
            ui.info(f"would start tracking {target}")
        elif context.registry.add(target):
            ui.ok(f"now tracking {target}")
            ui.gui_info(f"alforge now tracks {target}")
        else:
            ui.gui_info(f"{target} is already tracked")
        record_check(context, target, candidate)
        context.save_state()
        return 0

    _plan, _artifact, info, digest = installer.run(
        context,
        target,
        candidate=candidate,
        recommend=bool(context.config.setting("install_recommends", True)),
    )
    if info is None:
        record_check(context, target, candidate)
        ui.gui_info(f"{target} is already up to date ({context.state.get(str(target)).last_version})")
    else:
        record_install(
            context, target, candidate, package=info.name, version=info.version, digest=digest
        )
        if context.dry_run:
            ui.info(f"would track {target}")
        else:
            if context.registry.add(target):
                ui.detail(f"added {target} to the tracking registry")
            ui.ok(f"installed {info.name} {info.version}")
            ui.gui_info(f"Installed {info.name} {info.version}")
    context.save_state()
    return 0
