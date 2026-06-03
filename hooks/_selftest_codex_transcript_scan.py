# Codex transcript scanner의 후보 status·dismiss 역기록 회귀를 검증한다.
import importlib.util
import json
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCANNER = HERE / "cairn-codex-transcript-scan.py"
spec = importlib.util.spec_from_file_location("cairn_codex_transcript_scan", SCANNER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}")


def read_candidates(cairn_dir):
    return (Path(cairn_dir) / "sessions" / "codex-ingest-candidates.md").read_text(encoding="utf-8")


def test_status_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        cairn_dir = Path(td) / ".cairn"
        candidate = {
            "tool": "WebSearch",
            "ref": "KC-Fn-62 scanner dismissed fixture",
            "note": "fixture",
        }
        candidate["sig"] = mod.signature(candidate["tool"], candidate["ref"])
        path, items = mod.append_candidates(str(cairn_dir), "/tmp/transcript.jsonl", [candidate])
        body = path.read_text(encoding="utf-8")
        check("신규 후보 status pending 기록", "status: pending" in body)
        check("신규 후보 1건 append", len(items) == 1)

        result = mod.mark_candidates(str(cairn_dir), "dismissed", [candidate["sig"]])
        body = read_candidates(cairn_dir)
        check("dismissed mark count 1", result["count"] == 1)
        check("pending -> dismissed 역기록", f"sig: {candidate['sig']} | tool: WebSearch | status: dismissed" in body)

        _, items2 = mod.append_candidates(str(cairn_dir), "/tmp/transcript-2.jsonl", [candidate])
        check("dismissed sig 재append 억제", items2 == [])

        result2 = mod.mark_candidates(str(cairn_dir), "ingested", [candidate["sig"]])
        body = read_candidates(cairn_dir)
        check("dismissed -> ingested 역기록", result2["count"] == 1 and "status: ingested" in body)

        result3 = mod.mark_candidates(str(cairn_dir), "dismissed", ["000000000000"])
        check("없는 sig mark no-op", result3["count"] == 0)


def test_legacy_lines_default_pending():
    with tempfile.TemporaryDirectory() as td:
        cairn_dir = Path(td) / ".cairn"
        sess = cairn_dir / "sessions"
        sess.mkdir(parents=True)
        path = sess / "codex-ingest-candidates.md"
        path.write_text(
            "# codex-ingest-candidates (volatile — gitignored)\n\n"
            "- ts: 2026-06-03T14:31+09:00 | sig: 042721408643 | tool: WebSearch | ref: legacy\n"
            "  - transcript: /tmp/t.jsonl\n",
            encoding="utf-8",
        )
        statuses = mod.candidate_statuses(path)
        check("legacy status 없음은 pending", statuses["042721408643"] == "pending")
        result = mod.mark_candidates(str(cairn_dir), "dismissed", ["042721408643"])
        body = path.read_text(encoding="utf-8")
        check("legacy 라인에 status 삽입", result["count"] == 1 and "status: dismissed" in body)


def test_invalid_status():
    with tempfile.TemporaryDirectory() as td:
        result = mod.mark_candidates(str(Path(td) / ".cairn"), "suppressed", ["042721408643"])
        check("invalid status 거부", result["count"] == 0 and result.get("error") == "invalid_status")


if __name__ == "__main__":
    test_status_lifecycle()
    test_legacy_lines_default_pending()
    test_invalid_status()
    print(json.dumps({"passed": PASS, "failed": FAIL}, ensure_ascii=False))
    raise SystemExit(0 if FAIL == 0 else 1)
