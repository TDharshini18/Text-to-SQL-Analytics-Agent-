# Benchmarks

Evaluation of the text-to-SQL agent on the [BIRD](https://bird-bench.github.io/) mini-dev set
(500 SQLite questions, 11 databases). Metric: **execution accuracy (EX)**, where a prediction is
correct when it returns the same set of rows as the gold SQL.

## Final result

Model `openai/gpt-oss-120b` (Groq), schema linking on, max 3 attempts, BIRD evidence hints on.
499 of 500 questions scored (q701's reference SQL cannot be scored).

| Difficulty  | n   | EX    | First try |
|-------------|-----|-------|-----------|
| simple      | 148 | 77.0% | 75.7%     |
| moderate    | 250 | 57.2% | 55.6%     |
| challenging | 101 | 52.5% | 52.5%     |
| **total**   | 499 | **62.1%** | 60.9% |

- Self-correction loop: 6 wrong answers fixed, 0 broken (+1.2 points).
- Schema linking recall (all gold tables linked): 97.8%.
- Cost: about 2.0 LLM calls and 4,400 tokens per question.
- Weakest databases: california_schools 30.0%, financial 43.8%, thrombosis_prediction 46.0%.

Full report: `results/final/full_v2.summary.txt`.

## Ablation: schema linking

Same 100 questions (`--limit 100 --seed 0`), everything else identical.

| | Linking on | Linking off |
|---|---|---|
| EX | 73.0% | 71.0% |
| First try | 70.0% | 66.0% |
| Moderate EX | 77.4% | 73.6% |
| LLM calls / question | 2.04 | 1.08 |
| Tokens / question | 4,466 | 3,859 |

Linking adds about 2 points of EX and 4 points of first-try accuracy, at the cost of one extra
LLM call per question. With n=100 the gap is small, so treat it as a modest gain, not a proven one.
The self-correction loop recovers part of the difference: it fixes 5 answers without linking and 3 with it.

## Error analysis

Of the 499 scored questions, 189 were wrong. Every one of them **ran without an error**, so the
failures are in the logic, not in execution. Only 6 missed a needed table in schema linking.
The self-correction loop cannot help here: it reacts to errors and empty results, and these
queries returned plausible rows.

Grouped by how the predicted SQL differs from the reference SQL (a rough classification by
query shape over 190 rows, which includes the unscorable q701):

| Pattern | Count | What it looks like |
|---|---|---|
| Same shape, different logic or values | 83 | a wrong column or filter value, or a different tie-break |
| Different number of joins | 53 | a table skipped (q408) or one join too many |
| Missing output columns | 22 | the question asks to list names, but only the number is returned (q77) |
| Extra output columns | 19 | helper columns added that the reference does not return |
| Reference has `LIMIT`, prediction does not | 13 | "the school with the highest X" answered with a subquery |

Reading the examples, the errors fall into two groups:

- **Real model mistakes**, such as `SUM(c.id)` where a count was needed (q352) and a missing
  join (q408).
- **Differences that depend on BIRD's reference SQL.** For q41 and q82 the two queries differ only
  in how ties are broken (`ROW_NUMBER` vs `RANK`, `= MAX(...)` vs `LIMIT 1`). For q37 the
  prediction filters out schools with no test-takers and the reference does not, so they can
  disagree on NULL handling. Some of the remaining gap comes from choices the question does not
  settle, not from errors the agent can fix.

`california_schools` is the weakest database (21 wrong) because two tables hold overlapping
columns (`frpm."School Name"` vs `schools.School`, `School Code` vs `CDSCode`) and the reference
SQL picks one of them without saying why.

**Not tried yet:** turning on the Verifier Agent (`use_review`) for the weakest databases, and
few-shot examples of similar questions. Both change the prompts, so each needs a re-run on the
same 100-question sample to be compared fairly. No prompt change was made from this analysis,
because a few examples are not enough to justify one.

## Files

| File | Purpose |
|------|---------|
| `bird_eval.py` | Runs the benchmark and prints the report |
| `compare.py` | Compares two result files question by question |
| `check_quota.py` | Checks that the Groq key can make requests |
| `results/final/` | Full 500-question run (`full_v2`) |
| `results/sample100/` | 100-question ablation: linking on vs off |
| `results/tuning/` | Smoke test and 20-question tuning rounds |
| `results/v1/` | First baseline run |

`results/` is git-ignored; only the code and this README are tracked.

## Usage

Run from `backend/`:

```
python -m benchmarks.check_quota
python -m benchmarks.bird_eval --out results/final/full_v2.jsonl      # resumes if interrupted
python -m benchmarks.bird_eval --limit 100 --seed 0 --out results/sample100.jsonl
python -m benchmarks.bird_eval --report --out results/final/full_v2.jsonl
python -m benchmarks.bird_eval --no-linking --out results/no_linking.jsonl   # ablation
```
