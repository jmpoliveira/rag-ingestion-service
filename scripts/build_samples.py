"""Build the generated files of the sample corpus from `samples/sources/`.

    pip install -e ".[samples]"
    python scripts/build_samples.py

- `security-whitepaper.md` -> `knowledge-base/security-whitepaper.pdf`, one page per section
  (sections separated by `<!-- page -->`), so the evals cover the PDF path and page numbers.
  The PDF is built in reportlab's invariant mode: no timestamps or random ids, so the same
  source gives the same bytes, the same content hash, and no needless re-ingestion.
- `slack-integration.md` -> `knowledge-base/integrations/slack-integration.md`, with every
  `{{HIDDEN:...}}` block encoded as Unicode tag characters (U+E0000 block, "ASCII smuggling").
  They are invisible in editors and browsers but readable by a model. It is a planted attack
  for the evals (ADR 0007): the ingestion must strip it.

The generated files are committed, so ingesting the samples needs none of this.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "samples" / "sources"
OUTPUT = ROOT / "samples" / "knowledge-base"

PAGE_BREAK = "<!-- page -->"
_HIDDEN = re.compile(r"\{\{HIDDEN:(.*?)\}\}", re.DOTALL)
_TAG_BASE = 0xE0000


def hide(text: str) -> str:
    """Encode printable ASCII as invisible Unicode tag characters."""
    return "".join(chr(_TAG_BASE + ord(ch)) for ch in text if 0x20 <= ord(ch) < 0x7F)


def build_hidden_injection(source: Path, target: Path) -> None:
    text = source.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_HIDDEN.sub(lambda m: hide(m.group(1)), text), encoding="utf-8")


def _flowables(block: str) -> list[object]:
    styles = getSampleStyleSheet()
    flowables: list[object] = []
    for paragraph in (p.strip() for p in block.split("\n\n")):
        if not paragraph:
            continue
        text = " ".join(paragraph.split())
        if text.startswith("# "):
            flowables.append(Paragraph(text[2:], styles["Title"]))
        elif text.startswith("## "):
            flowables.append(Paragraph(text[3:], styles["Heading2"]))
        else:
            flowables.append(Paragraph(text, styles["BodyText"]))
        flowables.append(Spacer(1, 0.2 * cm))
    return flowables


def build_pdf(source: Path, target: Path) -> int:
    rl_config.invariant = True  # reproducible bytes: no creation date, fixed document id
    pages = source.read_text(encoding="utf-8").split(PAGE_BREAK)
    story: list[object] = []
    for number, page in enumerate(pages):
        if number:
            story.append(PageBreak())
        story.extend(_flowables(page))
    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        title="Tessera Security Whitepaper",
        author="Tessera Software (fictional)",
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
    )
    document.build(story)  # pyright: ignore[reportUnknownMemberType]
    return len(pages)


def main() -> None:
    pages = build_pdf(SOURCES / "security-whitepaper.md", OUTPUT / "security-whitepaper.pdf")
    print(f"security-whitepaper.pdf: {pages} pages")
    build_hidden_injection(
        SOURCES / "slack-integration.md", OUTPUT / "integrations" / "slack-integration.md"
    )
    print("integrations/slack-integration.md: hidden block encoded")


if __name__ == "__main__":
    main()
