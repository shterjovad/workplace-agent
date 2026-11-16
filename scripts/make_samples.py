# ruff: noqa: E501
"""Generate the sample policy PDFs and test fixtures for the ingestion demo.

Run with: uv run python scripts/make_samples.py
Output is deterministic and idempotent: existing files are overwritten.
"""

import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

rl_config.invariant = 1  # fixed timestamps and IDs in generated PDFs

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "samples" / "documents"
FIXTURES = ROOT / "samples" / "fixtures"
COMPANY = "Northwind Workplace"
STYLES = getSampleStyleSheet()

type Section = tuple[str, list[str]]

CARRY_SENTENCE = (
    "Employees may carry over up to {n} unused vacation days into the next calendar year."
)
RETREAT_SENTENCE = "The annual company retreat is held every September in Lake Bled, Slovenia."
IMAGE_TEXT = "Helpdesk PIN reset code: 7741"


def _story_from_sections(title: str, sections: list[Section]) -> list:
    story: list = [Paragraph(title, STYLES["Title"]), Paragraph(COMPANY, STYLES["Italic"])]
    story.append(Spacer(1, 0.5 * cm))
    for heading, paragraphs in sections:
        story.append(Paragraph(heading, STYLES["Heading2"]))
        for text in paragraphs:
            story.append(Paragraph(text, STYLES["BodyText"]))
    return story


def _build(path: Path, story: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=path.stem, author=COMPANY, invariant=1)
    doc.build(story)


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _screenshot_png() -> io.BytesIO:
    img = Image.new("RGB", (900, 260), (32, 36, 48))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 900, 40), fill=(60, 70, 95))
    title_font = ImageFont.load_default(size=22)
    body_font = ImageFont.load_default(size=44)
    draw.text((16, 8), "Helpdesk Portal - Self Service", fill="white", font=title_font)
    draw.text((40, 110), IMAGE_TEXT, fill=(120, 255, 160), font=body_font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _filler(topic: str, n: int) -> list[str]:
    return [
        f"This section describes how {topic} applies to every employee of {COMPANY}. "
        "Managers are responsible for communicating these rules to their teams and for "
        "answering questions from new joiners. Where a situation is not covered, employees "
        "should contact the People Team before acting.",
        f"Rule {n}.1: requests relating to {topic} must be made in writing, approved by the "
        "line manager, and recorded in the company portal within five working days.",
    ]


def _simple_policy(title: str, topic: str, headings: list[str]) -> list[Section]:
    sections: list[Section] = [("1. Purpose", [f"This policy sets out {topic} at {COMPANY}."])]
    for i, heading in enumerate(headings, start=2):
        sections.append((f"{i}. {heading}", _filler(topic, i)))
    return sections


def _hr_leave(days: int) -> list:
    sections: list[Section] = [
        ("1. Purpose", ["This policy explains vacation and other leave entitlements."]),
        (
            "2. Entitlement",
            [
                "Full-time employees receive 25 paid vacation days per calendar year, "
                "in addition to public holidays.",
                "Vacation requests are submitted through the company portal and approved "
                "by the line manager.",
            ],
        ),
        (
            "3. Carry-over",
            [
                CARRY_SENTENCE.format(n=days),
                "Days not used by 31 March of the following year are forfeited.",
            ],
        ),
        (
            "4. Sick leave",
            [
                "Employees who are unwell must inform their manager before the start of the "
                "working day. A medical certificate is required after three consecutive days."
            ],
        ),
        ("5. Questions", ["Contact the People Team at people@northwind.example."]),
    ]
    return _story_from_sections("HR Leave Policy", sections)


def _travel() -> list:
    story = _story_from_sections(
        "Travel and Expenses Policy",
        [
            ("1. Purpose", ["This policy covers business travel and expense claims."]),
            (
                "2. Booking",
                [
                    "Book flights and hotels through the approved travel portal at "
                    "least 14 days before departure where possible."
                ],
            ),
            (
                "3. Meal allowance",
                [
                    "Meals during business travel are reimbursed up to the "
                    "daily limits in the table below."
                ],
            ),
        ],
    )
    story.append(
        _table(
            [
                ["Trip type", "Daily meal allowance"],
                ["Domestic", "EUR 45"],
                ["International", "EUR 60"],
            ]
        )
    )
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("4. Per-diem by country", STYLES["Heading2"]))
    story.append(
        Paragraph("The following lodging per-diem limits apply per night.", STYLES["BodyText"])
    )
    countries = [
        "Austria",
        "Belgium",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czechia",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Ireland",
        "Italy",
        "Latvia",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Netherlands",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
        "Switzerland",
        "United Kingdom",
        "Canada",
        "Japan",
        "Singapore",
        "United States",
        "Australia",
        "Brazil",
        "India",
        "Mexico",
        "South Africa",
        "United Arab Emirates",
        "Turkey",
        "Serbia",
        "Albania",
        "North Macedonia",
        "Iceland",
        "Egypt",
        "Morocco",
        "Kenya",
        "Thailand",
        "Vietnam",
    ]
    rows = [["Country", "Hotel per night (EUR)"]]
    rows += [[c, str(90 + (i * 7) % 80)] for i, c in enumerate(countries)]
    story.append(_table(rows))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("5. Claims", STYLES["Heading2"]))
    story.append(
        Paragraph(
            "Submit expense claims with receipts within 30 days of the trip.", STYLES["BodyText"]
        )
    )
    return story


