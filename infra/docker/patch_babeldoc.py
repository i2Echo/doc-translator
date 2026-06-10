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

THAI_FONT_METADATA_PATCH = r'''

# Doc Translator compatibility patch: BabelDOC 0.6.2 does not ship a Thai font
# family, but the backend image installs Noto Thai fonts from Debian packages.
TH_FONT_FAMILY = {
    "script": [
        "NotoSansThai-Regular.ttf",
        "NotoSansThai-Bold.ttf",
    ],
    "normal": [
        "NotoSerifThai-Regular.ttf",
        "NotoSerifThai-Bold.ttf",
        "NotoSansThai-Regular.ttf",
        "NotoSansThai-Bold.ttf",
    ],
    "fallback": [
        "NotoSans-Regular.ttf",
        "NotoSans-Bold.ttf",
        "GoNotoKurrent-Regular.ttf",
        "GoNotoKurrent-Bold.ttf",
    ],
    "base": [
        "NotoSansThai-Regular.ttf",
    ],
}

EMBEDDING_FONT_METADATA.update(
    {
        "NotoSansThai-Regular.ttf": {
            "ascent": 1061,
            "bold": 0,
            "descent": -450,
            "encoding_length": 2,
            "file_name": "NotoSansThai-Regular.ttf",
            "font_name": "Noto Sans Thai Regular",
            "italic": 0,
            "monospace": 0,
            "serif": 0,
            "sha3_256": "0b89f424b0ce8abbb2c0ed7a5c93de41da62b9b078de718dc58278805341dbc0",
            "size": 37744,
        },
        "NotoSansThai-Bold.ttf": {
            "ascent": 1061,
            "bold": 1,
            "descent": -450,
            "encoding_length": 2,
            "file_name": "NotoSansThai-Bold.ttf",
            "font_name": "Noto Sans Thai Bold",
            "italic": 0,
            "monospace": 0,
            "serif": 0,
            "sha3_256": "c7a558f1ceb412e0723c02d9fbc352b1391a740d118335e7d40587adce25d4c0",
            "size": 37788,
        },
        "NotoSerifThai-Regular.ttf": {
            "ascent": 1064,
            "bold": 0,
            "descent": -534,
            "encoding_length": 2,
            "file_name": "NotoSerifThai-Regular.ttf",
            "font_name": "Noto Serif Thai Regular",
            "italic": 0,
            "monospace": 0,
            "serif": 1,
            "sha3_256": "fa5d3f2c89fcd1df32232838f8b68282afcf73e11077b0b2c2737b63e94972ad",
            "size": 45992,
        },
        "NotoSerifThai-Bold.ttf": {
            "ascent": 1064,
            "bold": 1,
            "descent": -534,
            "encoding_length": 2,
            "file_name": "NotoSerifThai-Bold.ttf",
            "font_name": "Noto Serif Thai Bold",
            "italic": 0,
            "monospace": 0,
            "serif": 1,
            "sha3_256": "7cf3f62aeaa69cea7c28de637a22ddba0256c8121b09721dc197f9021ac56d38",
            "size": 46992,
        },
    }
)
ALL_FONT_FAMILY["TH"] = TH_FONT_FAMILY
ALL_FONT_FAMILY["THAI"] = TH_FONT_FAMILY


def get_font_family(lang_code: str):
    lang_code = lang_code.upper()
    if "THAI" in lang_code or lang_code == "TH":
        font_family = TH_FONT_FAMILY
    elif "KR" in lang_code or "KOREAN" in lang_code:
        font_family = KR_FONT_FAMILY
    elif "JP" in lang_code or "JA" in lang_code or "JAPANESE" in lang_code:
        font_family = JP_FONT_FAMILY
    elif "HK" in lang_code:
        font_family = HK_FONT_FAMILY
    elif "TW" in lang_code:
        font_family = TW_FONT_FAMILY
    elif "EN" in lang_code:
        font_family = EN_FONT_FAMILY
    elif "CN" in lang_code or "CHINESE" in lang_code:
        font_family = CN_FONT_FAMILY
    else:
        font_family = EN_FONT_FAMILY
    verify_font_family(font_family)
    return font_family
'''

THAI_FONT_ASSETS_PATCH = r'''

# Doc Translator compatibility patch: use Debian-installed Thai fonts instead
# of trying to download them from BabelDOC's asset repository.
_DOC_TRANSLATOR_SYSTEM_FONT_PATHS = {
    "NotoSansThai-Regular.ttf": Path("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
    "NotoSansThai-Bold.ttf": Path("/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf"),
    "NotoSerifThai-Regular.ttf": Path("/usr/share/fonts/truetype/noto/NotoSerifThai-Regular.ttf"),
    "NotoSerifThai-Bold.ttf": Path("/usr/share/fonts/truetype/noto/NotoSerifThai-Bold.ttf"),
}
_doc_translator_original_get_font_and_metadata_async = get_font_and_metadata_async


async def get_font_and_metadata_async(
    font_file_name: str,
    client: httpx.AsyncClient | None = None,
    fastest_upstream: str | None = None,
    font_metadata: dict | None = None,
):
    system_font_path = _DOC_TRANSLATOR_SYSTEM_FONT_PATHS.get(font_file_name)
    if system_font_path is not None and system_font_path.exists():
        return system_font_path, EMBEDDING_FONT_METADATA[font_file_name]
    return await _doc_translator_original_get_font_and_metadata_async(
        font_file_name,
        client,
        fastest_upstream,
        font_metadata,
    )


def get_font_and_metadata(font_file_name: str):
    return run_coro(get_font_and_metadata_async(font_file_name))
'''


def apply_patch(target: Path, original: str, patched: str) -> None:
    text = target.read_text(encoding="utf-8")
    if patched in text:
        return
    if original not in text:
        raise SystemExit(f"Could not find expected BabelDOC snippet in {target}")
    target.write_text(text.replace(original, patched, 1), encoding="utf-8")


def append_patch(target: Path, marker: str, patch: str) -> None:
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + patch + "\n", encoding="utf-8")


def main() -> None:
    for target, original, patched in PATCHES:
        apply_patch(target, original, patched)
    append_patch(
        babeldoc_path("assets", "embedding_assets_metadata.py"),
        "Doc Translator compatibility patch: BabelDOC 0.6.2 does not ship a Thai font",
        THAI_FONT_METADATA_PATCH,
    )
    append_patch(
        babeldoc_path("assets", "assets.py"),
        "Doc Translator compatibility patch: use Debian-installed Thai fonts",
        THAI_FONT_ASSETS_PATCH,
    )


if __name__ == "__main__":
    main()
