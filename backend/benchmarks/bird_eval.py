"""BIRD mini-dev benchmark for the text-to-SQL agent.

Measures execution accuracy (EX), the official BIRD metric: a prediction is correct when it
returns the same set of rows as the gold SQL. Also reports, from the same run:

  - first-attempt EX   accuracy before any self-correction (attempt 1 only)
  - repair stats       how many queries failed, were repaired, and ended up correct
  - linking recall     share of questions where every table the gold SQL uses was linked
  - cost               LLM calls and tokens per question

Run from the backend folder:

  python -m benchmarks.bird_eval --limit 50                    # random sample of 50 (seed 0)
  python -m benchmarks.bird_eval                               # all 500 questions
  python -m benchmarks.bird_eval --no-linking --out results/no_linking.jsonl   # ablation

Results are appended to a JSONL file, one line per question, so an interrupted run resumes
where it stopped. `--report` alone re-prints the summary of an existing results file.
"""

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from app import config
from app.agents import pipeline
from app.database.connection import get_connection
from app.services import llm

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = BACKEND_DIR.parent.parent / "SQL_AI" / "data" / "bird" / "dev"
EVAL_TIMEOUT_S = 30  # same as the official BIRD evaluation


# ---------- execution and comparison ----------

def run_sql(conn: sqlite3.Connection, sql: str, timeout_s: float = EVAL_TIMEOUT_S) -> list[tuple]:
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.set_progress_handler(None, 0)


def same_result(pred: list[tuple], gold: list[tuple]) -> bool:
    # Official BIRD rule: compare as sets (row order and duplicates are ignored).
    return set(pred) == set(gold)


def tables_in_sql(sql: str, table_names: list[str]) -> set[str]:
    found = set()
    for name in table_names:
        if re.search(rf'(?<![\w.]){re.escape(name)}(?!\w)|[`"\[]{re.escape(name)}[`"\]]', sql, re.IGNORECASE):
            found.add(name)
    return found


# ---------- one question ----------

