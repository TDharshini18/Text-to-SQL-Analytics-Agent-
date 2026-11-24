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