def _it_security() -> list:
    story = _story_from_sections(
        "IT Security Policy",
        [
            ("1. Purpose", ["This policy protects company systems and data."]),
            (
                "2. Passwords",
                [
                    "Passwords must be at least 14 characters and unique per "
                    "system. Multi-factor authentication is mandatory."
                ],
            ),
            (
                "3. Helpdesk self-service",
                [
                    "The screenshot below shows the helpdesk portal "
                    "after a successful identity check."
                ],
            ),
        ],
    )
    story.append(RLImage(_screenshot_png(), width=15 * cm, height=15 * cm * 260 / 900))
    story.append(Paragraph("4. Reporting incidents", STYLES["Heading2"]))
    story.append(
        Paragraph(
            "Report suspected phishing or lost devices to the security team immediately.",
            STYLES["BodyText"],
        )
    )
    return story


def _handbook() -> list:
    story: list = [
        Paragraph("Employee Handbook", STYLES["Title"]),
        Paragraph(COMPANY, STYLES["Italic"]),
    ]
    chapters = [
        "Welcome",
        "Our Values",
        "Working Hours",
        "Teams and Structure",
        "Communication",
        "Learning and Development",
        "Benefits",
        "Workplace Conduct",
        "Office Facilities",
        "Recognition",
        "Leaving the Company",
        "Company Culture",
    ]
    for i, chapter in enumerate(chapters, start=1):
        if i > 1:
            story.append(PageBreak())
        story.append(Paragraph(f"Chapter {i}: {chapter}", STYLES["Heading2"]))
        for p in _filler(chapter.lower(), i):
            story.append(Paragraph(p, STYLES["BodyText"]))
        if i == 12:
            story.append(Paragraph(RETREAT_SENTENCE, STYLES["BodyText"]))
    return story


def _simple(title: str, topic: str, headings: list[str]) -> list:
    return _story_from_sections(title, _simple_policy(title, topic, headings))


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    fixed = (2024, 1, 1, 0, 0, 0)
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Meeting notes: weekly sync.</w:t></w:r></w:p></w:body>"
            "</w:document>"
        ),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(zipfile.ZipInfo(name, fixed), content)
    return buf.getvalue()


def main() -> None:
    docs = {
        "HR Leave Policy": _hr_leave(5),
        "Travel and Expenses Policy": _travel(),
        "IT Security Policy": _it_security(),
        "Onboarding Guide": _simple(
            "Onboarding Guide",
            "onboarding of new employees",
            ["First week", "Equipment and accounts", "Buddy programme"],
        ),
        "Employee Handbook": _handbook(),
        "Remote Work Policy": _simple(
            "Remote Work Policy", "remote and hybrid work", ["Eligibility", "Home office setup"]
        ),
        "Code of Conduct": _simple(
            "Code of Conduct", "professional behaviour", ["Respect", "Conflicts of interest"]
        ),
        "Parental Leave Policy": _simple(
            "Parental Leave Policy", "parental leave", ["Eligibility", "Returning to work"]
        ),
        "Health and Safety Policy": _simple(
            "Health and Safety Policy", "health and safety", ["Fire safety", "First aid"]
        ),
        "Data Protection Policy": _simple(
            "Data Protection Policy",
            "personal data handling",
            ["Retention", "Data subject requests"],
        ),
        "Equipment and Laptop Policy": _simple(
            "Equipment and Laptop Policy", "company equipment", ["Laptop refresh", "Loss or damage"]
        ),
        "Performance Review Guide": _simple(
            "Performance Review Guide", "performance reviews", ["Review cycle", "Goal setting"]
        ),
    }
    for title, story in docs.items():
        _build(DOCS / f"{title}.pdf", story)

    _build(FIXTURES / "updated" / "HR Leave Policy.pdf", _hr_leave(10))

    handbook = PdfReader(str(DOCS / "Employee Handbook.pdf"))
    writer = PdfWriter()
    for page in handbook.pages[:8]:
        writer.add_page(page)
    shortened = FIXTURES / "shortened" / "Employee Handbook.pdf"
    shortened.parent.mkdir(parents=True, exist_ok=True)
    with shortened.open("wb") as fh:
        writer.write(fh)

    sample = PdfReader(str(DOCS / "Code of Conduct.pdf"))
    enc = PdfWriter()
    for page in sample.pages:
        enc.add_page(page)
    enc.encrypt("secret")
    with (FIXTURES / "Confidential Salary Bands.pdf").open("wb") as fh:
        enc.write(fh)

    (FIXTURES / "Policy.pdf").write_text("This is plain text, not a PDF.\n", encoding="utf-8")
    (FIXTURES / "Meeting Notes.docx").write_bytes(_docx_bytes())
    print(f"Wrote {len(docs)} documents to {DOCS} and fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
