"""Compare two benchmark result files question by question, and show the misses of the second.

  python -m benchmarks.compare results/v1/bird_minidev.jsonl results/tuning/tune_r1.jsonl
"""

import json
import sqlite3
import sys
from pathlib import Path

from benchmarks.bird_eval import DEFAULT_DATA, run_sql


def load(path: str) -> dict:
    return {
        r["question_id"]: r
        for r in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines())
    }


def main():
    old, new = load(sys.argv[1]), load(sys.argv[2])
    common = [q for q in new if q in old]
    print(f"Same {len(common)} questions:  before {sum(old[q]['correct'] for q in common)}"
          f"  after {sum(new[q]['correct'] for q in common)}")
    for q in common:
        if old[q]["correct"] != new[q]["correct"]:
            print(f"  q{q}: {'wrong -> RIGHT' if new[q]['correct'] else 'right -> WRONG'}")

    evidence = {x["question_id"]: x["evidence"] for x in json.loads((DEFAULT_DATA / "mini_dev_sqlite.json").read_text(encoding="utf-8"))}
    print("\nStill wrong in the second file:\n")
    for q, r in new.items():
        if r["correct"]:
            continue
        db = DEFAULT_DATA / "dev_databases" / r["db_id"] / f"{r['db_id']}.sqlite"
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        gold = run_sql(conn, r["gold_sql"])
        pred = run_sql(conn, r["pred_sql"]) if r["pred_sql"] else []
        print(f"### q{q} [{r['difficulty']}] {r['question']}")
        print(f"HINT: {evidence[q]}")
        print(f"GOLD: {' '.join(r['gold_sql'].split())}")
        print(f"PRED: {' '.join((r['pred_sql'] or r['error'] or '').split())}")
        if len(r["attempts"]) > 1:
            print(f"ATTEMPTS: {[(a['n'], a.get('error') or a.get('note') or 'ok') for a in r['attempts']]}")
        print(f"gold {len(gold)} rows {gold[:3]} | pred {len(pred)} rows {pred[:3]}\n")
        conn.close()


if __name__ == "__main__":
    main()