def evaluate(item: dict, db_path: Path, args) -> dict:
    question = item["question"]
    if args.evidence and item.get("evidence"):
        question += f"\nHint: {item['evidence']}"

    before = dict(llm.usage)
    started = time.monotonic()
    record = {
        "question_id": item["question_id"],
        "db_id": item["db_id"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "gold_sql": item["SQL"],
    }

    conn = get_connection(db_path)
    try:
        linking, attempts, pred_sql, error = None, [], None, None
        try:
            for event in pipeline.run_pipeline(
                conn,
                question,
                use_linking=args.linking,
                max_attempts=args.max_attempts,
                explain_results=False,
            ):
                if event["type"] == "linking":
                    linking = event
                elif event["type"] == "attempt":
                    attempts.append({k: event[k] for k in ("n", "sql", "ok", "error", "rows", "note") if k in event})
                elif event["type"] == "result":
                    pred_sql = event["response"]["sql"]
        except pipeline.PipelineError as e:
            error = e.message
        except llm.LLMError:
            # Out of quota or API down: never record this as a wrong answer; the caller decides.
            raise

        gold = run_sql(conn, item["SQL"])

        def is_correct(sql: str | None) -> bool:
            if sql is None:
                return False
            try:
                return same_result(run_sql(conn, sql), gold)
            except sqlite3.Error:
                return False

        correct = is_correct(pred_sql)
        # Accuracy without self-correction: attempt 1's query, if it ran at all.
        first_correct = (
            correct if attempts and attempts[0]["sql"] == pred_sql
            else bool(attempts) and attempts[0]["ok"] and is_correct(attempts[0]["sql"])
        )

        all_tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        gold_tables = tables_in_sql(item["SQL"], all_tables)
        linked = set(linking["tables"]) if linking else set()
    finally:
        conn.close()

    record.update(
        pred_sql=pred_sql,
        correct=correct,
        first_attempt_correct=first_correct,
        attempts=attempts,
        error=error,
        linked_tables=sorted(linked),
        total_tables=linking["total_tables"] if linking else None,
        gold_tables=sorted(gold_tables),
        linking_recall=gold_tables <= {t.lower() for t in linked} | linked,
        linking_method=linking["method"] if linking else None,
        llm_calls=llm.usage["calls"] - before["calls"],
        tokens=(llm.usage["prompt_tokens"] - before["prompt_tokens"])
        + (llm.usage["completion_tokens"] - before["completion_tokens"]),
        seconds=round(time.monotonic() - started, 2),
    )
    return record


def quota_wait_seconds(message: str) -> float | None:
    """Groq's daily limit is a rolling window; its error says e.g. 'Please try again in 7m12.5s'."""
    if "per day" not in message.lower():
        return None
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", message)
    if not m or not any(m.groups()):
        return 600.0
    h, mins, s = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mins * 60 + s + 5


def evaluate_with_quota_waits(item: dict, db_path: Path, args) -> dict:
    for tries in range(1000):
        try:
            return evaluate(item, db_path, args)
        except llm.LLMError as e:
            wait = quota_wait_seconds(str(e))
            if wait is None or not args.wait:
                raise SystemExit(
                    f"\nLLM error on question {item['question_id']}: {e}\n"
                    "Nothing was recorded for it. Re-run the same command to resume."
                )
            print(f"    daily token limit reached, waiting {wait / 60:.1f} min "
                  f"({time.strftime('%H:%M')})", flush=True)
            time.sleep(wait)
    raise SystemExit("Gave up waiting for quota.")


# ---------- summary ----------

def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "-"


def summarize(records: list[dict], label: str) -> str:
    n = len(records)
    if not n:
        return "No results yet."
    lines = [f"BIRD mini-dev (SQLite) - {label}", f"Questions evaluated: {n}", ""]

    by_diff = defaultdict(list)
    for r in records:
        by_diff[r["difficulty"]].append(r)
    lines.append(f"{'':14}{'n':>5}{'EX':>9}{'1st try':>10}")
    for diff in ("simple", "moderate", "challenging"):
        rs = by_diff.get(diff, [])
        if rs:
            lines.append(
                f"{diff:14}{len(rs):>5}{pct(sum(r['correct'] for r in rs), len(rs)):>9}"
                f"{pct(sum(r['first_attempt_correct'] for r in rs), len(rs)):>10}"
            )
    total_ok = sum(r["correct"] for r in records)
    first_ok = sum(r["first_attempt_correct"] for r in records)
    lines.append(f"{'total':14}{n:>5}{pct(total_ok, n):>9}{pct(first_ok, n):>10}")
    lines.append("")

    failed = [r for r in records if r["attempts"] and not r["attempts"][0]["ok"]]
    empty = [r for r in records if r["attempts"] and r["attempts"][0].get("note")]
    fixed = [r for r in records if r["correct"] and not r["first_attempt_correct"]]
    broken = [r for r in records if r["first_attempt_correct"] and not r["correct"]]
    no_sql = [r for r in records if r["pred_sql"] is None]
    lines.append("Self-correction")
    lines.append(f"  attempt 1 failed to execute:     {len(failed)} ({pct(len(failed), n)})")
    lines.append(f"  attempt 1 returned no rows:      {len(empty)} (sent back for review)")
    lines.append(f"  wrong -> right after the loop:   {len(fixed)}")
    lines.append(f"  right -> wrong after the loop:   {len(broken)}")
    lines.append(f"  still no working SQL after loop: {len(no_sql)}")
    lines.append(f"  EX gain from the loop:           +{100 * (total_ok - first_ok) / n:.1f} points")
    lines.append("")

    linked = [r for r in records if r["linking_method"] not in (None, "off")]
    if linked:
        lines.append("Schema linking")
        lines.append(f"  gold tables all linked (recall): {pct(sum(r['linking_recall'] for r in linked), len(linked))}")
        avg_linked = sum(len(r["linked_tables"]) for r in linked) / len(linked)
        avg_total = sum(r["total_tables"] for r in linked) / len(linked)
        lines.append(f"  tables in prompt:                {avg_linked:.1f} of {avg_total:.1f} on average")
        lines.append(f"  fell back to all tables:         {sum(r['linking_method'] == 'fallback' for r in linked)}")
        lines.append("")

    lines.append("Cost")
    lines.append(f"  LLM calls per question:  {sum(r['llm_calls'] for r in records) / n:.2f}")
    lines.append(f"  tokens per question:     {sum(r['tokens'] for r in records) / n:,.0f}")
    lines.append(f"  seconds per question:    {sum(r['seconds'] for r in records) / n:.1f} (includes rate-limit waits)")
    lines.append("")
    lines.append("Per database EX: " + ", ".join(
        f"{db} {pct(sum(r['correct'] for r in rs), len(rs))} ({len(rs)})"
        for db, rs in sorted(_group(records, "db_id").items())
    ))
    return "\n".join(lines)


def _group(records, key):
    groups = defaultdict(list)
    for r in records:
        groups[r[key]].append(r)
    return groups


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="folder with mini_dev_sqlite.json and dev_databases/")
    p.add_argument("--limit", type=int, default=0, help="random sample of N questions (0 = all 500)")
    p.add_argument("--first", type=int, default=0, help="only the first N questions (sorted by database, id)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-linking", dest="linking", action="store_false", help="ablation: send the full schema")
    p.add_argument("--max-attempts", type=int, default=pipeline.MAX_ATTEMPTS)
    p.add_argument("--no-evidence", dest="evidence", action="store_false", help="leave out BIRD's evidence hints")
    p.add_argument("--out", type=Path, default=BACKEND_DIR / "benchmarks" / "results" / "bird_minidev.jsonl")
    p.add_argument("--report", action="store_true", help="only print the summary of --out")
    p.add_argument("--no-wait", dest="wait", action="store_false",
                   help="stop when the daily token limit is hit instead of waiting for quota")
    args = p.parse_args()

    label = (
        f"model {config.GROQ_MODEL}, linking {'on' if args.linking else 'off'}, "
        f"max attempts {args.max_attempts}, evidence {'on' if args.evidence else 'off'}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["question_id"]] = r

    if args.report:
        print(summarize(list(done.values()), label))
        return

    items = json.loads((args.data / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
    if args.limit:
        items = random.Random(args.seed).sample(items, args.limit)
    # Group by database so each database's value index is built once.
    items.sort(key=lambda x: (x["db_id"], x["question_id"]))
    if args.first:
        items = items[: args.first]
    todo = [x for x in items if x["question_id"] not in done]
    print(f"{label}\n{len(items)} questions, {len(items) - len(todo)} already done, {len(todo)} to run\n")

    with args.out.open("a", encoding="utf-8") as f:
        for i, item in enumerate(todo, 1):
            db_path = args.data / "dev_databases" / item["db_id"] / f"{item['db_id']}.sqlite"
            config.DB_PATH = db_path  # the pipeline caches the value index per database file
            r = evaluate_with_quota_waits(item, db_path, args)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            done[r["question_id"]] = r
            mark = "OK " if r["correct"] else ("ERR" if r["pred_sql"] is None else "-- ")
            print(
                f"[{i}/{len(todo)}] {mark} q{r['question_id']:<5} {r['db_id'][:22]:22} {r['difficulty'][:4]} "
                f"attempts={len(r['attempts'])} tokens={r['tokens']:,} {r['seconds']}s",
                flush=True,
            )

    selected = {x["question_id"] for x in items}
    records = [r for qid, r in done.items() if qid in selected]
    report = summarize(records, label)
    print("\n" + report)
    args.out.with_suffix(".summary.txt").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
