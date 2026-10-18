#!/usr/bin/env python3
"""Unit tests for alforge's pure logic and security guards.

Standard library only on purpose: alforge itself has no runtime dependency, so
neither does its test suite.  Run it either way::

    python3 tests/test_alforge.py
    PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alforge import assets, checksum, deb, http, installer, lock, report, ui, uri, versions
from alforge.config import Target, parse_target, short_name_matches
from alforge.errors import (
    AlforgeError,
    AmbiguousError,
    ChecksumError,
    NetworkError,
    NotFoundError,
    UsageError,
)
from alforge.providers.gitea import CodebergProvider
from alforge.providers import Asset, Release
from alforge.records import forget
from alforge.state import EntryState, State

_XDG_NAMES = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")


class VersionsTest(unittest.TestCase):
    #: (left, right, expected) triples, the classic dpkg corner cases.
    PAIRS = [
        ("1.0~rc1", "1.0", -1),
        ("1:0.1", "9.9", 1),
        ("1.0-2", "1.0-1", 1),
        ("1.0-1", "1.0", 1),
        ("2.10", "2.9", 1),
        ("1.0a", "1.0", 1),
        ("19.2.0", "19.10.0", -1),
        ("0.9", "1.0", -1),
        ("1.0", "1.0", 0),
    ]

    def test_pure_comparator_edge_cases(self):
        for left, right, expected in self.PAIRS:
            with self.subTest(left=left, right=right):
                self.assertEqual(versions.compare_pure(left, right), expected)
                self.assertEqual(versions.compare_pure(right, left), -expected)

    def test_dpkg_and_pure_agree(self):
        if not versions._dpkg_available():
            self.skipTest("dpkg is not installed")
        for left, right, _ in self.PAIRS:
            with self.subTest(left=left, right=right):
                self.assertEqual(versions.compare(left, right), versions.compare_pure(left, right))

    def test_parse_epoch_and_revision(self):
        self.assertEqual(versions.parse("2:1.3-4"), (2, "1.3", "4"))
        self.assertEqual(versions.parse("1.0"), (0, "1.0", ""))

    def test_is_newer_handles_missing_values(self):
        self.assertFalse(versions.is_newer("", "1.0"))
        self.assertTrue(versions.is_newer("1.0", None))
        self.assertFalse(versions.is_newer("1.0", "1.0"))
        self.assertTrue(versions.is_newer("1.1", "1.0"))

    def test_normalise_tag_is_cosmetic_only(self):
        self.assertEqual(versions.normalise_tag("v1.2.3"), "1.2.3")
        self.assertEqual(versions.normalise_tag("release-1"), "release-1")


class AssetsTest(unittest.TestCase):
    @staticmethod
    def _asset(name: str, *, digest: str | None = None) -> Asset:
        return Asset(name=name, url=f"https://example.invalid/{name}", digest=digest)

    def test_prefers_native_architecture(self):
        chosen = assets.select(
            [self._asset("app_1.0_arm64.deb"), self._asset("app_1.0_amd64.deb")],
            arch="amd64",
        )
        self.assertEqual(chosen.asset.name, "app_1.0_amd64.deb")

    def test_accepts_architecture_independent(self):
        chosen = assets.select([self._asset("tool_1.0_all.deb")], arch="amd64")
        self.assertEqual(chosen.asset.name, "tool_1.0_all.deb")

    def test_refuses_wrong_architecture_only(self):
        with self.assertRaises(NotFoundError) as ctx:
            assets.select([self._asset("app_1.0_arm64.deb")], arch="amd64")
        self.assertIn("app_1.0_arm64.deb", ctx.exception.hint or "")

    def test_excludes_debug_assets(self):
        with self.assertRaises(NotFoundError):
            assets.select(
                [self._asset("app_1.0_amd64-dbg.deb")],
                arch="amd64",
                exclude=("-dbg",),
            )

    def test_ambiguity_is_refused_headless(self):
        with self.assertRaises(AmbiguousError):
            assets.select(
                [self._asset("app_1.0_amd64.deb"), self._asset("app_1.0_amd64.deb")],
                arch="amd64",
                hint="app",
            )

    def test_architecture_token_matching_is_boundary_aware(self):
        self.assertTrue(assets._token_present("app_1.0_amd64.deb", "amd64"))
        self.assertFalse(assets._token_present("damd64.deb", "amd64"))
        self.assertFalse(assets._token_present("amd64x.deb", "amd64"))


class GuessPackageTest(unittest.TestCase):
    def test_exact_and_normalised_match(self):
        target = Target("github", "owner/super-productivity")
        self.assertEqual(
            report.guess_package(target, {"superproductivity": "1.0"}),
            "superproductivity",
        )

    def test_short_prefix_is_never_guessed(self):
        target = Target("github", "owner/r")
        self.assertIsNone(report.guess_package(target, {"adduser": "1.0"}))

    def test_distinctive_prefix_is_accepted(self):
        target = Target("github", "owner/obsidian")
        self.assertEqual(
            report.guess_package(target, {"obsidian-notes": "1.0"}),
            "obsidian-notes",
        )

    def test_no_match_returns_none(self):
        target = Target("github", "owner/whatever")
        self.assertIsNone(report.guess_package(target, {"unrelated": "1.0"}))


class DebTest(unittest.TestCase):
    def test_valid_package_names(self):
        for name in ("superproductivity", "libfoo1", "g++", "python3-dev", "a2ps"):
            with self.subTest(name=name):
                self.assertEqual(deb.validate_package_name(name), name)

    def test_invalid_package_names_are_refused(self):
        for name in ("Bad", "has space", "a", "-leading", "name/with/slash", ""):
            with self.subTest(name=name):
                with self.assertRaises(AlforgeError):
                    deb.validate_package_name(name)

    def test_architecture_aliases(self):
        self.assertIn("x86_64", deb.arch_alias_tokens("amd64"))
        self.assertIn("aarch64", deb.arch_alias_tokens("arm64"))


class HttpSecurityTest(unittest.TestCase):
    def test_rejects_non_http_schemes(self):
        for url in ("ftp://example.invalid/x.deb", "file:///etc/passwd", "data:text/plain,hi"):
            with self.subTest(url=url):
                with self.assertRaises(NetworkError):
                    http._check_download_url(url)

    def test_accepts_http_and_https(self):
        http._check_download_url("https://github.com/a/b.deb")
        http._check_download_url("http://selfhosted.invalid/a/b.deb")

    def test_redirect_strips_credentials_across_hosts(self):
        handler = http._SafeRedirectHandler()
        request = urllib.request.Request(
            "https://github.com/a/b", headers={"Authorization": "Bearer secret"}
        )
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://objects.githubusercontent.com/x"
        )
        self.assertNotIn("Authorization", redirected.headers)

    def test_redirect_keeps_credentials_on_same_host(self):
        handler = http._SafeRedirectHandler()
        request = urllib.request.Request(
            "https://github.com/a/b", headers={"Authorization": "Bearer secret"}
        )
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://github.com/c"
        )
        self.assertIn("Authorization", redirected.headers)


class ChecksumTest(unittest.TestCase):
    def test_manifest_name_detection(self):
        for name in ("SHA256SUMS", "sha256sums.txt", "checksums.txt", "app.deb.sha256"):
            with self.subTest(name=name):
                self.assertTrue(checksum.is_manifest_name(name))
        self.assertFalse(checksum.is_manifest_name("app_1.0_amd64.deb"))

    def test_parse_gnu_format(self):
        first, second = "a" * 64, "b" * 64
        text = f"{first}  app_1.0_amd64.deb\n{second} *app_1.0_arm64.deb\n# comment\n\n"
        digests = checksum.parse_manifest(text)
        self.assertEqual(digests["app_1.0_amd64.deb"], first)
        self.assertEqual(digests["app_1.0_arm64.deb"], second)

    def test_parse_bsd_format(self):
        digest = "c" * 64
        digests = checksum.parse_manifest(f"SHA256 (app.deb) = {digest}\n")
        self.assertEqual(digests["app.deb"], digest)

    def test_lookup_tolerates_path_prefixes(self):
        digest = "d" * 64
        self.assertEqual(checksum.lookup({"dist/app.deb": digest}, "app.deb"), digest)

    def test_verify_detects_mismatch(self):
        with tempfile.NamedTemporaryFile(suffix=".deb") as handle:
            handle.write(b"payload")
            handle.flush()
            path = Path(handle.name)
            good = checksum.sha256_file(path)
            self.assertEqual(checksum.verify(path, good), good)
            with self.assertRaises(ChecksumError):
                checksum.verify(path, "0" * 64)


class ConflictingTargetTest(unittest.TestCase):
    class _Context:
        def __init__(self, entries: dict[str, EntryState]) -> None:
            self.state = State(data=entries)

    def test_detects_duplicate_package(self):
        context = self._Context({"github:other/repo": EntryState(package="foo")})
        self.assertEqual(
            installer.conflicting_target(context, Target("github", "a/b"), "foo"),
            "github:other/repo",
        )

    def test_ignores_the_same_target(self):
        context = self._Context({"github:a/b": EntryState(package="foo")})
        self.assertIsNone(installer.conflicting_target(context, Target("github", "a/b"), "foo"))

    def test_ignores_other_packages(self):
        context = self._Context({"github:other/repo": EntryState(package="bar")})
        self.assertIsNone(installer.conflicting_target(context, Target("github", "a/b"), "foo"))


class TargetTest(unittest.TestCase):
    def test_parse_prefixed_and_bare(self):
        self.assertEqual(parse_target("gitlab:owner/repo"), Target("gitlab", "owner/repo"))
        self.assertEqual(parse_target("owner/repo"), Target("github", "owner/repo"))

    def test_forgejo_is_an_alias_for_gitea(self):
        self.assertEqual(parse_target("forgejo:owner/repo"), Target("gitea", "owner/repo"))

    def test_unknown_forge_is_refused(self):
        with self.assertRaises(AlforgeError):
            parse_target("bitbucket:owner/repo")

    def test_short_name_matching(self):
        target = Target("github", "owner/super-productivity")
        self.assertTrue(short_name_matches(target, "super-productivity"))
        self.assertTrue(short_name_matches(target, "owner/super-productivity"))
        self.assertFalse(short_name_matches(target, "something-else"))


class CodebergTest(unittest.TestCase):
    """Codeberg targets omit the host; the provider fills in codeberg.org."""

    class _Client:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url, *, forge=None, allow_404=False):  # noqa: ANN001
            self.urls.append(url)
            return {"tag_name": "v1.0.0", "assets": []}

    def test_owner_repo_is_enough(self):
        client = self._Client()
        CodebergProvider(client).latest_release("owner/repo")
        self.assertEqual(
            client.urls[0],
            "https://codeberg.org/api/v1/repos/owner/repo/releases/latest",
        )

    def test_an_explicit_host_is_still_accepted(self):
        client = self._Client()
        CodebergProvider(client).latest_release("codeberg.org/owner/repo")
        self.assertEqual(
            client.urls[0],
            "https://codeberg.org/api/v1/repos/owner/repo/releases/latest",
        )

    def test_a_bare_name_is_refused(self):
        with self.assertRaises(ValueError):
            CodebergProvider(self._Client()).latest_release("owner")

    def test_parse_url_returns_a_hostless_path(self):
        provider = CodebergProvider(self._Client())
        self.assertEqual(provider.parse_url("https://codeberg.org/owner/repo"), "owner/repo")

    def test_parse_url_ignores_a_lookalike_host(self):
        provider = CodebergProvider(self._Client())
        self.assertIsNone(provider.parse_url("https://codeberg.org.evil.example/owner/repo"))


# --------------------------------------------------------------------------- #
# test doubles for the pipeline
# --------------------------------------------------------------------------- #
def _release(tag: str, *, prerelease: bool = False, assets=()) -> Release:
    return Release(forge="github", repo="a/b", tag=tag, prerelease=prerelease, assets=tuple(assets))


def _deb_asset(
    name: str = "app_1.0_amd64.deb", *, size: int | None = 10, ident: str | None = None
) -> Asset:
    return Asset(name=name, url=f"https://example.invalid/{name}", size=size, id=ident)


class _FakeProvider:
    """Minimal provider double exposing the latest and latest-stable release."""

    def __init__(self, latest: Release | None, stable: Release | None) -> None:
        self._latest = latest
        self._stable = stable
        self.stable_calls = 0

    def latest_release(self, path: str) -> Release | None:
        return self._latest

    def latest_stable_release(self, path: str, *, limit: int = 20) -> Release | None:
        self.stable_calls += 1
        return self._stable


class _EmptyState:
    """State double: every target is unknown, so the kind is auto-detected."""

    def get(self, key: str) -> EntryState:  # noqa: ARG002
        return EntryState()


class _FakePlanContext:
    offline = False

    def __init__(self, provider: _FakeProvider) -> None:
        self._provider = provider
        self.state = _EmptyState()

    def provider(self, forge: str) -> _FakeProvider:
        return self._provider

    def asset_exclude(self) -> tuple[str, ...]:
        return ()


class PrereleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        ui.configure(quiet=True, json_output=False, color=False)

    def _provider(self) -> _FakeProvider:
        asset = _deb_asset()
        return _FakeProvider(
            latest=_release("v2.0.0-beta", prerelease=True, assets=[asset]),
            stable=_release("v1.9.0", assets=[asset]),
        )

    def test_falls_back_to_newest_stable(self):
        provider = self._provider()
        chosen = installer.plan(_FakePlanContext(provider), Target("github", "a/b"))
        self.assertEqual(chosen.release.tag, "v1.9.0")
        self.assertEqual(provider.stable_calls, 1)

    def test_allow_prerelease_keeps_the_beta(self):
        provider = self._provider()
        chosen = installer.plan(
            _FakePlanContext(provider), Target("github", "a/b"), allow_prerelease=True
        )
        self.assertEqual(chosen.release.tag, "v2.0.0-beta")
        self.assertEqual(provider.stable_calls, 0)

    def test_prerelease_is_used_when_nothing_is_stable(self):
        asset = _deb_asset()
        provider = _FakeProvider(
            latest=_release("v2.0.0-beta", prerelease=True, assets=[asset]), stable=None
        )
        chosen = installer.plan(_FakePlanContext(provider), Target("github", "a/b"))
        self.assertEqual(chosen.release.tag, "v2.0.0-beta")


class _FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, url, writer, *, forge=None):  # noqa: ANN001
        self.calls += 1
        writer(b"data")
        return 4


class _FakeDownloadContext:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.client = _FakeClient()

    def download_dir(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory


class DownloadCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        ui.configure(quiet=True, json_output=False, color=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _candidate(self) -> installer.Plan:
        asset = _deb_asset(ident="42")
        return installer.Plan(
            target=Target("github", "a/b"),
            release=_release("v1.0.0", assets=[asset]),
            asset=asset,
        )

    def test_second_download_reuses_the_cache(self):
        context = _FakeDownloadContext(Path(self.tmp.name))
        candidate = self._candidate()
        first = installer.download(context, candidate)
        self.assertEqual(context.client.calls, 1)
        second = installer.download(context, candidate)
        self.assertEqual(context.client.calls, 1)
        self.assertEqual(first, second)

    def test_cached_path_is_deterministic_and_flat(self):
        context = _FakeDownloadContext(Path(self.tmp.name))
        candidate = self._candidate()
        path = installer.cached_path(context, candidate)
        self.assertEqual(path, installer.cached_path(context, candidate))
        self.assertNotIn("/", path.name)
        self.assertTrue(path.name.endswith("--42.deb"))

    def test_downloaded_file_is_private(self):
        context = _FakeDownloadContext(Path(self.tmp.name))
        path = installer.download(context, self._candidate())
        self.assertEqual(path.stat().st_mode & 0o077, 0)


class UriTest(unittest.TestCase):
    """The alforge:// scheme is the bridge a web page uses, so it is strict."""

    def test_install_from_github(self):
        request = uri.parse("alforge://install/github/owner/repo")
        self.assertEqual(request.verb, "install")
        self.assertEqual(request.spec, "github:owner/repo")

    def test_track_from_codeberg(self):
        request = uri.parse("alforge://track/codeberg/owner/repo")
        self.assertEqual(request.verb, "track")
        self.assertEqual(request.spec, "codeberg:owner/repo")

    def test_gitea_host_is_kept(self):
        request = uri.parse("alforge://install/gitea/git.example.org/owner/repo")
        self.assertEqual(request.spec, "gitea:git.example.org/owner/repo")

    def test_forgejo_is_accepted(self):
        self.assertEqual(
            uri.parse("alforge://install/forgejo/owner/repo").spec, "forgejo:owner/repo"
        )

    def test_uppercase_action_is_normalised(self):
        self.assertEqual(uri.parse("alforge://INSTALL/github/o/r").verb, "install")

    def test_percent_encoding_is_decoded(self):
        request = uri.parse("alforge://install/github/my%2Downer/repo")
        self.assertEqual(request.spec, "github:my-owner/repo")

    def test_rejects_a_foreign_scheme(self):
        with self.assertRaises(UsageError):
            uri.parse("https://example.com/install/github/o/r")

    def test_rejects_an_unknown_action(self):
        with self.assertRaises(UsageError):
            uri.parse("alforge://purge/github/o/r")

    def test_rejects_an_unknown_forge(self):
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/bitbucket/o/r")

    def test_rejects_a_url_in_the_forge_position(self):
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/https/evil.example/x.deb")

    def test_rejects_a_url_as_the_target(self):
        # Otherwise a page could point the pipeline at an arbitrary artifact.
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/github/https://evil.example/x.deb")

    def test_rejects_an_incomplete_target(self):
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/github/owner")

    def test_rejects_a_query_or_fragment(self):
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/github/o/r?asset=evil.deb")
        with self.assertRaises(UsageError):
            uri.parse("alforge://install/github/o/r#frag")


