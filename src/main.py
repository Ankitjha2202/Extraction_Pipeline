"""CLI entrypoint for invoice extraction and metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cmd_extract(args: argparse.Namespace) -> int:
    from src.pipeline import discover_pdfs, run_extraction, save_result, process_pdf
    from src.mistral_client import MistralOCRClient
    from src.metrics import build_metrics, write_metrics

    try:
        if args.file:
            pdf = Path(args.file)
            if not pdf.exists():
                print(f"File not found: {pdf}", file=sys.stderr)
                return 1
            client = MistralOCRClient()
            result = process_pdf(pdf, client=client, force=args.force)
            out = save_result(result)
            print(f"Wrote {out}")
        else:
            pdfs = discover_pdfs()
            print(f"Found {len(pdfs)} PDF(s) under data/")
            results = run_extraction(pdfs=pdfs, force=args.force)
            print(f"Wrote {len(results)} JSON file(s) to output/json/")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    metrics = build_metrics(gt_path=Path(args.gt) if args.gt else None)
    path = write_metrics(metrics)
    print(f"Metrics: {path}")
    print(
        json.dumps(
            {
                "invoicesProcessed": metrics["invoicesProcessed"],
                "totalFieldsExtracted": metrics["totalFieldsExtracted"],
                "fieldsRequiringHumanReview": metrics["fieldsRequiringHumanReview"],
                "mandatoryFieldsSuccessfullyExtracted": metrics[
                    "mandatoryFieldsSuccessfullyExtracted"
                ],
                "mandatoryFieldsRequiringHumanReview": metrics[
                    "mandatoryFieldsRequiringHumanReview"
                ],
                "invoicesRequiringHumanReview": metrics["invoicesRequiringHumanReview"],
                "missedReviewRate": metrics.get("missedReviewRate"),
            },
            indent=2,
        )
    )
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    from src.metrics import build_metrics, write_metrics

    gt = Path(args.gt) if args.gt else None
    metrics = build_metrics(gt_path=gt)
    path = write_metrics(metrics)
    print(f"Wrote {path}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False)[:4000])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mistral-powered invoice extraction pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Run OCR + extraction on invoices")
    extract.add_argument(
        "--file",
        type=str,
        default=None,
        help="Process a single PDF instead of all under data/",
    )
    extract.add_argument(
        "--force",
        action="store_true",
        help="Ignore OCR cache and re-call Mistral",
    )
    extract.add_argument(
        "--gt",
        type=str,
        default=None,
        help="Optional ground-truth JSON for missed-review rate",
    )
    extract.set_defaults(func=cmd_extract)

    metrics = sub.add_parser("metrics", help="Recompute metrics from output/json")
    metrics.add_argument(
        "--gt",
        type=str,
        default=None,
        help="Ground-truth JSON path for missed-review rate",
    )
    metrics.set_defaults(func=cmd_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
