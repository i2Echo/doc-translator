"""Single-PDF regression runner for the BabelDOC internal hooks.

A repeatable command that translates one PDF through the same library entry
point the worker uses (``translate_pdf_with_babeldoc_library``) -- *not* the
HTTP API -- and emits, into a run directory:

* ``mono.pdf``               -- the translated monolingual PDF
* ``doc_translator_ir.json`` -- the hook sidecar (schema v2)
* ``structure_before.json``  / ``structure_after.json`` -- structure snapshots
* ``pages/page-NNN.png``     -- PyMuPDF page renders for visual inspection
* ``metrics.json``           -- the v1 metrics roll-up
* ``baseline.diff.json``     -- regression diff vs the committed baseline (if any)

Usage::

    py -3.11 -m tests.regression.run_single_pdf \
        --input tests/regression/inputs/translate.cli.font.unknown.pdf \
        --output-dir tests/regression/runs/font-unknown \
        --source-language en --target-language zh-CN \
        --model-base-url "$MODEL_BASE_URL" --model-api-key "$MODEL_API_KEY" \
        --model-name "$MODEL_NAME"

Add ``--update-baseline`` to (re)write ``tests/regression/baselines/<name>.metrics.json``.
When ``--name`` is omitted, the output directory name is used so
``tests/regression/runs/font-unknown`` matches ``baselines/font-unknown.metrics.json``.
Without it, the runner diffs against the baseline and exits non-zero on
regressions (worsening directions only).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Make the api package importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_ROOT = _REPO_ROOT / "apps" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from tests.regression import metrics as metrics_module  # noqa: E402


def _build_runtime_settings(args: argparse.Namespace):
    """Construct a DB-free ``RuntimeSettings`` for the runner.

    Only the model + ocr fields are consumed by the translation path; the
    storage/limits fields are inert here but required by the dataclass.
    ``RuntimeSettings`` is imported lazily so module import does not pull in
    sqlalchemy (which the runner does not otherwise need).
    """

    from doc_translator.settings_service import RuntimeSettings

    return RuntimeSettings(
        storage_mode="local",
        local_storage_path=str(_REPO_ROOT / "tests" / "regression" / "runs"),
        file_retention_days=7,
        model_base_url=args.model_base_url,
        model_api_key=args.model_api_key,
        model_name=args.model_name,
        model_timeout_seconds=args.model_timeout_seconds,
        ocr_enabled=args.use_ocr_workaround,
        ocr_language_hint="auto",
        max_upload_mb=100,
        max_concurrent_jobs=4,
    )


def _render_pages_to_png(pdf_path: Path, pages_dir: Path, dpi: int = 150) -> int:
    """Render every page of ``pdf_path`` to ``pages_dir/page-NNN.png``."""

    import fitz  # PyMuPDF

    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered = 0
    with fitz.open(str(pdf_path)) as doc:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for page_index, page in enumerate(doc):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            png_path = pages_dir / f"page-{page_index + 1:03d}.png"
            pixmap.save(str(png_path))
            rendered += 1
    return rendered


def _baseline_path(name: str) -> Path:
    return _REPO_ROOT / "tests" / "regression" / "baselines" / f"{name}.metrics.json"


def _sample_name(args: argparse.Namespace, input_path: Path, output_dir: Path) -> str:
    if args.name:
        return args.name
    return output_dir.name or input_path.stem


def _remove_if_exists(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _move_replace(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    _remove_if_exists(dst)
    shutil.move(str(src), str(dst))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a single PDF through the BabelDOC hooks and collect metrics.")
    parser.add_argument("--input", required=True, type=Path, help="Input PDF path.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Run output directory.")
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--target-language", default="zh-CN")
    parser.add_argument("--qps", type=int, default=6)
    parser.add_argument("--model-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--model-api-key", default="")
    parser.add_argument("--model-name", default="gpt-4.1-mini")
    parser.add_argument("--model-timeout-seconds", type=int, default=120)
    parser.add_argument("--use-ocr-workaround", action="store_true")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--update-baseline", action="store_true", help="Write/overwrite the baseline metrics for this sample.")
    parser.add_argument("--name", default=None, help="Sample name for baseline files (defaults to output dir name).")
    args = parser.parse_args(argv)

    input_path: Path = args.input.resolve()
    if not input_path.exists():
        print(f"error: input PDF not found: {input_path}", file=sys.stderr)
        return 2
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    working_dir = output_dir / "working"
    working_dir.mkdir(parents=True, exist_ok=True)
    sample_name = _sample_name(args, input_path, output_dir)
    for stale_name in (
        "mono.pdf",
        "doc_translator_ir.json",
        "structure_before.json",
        "structure_after.json",
        "metrics.json",
        "baseline.diff.json",
    ):
        _remove_if_exists(output_dir / stale_name)
    _remove_if_exists(output_dir / "pages")

    runtime = _build_runtime_settings(args)
    babeldoc_input_path = input_path
    used_ocr_preprocessing = False
    if args.use_ocr_workaround:
        from doc_translator.translation import _prepare_pdf_for_babeldoc

        prepared_input_path = working_dir / f"{input_path.stem}.ocr-prepared.pdf"
        _page_count, used_ocr_preprocessing = _prepare_pdf_for_babeldoc(
            str(input_path),
            prepared_input_path,
            runtime,
        )
        if used_ocr_preprocessing:
            babeldoc_input_path = prepared_input_path

    print(f"[run] translating {input_path.name} -> {output_dir}")
    # Imported lazily so ``--help`` and metric-only invocations do not require
    # the full BabelDOC / sqlalchemy runtime to be installed.
    from doc_translator.babeldoc_runner import translate_pdf_with_babeldoc_library

    result = translate_pdf_with_babeldoc_library(
        babeldoc_input_path,
        output_dir,
        working_dir,
        runtime,
        source_language=args.source_language,
        target_language=args.target_language,
        use_ocr_workaround=args.use_ocr_workaround or used_ocr_preprocessing,
        qps=args.qps,
        report_interval=0.5,
    )

    # Normalize outputs into the run dir with stable names.
    mono_pdf = output_dir / "mono.pdf"
    if result.mono_output and result.mono_output.exists():
        _move_replace(result.mono_output, mono_pdf)
    sidecar_dst = output_dir / "doc_translator_ir.json"
    if result.hook_sidecar and result.hook_sidecar.exists():
        _move_replace(result.hook_sidecar, sidecar_dst)
    for stage, snapshot in (("before", result.structure_before), ("after", result.structure_after)):
        if snapshot and snapshot.exists():
            dst = output_dir / f"structure_{stage}.json"
            _move_replace(snapshot, dst)

    pages_dir = output_dir / "pages"
    page_count = _render_pages_to_png(mono_pdf, pages_dir, dpi=args.dpi)
    print(f"[run] rendered {page_count} page PNGs into {pages_dir}")

    metrics = metrics_module.compute_metrics(
        output_dir=output_dir,
        mono_pdf=mono_pdf,
        input_name=sample_name,
    )
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[run] wrote metrics -> {metrics_path}")

    if args.update_baseline:
        baseline = _baseline_path(sample_name)
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[run] updated baseline -> {baseline}")
        return 0

    baseline = _baseline_path(sample_name)
    if not baseline.exists():
        print(f"[run] no baseline at {baseline}; skipping diff (run with --update-baseline to create one).")
        return 0
    baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
    diff = metrics_module.diff_metrics(baseline_data, metrics)
    (output_dir / "baseline.diff.json").write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    if diff["failed"]:
        print("[run] REGRESSIONS vs baseline:", file=sys.stderr)
        for reg in diff["regressions"]:
            print(
                f"  {reg['gate']}: {reg['before']} -> {reg['after']} (+{reg['delta']})",
                file=sys.stderr,
            )
        return 1
    print("[run] no regressions vs baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