class GuiDialogTest(unittest.TestCase):
    """The zenity/kdialog bridge, the only channel a browser-launched run has."""

    def setUp(self) -> None:
        ui.configure(quiet=True, json_output=False, color=False)
        ui.set_assume_yes(False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name)
        self.empty = self.bin / "empty"
        self.empty.mkdir()
        self.calls = self.bin / "calls.txt"
        self._write_tool("zenity")
        os.environ["ALFORGE_TEST_CALLS"] = str(self.calls)
        os.environ["ALFORGE_TEST_EXIT"] = "0"
        self._saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{self._saved_path}"
        self.addCleanup(self._restore)

    def _write_tool(self, name: str) -> None:
        script = self.bin / name
        script.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$ALFORGE_TEST_CALLS"\n'
            'exit "${ALFORGE_TEST_EXIT:-0}"\n'
        )
        script.chmod(0o755)

    def _restore(self) -> None:
        os.environ["PATH"] = self._saved_path
        for name in ("ALFORGE_TEST_CALLS", "ALFORGE_TEST_EXIT"):
            os.environ.pop(name, None)

    def _recorded(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""

    def test_confirm_gui_asks_a_question(self):
        self.assertTrue(ui.confirm_gui("Install foo?"))
        self.assertIn("--question", self._recorded())
        self.assertIn("Install foo?", self._recorded())

    def test_confirm_gui_honours_a_refusal(self):
        os.environ["ALFORGE_TEST_EXIT"] = "1"
        self.assertFalse(ui.confirm_gui("Install foo?"))

    def test_gui_error_shows_the_hint(self):
        self.assertTrue(ui.gui_error("no .deb asset in this release", hint="archives only"))
        recorded = self._recorded()
        self.assertIn("--error", recorded)
        self.assertIn("no .deb asset in this release", recorded)
        self.assertIn("archives only", recorded)

    def test_gui_info_self_dismisses(self):
        self.assertTrue(ui.gui_info("Installed foo 1.0"))
        recorded = self._recorded()
        self.assertIn("--info", recorded)
        self.assertIn("--timeout=", recorded)

    def test_no_dialog_tool_refuses_instead_of_assuming(self):
        os.environ["PATH"] = str(self.empty)
        self.assertIsNone(ui.dialog_tool())
        self.assertFalse(ui.confirm_gui("Install foo?"))
        self.assertTrue(ui.confirm_gui("Install foo?", default=True))
        self.assertFalse(ui.gui_error("nope"))
        self.assertFalse(ui.gui_info("nope"))
        self.assertEqual(self._recorded(), "")

    def test_kdialog_is_used_when_zenity_is_absent(self):
        (self.bin / "zenity").unlink()
        self._write_tool("kdialog")
        self.assertEqual(ui.dialog_tool(), "kdialog")
        self.assertTrue(ui.confirm_gui("Install foo?"))
        ui.gui_error("boom")
        ui.gui_info("done")
        recorded = self._recorded()
        self.assertIn("--yesno", recorded)
        self.assertIn("--error", recorded)
        self.assertIn("--passivepopup", recorded)


class _SandboxedTest(unittest.TestCase):
    """Redirects the XDG directories into a throwaway directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._saved = {name: os.environ.get(name) for name in _XDG_NAMES}
        for name in _XDG_NAMES:
            os.environ[name] = self.tmp.name
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class LockTest(_SandboxedTest):
    def test_lock_is_exclusive(self):
        with lock.exclusive(wait=False):
            with self.assertRaises(lock.LockBusy):
                with lock.exclusive(wait=False):
                    pass

    def test_lock_is_released_after_the_block(self):
        with lock.exclusive(wait=False):
            pass
        with lock.exclusive(wait=False):
            pass


class ForgetTest(_SandboxedTest):
    def test_forget_drops_the_learned_entry(self):
        state = State.load()
        entry = state.get("github:a/b")
        entry.package = "app"
        entry.last_version = "1.0.0"
        state.save()
        self.assertIn("github:a/b", State.load().entries)

        class _Context:
            pass

        context = _Context()
        context.state = State.load()
        forget(context, Target("github", "a/b"))
        context.state.save()
        self.assertNotIn("github:a/b", State.load().entries)


if __name__ == "__main__":
    unittest.main(verbosity=2)
