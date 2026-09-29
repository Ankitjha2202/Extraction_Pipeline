# Spot-check evaluation (missed-review rate)

The assignment asks for the **percentage of extracted values that were incorrect but were not flagged for human review** (missed-review rate). That metric needs ground truth.

## How to produce it

1. Copy the example file:

```bash
cp evaluation/ground_truth.example.json evaluation/ground_truth.json
```

2. Open several extracted files under `output/json/` and fill `evaluation/ground_truth.json` with the correct values for those invoices (at least a few fields per document is enough for a spot-check).

3. Recompute metrics:

```bash
python -m src.main metrics --gt evaluation/ground_truth.json
```

The result is written to `output/metrics.json` as `missedReviewRate` (percent), plus `incorrectUnflagged` / `comparableExtractedValues` and a detail list.

## Notes

- Compare is case-insensitive and whitespace-normalized.
- Only fields with a non-null extracted `value` are counted in the denominator.
- Line items are matched by index (`lineItems[0]`, …); align GT order with the extraction output when possible.
