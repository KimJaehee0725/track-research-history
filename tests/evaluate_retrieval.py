"""Evaluate frozen evidence queries without writing to a project history.

python3 tests/evaluate_retrieval.py --script scripts/history.py
Use a saved baseline history.py with --script to compare the same fixture.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def evaluate(script: Path) -> dict:
    spec = importlib.util.spec_from_file_location("evaluated_history", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = json.loads((ROOT / "tests/fixtures/retrieval_cases.json").read_text())
    with tempfile.TemporaryDirectory(prefix="history-retrieval-eval-") as tmp:
        root = Path(tmp)
        docs = []
        for item in fixture["documents"]:
            path = root / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (f'# {item["title"]}\n\nStatus: {item["status"]}\n\n## Evidence\n\n'
                   + item["body"] + "\n\n" + item.get("extra", ""))
            path.write_text(raw)
            docs.extend(module.search_documents_for_file(root, path, raw, item["status"], "active"))
        rows = []
        start = time.perf_counter()
        for case in fixture["cases"]:
            payload = module.bm25_search_documents(docs, case["query"], 8)
            paths = [hit["path"] for hit in payload["results"]]
            passed = not paths if case.get("empty") else bool(paths and paths[0] == case["expected"])
            rows.append({
                "query": case["query"], "expected": case.get("expected"),
                "should_abstain": case.get("empty", False), "passed": passed,
                "paths": paths, "unique_files": len(set(paths)),
                "excerpt_chars": sum(len(hit["excerpt"]) for hit in payload["results"]),
            })
        elapsed = time.perf_counter() - start
    answerable = [row for row in rows if not row["should_abstain"]]
    absent = [row for row in rows if row["should_abstain"]]
    return {
        "fixture": "retrieval_cases.json", "cases": len(rows),
        "top1_evidence": {"passed": sum(row["passed"] for row in answerable), "total": len(answerable)},
        "no_evidence_abstention": {"passed": sum(row["passed"] for row in absent), "total": len(absent)},
        "all_cases_passed": all(row["passed"] for row in rows),
        "elapsed_seconds": round(elapsed, 4), "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=ROOT / "scripts/history.py")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.script.resolve()), ensure_ascii=False, indent=2))
