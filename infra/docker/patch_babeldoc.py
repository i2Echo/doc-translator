from pathlib import Path


PATCHES = (
    (
        Path("/usr/lib/python3.12/site-packages/babeldoc/format/pdf/document_il/midend/typesetting.py"),
        "        line_skip = 1.50 if self.is_cjk else 1.3\n",
        "        line_skip = 1.38 if self.is_cjk else 1.3\n",
    ),
    (
        Path("/usr/lib/python3.12/site-packages/babeldoc/format/pdf/document_il/midend/paragraph_finder.py"),
        """        paragraph.first_line_indent = False
        if (
            paragraph.pdf_paragraph_composition
            and paragraph.pdf_paragraph_composition[0].pdf_line
            and paragraph.pdf_paragraph_composition[0]
            .pdf_line.pdf_character[0]
            .visual_bbox.box.x
            - paragraph.box.x
            > 1
        ):
            paragraph.first_line_indent = True
""",
        """        paragraph.first_line_indent = False
        if (
            paragraph.pdf_paragraph_composition
            and paragraph.pdf_paragraph_composition[0].pdf_line
        ):
            first_line = paragraph.pdf_paragraph_composition[0].pdf_line
            first_line_offset = first_line.pdf_character[0].visual_bbox.box.x - paragraph.box.x
            first_line_height = first_line.box.y2 - first_line.box.y
            indent_threshold = max(4.0, first_line_height * 0.5)
            if first_line_offset > indent_threshold:
                paragraph.first_line_indent = True
""",
    ),
    (
        Path("/usr/lib/python3.12/site-packages/babeldoc/format/pdf/document_il/midend/styles_and_formulas.py"),
        """    def _calculate_base_style(self, paragraph) -> PdfStyle:
        \"\"\"计算段落的基准样式（除公式外所有文字样式的交集）\"\"\"
        styles = []
        for comp in paragraph.pdf_paragraph_composition:
            if isinstance(comp, PdfFormula):
                continue
            if not comp.pdf_line:
                continue
            for char in comp.pdf_line.pdf_character:
                styles.append(char.pdf_style)

        if not styles:
            return None

        # 返回所有样式的交集
        base_style = styles[0]
        for style in styles[1:]:
            # 更新基准样式为所有样式的交集
            base_style = self._merge_styles(base_style, style)

        # 如果 font_id 或 font_size 为 None，则使用众数
        if base_style.font_id is None:
            base_style.font_id = self._get_mode_value([s.font_id for s in styles])
        if base_style.font_size is None:
            base_style.font_size = self._get_mode_value([s.font_size for s in styles])

        return base_style

    def _get_mode_value(self, values):
        \"\"\"计算列表中的众数\"\"\"
        if not values:
            return None
        from collections import Counter

        counter = Counter(values)
        return counter.most_common(1)[0][0]
""",
        """    def _calculate_base_style(self, paragraph) -> PdfStyle:
        \"\"\"计算段落的基准样式（除公式外所有文字样式的交集）\"\"\"
        import statistics

        styles = []
        for comp in paragraph.pdf_paragraph_composition:
            if isinstance(comp, PdfFormula):
                continue
            if not comp.pdf_line:
                continue
            for char in comp.pdf_line.pdf_character:
                styles.append(char.pdf_style)

        if not styles:
            return None

        dominant_styles = self._get_dominant_style_cluster(styles)

        font_id = styles[0].font_id
        font_size = styles[0].font_size
        graphic_state = styles[0].graphic_state
        for style in styles[1:]:
            if font_id is not None and style.font_id != font_id:
                font_id = None
            if (
                font_size is not None
                and (style.font_size is None or math.fabs(font_size - style.font_size) >= 0.02)
            ):
                font_size = None
            graphic_state = self._merge_graphic_states(graphic_state, style.graphic_state)

        base_style = PdfStyle(
            font_id=font_id,
            font_size=font_size,
            graphic_state=graphic_state,
        )

        if base_style.font_id is None:
            base_style.font_id = self._get_mode_value([s.font_id for s in dominant_styles])
        if base_style.font_size is None:
            dominant_font_sizes = [s.font_size for s in dominant_styles if s and s.font_size is not None]
            if dominant_font_sizes:
                base_style.font_size = statistics.median(dominant_font_sizes)
            else:
                base_style.font_size = self._get_mode_value([s.font_size for s in styles])

        return base_style

    def _get_mode_value(self, values):
        \"\"\"计算列表中的众数\"\"\"
        if not values:
            return None
        from collections import Counter

        counter = Counter(values)
        return counter.most_common(1)[0][0]

    def _get_dominant_style_cluster(self, styles: list[PdfStyle]) -> list[PdfStyle]:
        valid_styles = [style for style in styles if style and style.font_size is not None]
        if not valid_styles:
            return styles

        sorted_styles = sorted(valid_styles, key=lambda style: style.font_size)
        clusters: list[list[PdfStyle]] = [[sorted_styles[0]]]
        tolerance = 0.75
        for style in sorted_styles[1:]:
            if abs(style.font_size - clusters[-1][-1].font_size) <= tolerance:
                clusters[-1].append(style)
            else:
                clusters.append([style])
        return max(clusters, key=len)
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
