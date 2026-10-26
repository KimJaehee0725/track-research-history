from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("retrieval_history", ROOT / "scripts/history.py")
history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history)


class RetrievalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = json.loads((ROOT / "tests/fixtures/retrieval_cases.json").read_text())
        self.docs = []
        for item in self.fixture["documents"]:
            path = self.root / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (f'---\ntype: change\ntitle: "{item["title"]}"\nstatus: {item["status"]}\n---\n'
                   f'# {item["title"]}\n\nStatus: {item["status"]}\n\n## Evidence\n\n{item["body"]}\n\n'
                   + item.get("extra", ""))
            path.write_text(raw)
            self.docs.extend(history.search_documents_for_file(self.root, path, raw, item["status"], "active"))

    def search(self, query, **kwargs):
        return history.bm25_search_documents(self.docs, query, 8, **kwargs)

    def test_twenty_six_evidence_queries(self):
        for case in self.fixture["cases"]:
            with self.subTest(query=case["query"]):
                result = self.search(case["query"])
                if case.get("empty"):
                    self.assertEqual([], result["results"])
                    self.assertTrue(result["diagnostics"])
                else:
                    self.assertTrue(result["results"])
                    self.assertEqual(case["expected"], result["results"][0]["path"])

    def test_files_grouped_and_budget_can_expand_to_two_chunks(self):
        one = self.search("OpenCGS upstream CLI")
        paths = [r["path"] for r in one["results"]]
        self.assertEqual(len(set(paths)), len(paths))
        two = self.search("OpenCGS upstream CLI", max_chunks_per_file=2)
        self.assertEqual(2, sum(r["path"].endswith("opencgs.md") for r in two["results"]))

    def test_body_excerpt_has_actual_source_line(self):
        result = self.search("external_solver.py")["results"][0]
        source = (self.root / result["path"]).read_text().splitlines()
        self.assertIn(result["excerpt"].lstrip("…"), source[result["excerpt_line"] - 1])
        self.assertFalse(result["excerpt"].startswith(("title:", "tags:", "---")))

    def test_identifier_boundary_does_not_accept_similar_symbol(self):
        self.assertFalse(history.identifier_match("cacheKey", "cacheKeyExtra"))
        self.assertFalse(history.identifier_match("solver.py", "src/solver.py.bak"))
        self.assertTrue(history.identifier_match("cacheKey", "Use cacheKey."))
        self.assertTrue(history.identifier_match("solver.py", "src/solver.py:21"))

    def test_no_variants_disables_expansion_and_spacing_fallback(self):
        payload = self.search("수리상한", use_variants=False)
        self.assertEqual([], payload["results"])
        self.assertEqual([("original", "수리상한", 1.0)], payload["variants"])
        self.assertTrue(self.search("수리상한")["results"])

    def test_filters_apply_before_ranking(self):
        self.assertEqual([], self.search("export_evidence", statuses=["accepted"])["results"])
        self.assertEqual([], self.search("observation_at", kinds=["decisions"])["results"])
        self.assertEqual([], self.search("request_id", scope="history/changes")["results"])
        self.assertTrue(self.search("request_id", scope="history/decisions", statuses=["accepted"])["results"])

    def test_missing_identifier_is_diagnostic_not_confident_tail(self):
        payload = self.search("why physical_at")
        self.assertEqual([], payload["results"])
        self.assertIn("exact_match_missing", {d["code"] for d in payload["diagnostics"]})
        json.dumps(payload)

    def test_empty_scope_and_invalid_budget(self):
        self.assertEqual([], self.search("anything", scope="history/no-such-scope")["results"])
        self.assertEqual([], self.search("")["results"])
        with self.assertRaises(ValueError):
            self.search("anything", max_chunks_per_file=3)

    def test_search_does_not_modify_fixture_files(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.md")}
        self.search("OpenCGS upstream CLI")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.md")})


if __name__ == "__main__":
    unittest.main()
