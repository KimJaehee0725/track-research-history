"""Same-origin CSRF policy for the loopback administration UI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from research_memory.web_security import (
    mutation_source_is_same_origin,
    request_host_is_loopback,
)


class WebSecurityTests(unittest.TestCase):
    def test_same_origin_post_is_allowed(self) -> None:
        self.assertTrue(
            mutation_source_is_same_origin(
                "http://127.0.0.1:8787/",
                origin="http://127.0.0.1:8787",
                referer=None,
                fetch_site="same-origin",
            )
        )

    def test_referer_fallback_is_allowed_for_exact_origin(self) -> None:
        self.assertTrue(
            mutation_source_is_same_origin(
                "http://localhost:8787/",
                origin=None,
                referer="http://localhost:8787/projects/research-hub",
                fetch_site=None,
            )
        )

    def test_cross_site_null_and_missing_sources_are_blocked(self) -> None:
        cases = (
            {
                "origin": "https://attacker.example",
                "referer": None,
                "fetch_site": "cross-site",
            },
            {"origin": "null", "referer": None, "fetch_site": None},
            {"origin": None, "referer": None, "fetch_site": None},
            {
                "origin": "http://localhost:8787",
                "referer": None,
                "fetch_site": "same-site",
            },
            {
                "origin": "http://localhost:9999",
                "referer": None,
                "fetch_site": "same-origin",
            },
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(
                    mutation_source_is_same_origin(
                        "http://localhost:8787/",
                        **case,
                    )
                )

    def test_malformed_request_and_source_origins_fail_closed(self) -> None:
        self.assertFalse(
            mutation_source_is_same_origin(
                "http://localhost:bad/",
                origin="http://attacker.example:bad",
                referer=None,
                fetch_site=None,
            )
        )

    def test_only_loopback_host_authorities_are_allowed(self) -> None:
        for host in (
            "localhost",
            "localhost:8787",
            "127.0.0.1:8787",
            "127.42.0.9",
            "[::1]:8787",
        ):
            with self.subTest(host=host):
                self.assertTrue(request_host_is_loopback(host))

        for host in (
            None,
            "",
            "rebind.example:8787",
            "localhost.attacker.example",
            "127.0.0.1.attacker.example",
            "localhost:bad",
            "localhost:70000",
            "user@localhost:8787",
            "localhost/path",
        ):
            with self.subTest(host=host):
                self.assertFalse(request_host_is_loopback(host))
