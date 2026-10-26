from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.collab_behavior_smoke import HistoryCLI

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("history_relation_test", ROOT / "scripts/history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


class RelationRetrievalTests(unittest.TestCase):
    def test_identifier_hit_surfaces_incoming_partial_correction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = HistoryCLI(root)
            cli.run("bootstrap")
            first = cli.emitted_path(cli.run("decision", "--title", "Original normalization", "--decision", "normalized_gain returns zero for empty count."))
            correction = cli.emitted_path(cli.run("decision", "--title", "Narrow empty case", "--decision", "빈 표본에서 total=0인 경우에만 영을 반환한다. 다른 입력은 거부한다.", "--corrects", str(first.relative_to(root))))
            payload = json.loads(cli.run("search", "normalized_gain", "--kind", "decisions", "--json").stdout)
            self.assertEqual(str(first.relative_to(root)), payload["results"][0]["path"])
            context = payload["results"][0]["related_records"]
            self.assertEqual(str(correction.relative_to(root)), context[0]["path"])
            self.assertEqual("corrected_by", context[0]["relation"])
            self.assertIn("total=0", context[0]["excerpt"])
            self.assertTrue(any(x["code"] == "related_correction" for x in payload["diagnostics"]))
            text = cli.run("search", "normalized_gain", "--kind", "decisions").stdout
            self.assertIn("corrected_by", text)
            self.assertIn(correction.name, text)
            formatted = history.format_bm25_read_first(payload)
            self.assertIn(correction.name, formatted)

    def test_scoped_search_discloses_outside_scope_correction_as_context(self):
        docs = [
            {"path":"history/decisions/0001-a.md", "record_id":"dec-a", "kind":"decisions", "approval":"accepted", "status":"accepted", "text":"## Decision\n\nexact_symbol works.\n", "index_text":"exact_symbol works", "title":"A", "line_start":"10"},
            {"path":"history/changes/2020-correction.md", "record_id":"chg-b", "kind":"changes", "approval":"completed", "status":"completed", "corrects":"dec-a", "text":"## Results\n\nThe old rule applies only to seed 42.\n", "index_text":"seed 42", "title":"B", "line_start":"20"},
        ]
        result = history.bm25_search_documents(docs,"exact_symbol",8,kinds=["decisions"])
        context = result["results"][0]["related_records"][0]
        self.assertTrue(context["outside_filters"])
        self.assertEqual("history/changes/2020-correction.md",context["path"])
        self.assertEqual(22,context["line"])
