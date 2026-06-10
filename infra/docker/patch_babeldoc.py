import sysconfig
from pathlib import Path


SITE_PACKAGES = Path(sysconfig.get_path("purelib"))


def babeldoc_path(*parts: str) -> Path:
    return SITE_PACKAGES.joinpath("babeldoc", *parts)


PATCHES = (
    (
        babeldoc_path("main.py"),
        "import asyncio\n",
        "import asyncio\nimport json\n",
    ),
    (
        babeldoc_path("main.py"),
        """        def progress_handler(event):
            if show_log and random.random() <= 0.1:  # noqa: S311
                logger.info(event)
""",
        """        def progress_handler(event):
            if show_log and event["type"] in {
                "stage_summary",
                "progress_start",
                "progress_update",
                "progress_end",
            }:
                print(
                    "__BABELDOC_PROGRESS__"
                    + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
                    flush=True,
                )
""",
    ),
    (
        babeldoc_path("main.py"),
        """        progress_context, progress_handler = create_progress_handler(
            config, show_log=False
        )
""",
        """        progress_context, progress_handler = create_progress_handler(
            config, show_log=True
        )
""",
    ),
)


def apply_patch(target: Path, original: str, patched: str) -> None:
    text = target.read_text(encoding="utf-8")
    if patched in text:
        return
    if original not in text:
        raise SystemExit(f"Could not find expected BabelDOC snippet in {target}")
    target.write_text(text.replace(original, patched, 1), encoding="utf-8")


def main() -> None:
    for target, original, patched in PATCHES:
        apply_patch(target, original, patched)


if __name__ == "__main__":
    main()
