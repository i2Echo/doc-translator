"""Batch regression runner for the PDF layout convergence samples.

Runs the fixed sample set through ``run_single_pdf`` and writes a compact
``batch.summary.json`` into the runs directory.  Use ``--metrics-only`` to
recompute metrics and gates from existing run artifacts without calling the
translator.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.regression import metrics as metrics_module
from tests.regression import run_single_pdf


_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGRESSION_ROOT = _REPO_ROOT / "tests" / "regression"


@dataclass(frozen=True, slots=True)
class Sample:
    name: str
    input_path: Path
    source_language: str = "en"
    target_language: str = "zh-CN"
    use_ocr_workaround: bool = False


_SAMPLES: dict[str, Sample] = {
    "font-unknown": Sample(
        name="font-unknown",
        input_path=_REGRESSION_ROOT / "inputs" / "translate.cli.font.unknown.pdf",
    ),
    "text-with-figure": Sample(
        name="text-with-figure",
        input_path=_REGRESSION_ROOT / "inputs" / "translate.cli.text.with.figure.pdf",
    ),
    "lm555": Sample(
        name="lm555",
        input_path=_REGRESSION_ROOT / "inputs" / "lm555-p1.pdf",
    ),
    "ads1113-p01-p02": Sample(
        name="ads1113-p01-p02",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p01-p02.pdf",
    ),
    "ads1113-p03-p04": Sample(
        name="ads1113-p03-p04",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p03-p04.pdf",
    ),
    "ads1113-p11-p12": Sample(
        name="ads1113-p11-p12",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p11-p12.pdf",
    ),
    "ads1113-p23-p24": Sample(
        name="ads1113-p23-p24",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p23-p24.pdf",
    ),
    "ads1113-p25-p26": Sample(
        name="ads1113-p25-p26",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p25-p26.pdf",
    ),
    "ads1113-p27-p28": Sample(
        name="ads1113-p27-p28",
        input_path=_REGRESSION_ROOT / "inputs" / "ADS1113-p27-p28.pdf",
    ),
    "toc-dot-leaders": Sample(
        name="toc-dot-leaders",
        input_path=_REGRESSION_ROOT / "inputs" / "toc-dot-leaders.pdf",
    ),
    "scanned-ocr-smoke": Sample(
        name="scanned-ocr-smoke",
        input_path=_REGRESSION_ROOT / "inputs" / "scanned-ocr-smoke.pdf",
        use_ocr_workaround=True,
    ),
}


def _baseline_path(sample_name: str) -> Path:
    return _REGRESSION_ROOT / "baselines" / f"{sample_name}.metrics.json"


def _run_dir(runs_dir: Path, sample_name: str) -> Path:
    return runs_dir / sample_name


def _selected_samples(names: list[str] | None) -> list[Sample]:
    if not names:
        return list(_SAMPLES.values())
    samples = []
    for name in names:
        if name not in _SAMPLES:
            known = ", ".join(sorted(_SAMPLES))
            raise SystemExit(f"unknown sample {name!r}; known samples: {known}")
        samples.append(_SAMPLES[name])
    return samples


def _run_single_sample(args: argparse.Namespace, sample: Sample, runs_dir: Path) -> int:
    argv = [
        "--input",
        str(sample.input_path),
        "--output-dir",
        str(_run_dir(runs_dir, sample.name)),
        "--name",
        sample.name,
        "--source-language",
        sample.source_language,
        "--target-language",
        sample.target_language,
        "--qps",
        str(args.qps),
        "--model-base-url",
        args.model_base_url,
        "--model-api-key",
        args.model_api_key,
        "--model-name",
        args.model_name,
        "--model-timeout-seconds",
        str(args.model_timeout_seconds),
        "--dpi",
        str(args.dpi),
    ]
    if args.use_ocr_workaround or sample.use_ocr_workaround:
        argv.append("--use-ocr-workaround")
    if args.update_baseline:
        argv.append("--update-baseline")
    return run_single_pdf.main(argv)


def _metrics_result(sample: Sample, runs_dir: Path) -> dict[str, Any]:
    output_dir = _run_dir(runs_dir, sample.name)
    metrics = metrics_module.compute_metrics(
        output_dir=output_dir,
        mono_pdf=output_dir / "mono.pdf",
        input_name=sample.name,
    )
    metrics_path = output_dir / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline_path = _baseline_path(sample.name)
    if not baseline_path.exists():
        return {
            "sample": sample.name,
            "status": "missing_baseline",
            "failed": True,
            "metrics_path": str(metrics_path),
            "regressions": [{"gate": "baseline_exists", "path": str(baseline_path)}],
        }
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    diff = metrics_module.diff_metrics(baseline, metrics)
    diff_path = output_dir / "baseline.diff.json"
    diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "sample": sample.name,
        "status": "failed" if diff["failed"] else "passed",
        "failed": diff["failed"],
        "metrics_path": str(metrics_path),
        "diff_path": str(diff_path),
        "diffs": diff["diffs"],
        "regressions": diff["regressions"],
    }


def _write_summary(runs_dir: Path, results: list[dict[str, Any]]) -> Path:
    summary = {
        "schema_version": 1,
        "samples": results,
        "failed": any(result.get("failed") for result in results),
    }
    summary_path = runs_dir / "batch.summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PDF layout regression sample set.")
    parser.add_argument("--sample", action="append", choices=sorted(_SAMPLES), help="Sample name; repeat to run a subset.")
    parser.add_argument("--runs-dir", type=Path, default=_REGRESSION_ROOT / "runs")
    parser.add_argument("--metrics-only", action="store_true", help="Use existing run artifacts; do not translate PDFs.")
    parser.add_argument("--update-baseline", action="store_true", help="Refresh baselines when translating.")
    parser.add_argument("--qps", type=int, default=6)
    parser.add_argument("--model-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--model-api-key", default="")
    parser.add_argument("--model-name", default="gpt-4.1-mini")
    parser.add_argument("--model-timeout-seconds", type=int, default=120)
    parser.add_argument("--use-ocr-workaround", action="store_true")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args(argv)

    samples = _selected_samples(args.sample)
    runs_dir = args.runs_dir.resolve()
    results: list[dict[str, Any]] = []
    exit_code = 0

    for sample in samples:
        print(f"[batch] sample {sample.name}")
        if not args.metrics_only:
            sample_exit = _run_single_sample(args, sample, runs_dir)
            if sample_exit != 0:
                exit_code = sample_exit
        result = _metrics_result(sample, runs_dir)
        results.append(result)
        if result["failed"]:
            exit_code = 1
            print(f"[batch] regression in {sample.name}", file=sys.stderr)

    summary_path = _write_summary(runs_dir, results)
    print(f"[batch] wrote summary -> {summary_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
