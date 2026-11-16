# @spec: 001-document-ingestion-and-qa-cli
# @regression
"""Spec 2.1-2.3: user flows through the `ingest` and `ask` commands (hermetic)."""

import pytest

from tests.acceptance.conftest import World, pdf
from workplace_agent.ingestion.models import PageSpan, ParsedDocument

NOT_FOUND_MESSAGE = "I couldn't find this in the company documents."

pytestmark = pytest.mark.regression

FILLER = "Standard policy wording that appears on every page of the document. " * 12


def _summary(output: str) -> dict[str, int]:
    pairs = (line.split(": ") for line in output.splitlines() if line.split(": ")[0] in COUNTS)
    return {key: int(value) for key, value in pairs}


COUNTS = ("new", "updated", "unchanged", "removed", "failed", "passages in library")


def _fifteen(world: World) -> None:
    for n in range(15):
        world.put(f"Doc {n:02d}.pdf", pdf(f"Document {n} page one. {FILLER}"))


# --- 2.1 -----------------------------------------------------------------------------------


def test_first_ingest_of_15_pdfs_reports_15_new_and_passages(world: World) -> None:
    _fifteen(world)
    result = world.run("ingest")
    counts = _summary(result.stdout)
    assert result.exit_code == 0, result.output
    assert (counts["new"], counts["updated"], counts["unchanged"]) == (15, 0, 0)
    assert (counts["removed"], counts["failed"]) == (0, 0)
    assert counts["passages in library"] > 0


def test_fact_on_page_12_is_cited_as_p_12(world: World) -> None:
    pages = [f"Page {n} general text. {FILLER}" for n in range(1, 12)]
    pages.append("# Events\n\nThe annual retreat is held in Lake Bled.")
    world.put("Employee Handbook.pdf", pdf(*pages))
    world.chat.needles["retreat"] = "Lake Bled"
    assert world.run("ingest").exit_code == 0
    result = world.run("ask", "Where is the retreat?")
    assert "Lake Bled" in result.stdout
    assert "[1] Employee Handbook, p. 12" in result.stdout


def test_figure_only_in_a_table_is_answered_with_its_page(world: World) -> None:
    table = "| Trip type | Daily meal allowance |\n| --- | --- |\n| Domestic | EUR 45 |"
    world.put("Travel.pdf", pdf(f"Intro. {FILLER}", f"# Meals\n\n{table}"))
    world.chat.needles["meal"] = "EUR 45"
    world.run("ingest")
    result = world.run("ask", "What is the meal allowance?")
    assert "EUR 45" in result.stdout
    assert "[1] Travel, p. 2" in result.stdout


def test_text_only_inside_an_image_is_answered_with_its_page(world: World) -> None:
    class ImageParser:
        def parse(self, name: str, data: bytes) -> ParsedDocument:
            md = "# Security\n\nPlain text.\n"
            return ParsedDocument(
                markdown=md,
                page_spans=[PageSpan(1, 0, len(md))],
                uncovered_lines=[(1, "Helpdesk PIN reset code: 7741")],
            )

    world.parser = ImageParser()  # type: ignore[assignment]
    world.put("IT Security.pdf", b"x")
    world.chat.needles["PIN"] = "7741"
    world.run("ingest")
    result = world.run("ask", "What is the PIN reset code?")
    assert "7741" in result.stdout
    assert "[1] IT Security, p. 1" in result.stdout


def test_non_pdf_is_listed_as_skipped_and_run_succeeds(world: World) -> None:
    _fifteen(world)
    world.put("Meeting Notes.docx", b"word")
    result = world.run("ingest")
    assert result.exit_code == 0
    assert "skipped (not a PDF):\n  Meeting Notes.docx" in result.stdout
    assert "new: 15" in result.stdout
    assert "Ingest finished successfully." in result.stdout


# --- 2.2 -----------------------------------------------------------------------------------


def test_rerun_with_no_changes_reports_15_unchanged(world: World) -> None:
    _fifteen(world)
    world.run("ingest")
    counts = _summary(world.run("ingest").stdout)
    assert (counts["unchanged"], counts["new"], counts["updated"]) == (15, 0, 0)
    assert (counts["removed"], counts["failed"]) == (0, 0)


def test_replaced_policy_answers_with_new_limit_only(world: World) -> None:
    world.put("HR Leave Policy.pdf", pdf("Employees may carry over up to 5 days."))
    world.chat.needles["carry"] = "up to 5 days"
    world.run("ingest")
    world.put("HR Leave Policy.pdf", pdf("Employees may carry over up to 10 days."))
    world.chat.needles["carry"] = "up to 10 days"
    result = world.run("ingest")
    assert _summary(result.stdout)["updated"] == 1
    answer = world.run("ask", "How many days can I carry over?").stdout
    assert "10 days" in answer and "5 days" not in answer


def test_deleted_document_gives_not_found_answer(world: World) -> None:
    _fifteen(world)
    world.put("Secret.pdf", pdf("The vault code is 9921."))
    world.chat.needles["vault"] = "9921"
    world.run("ingest")
    world.remove("Secret.pdf")
    counts = _summary(world.run("ingest").stdout)
    assert counts["removed"] == 1
    answer = world.run("ask", "What is the vault code?")
    assert answer.stdout.strip() == NOT_FOUND_MESSAGE


def test_shortened_document_forgets_pages_that_no_longer_exist(world: World) -> None:
    pages = [f"Page {n}. {FILLER}" for n in range(1, 12)] + ["# Events\n\nRetreat is in Lake Bled."]
    world.put("Handbook.pdf", pdf(*pages))
    world.chat.needles["retreat"] = "Lake Bled"
    world.run("ingest")
    world.put("Handbook.pdf", pdf(*pages[:8]))
    counts = _summary(world.run("ingest").stdout)
    assert counts["updated"] == 1
    assert world.run("ask", "Where is the retreat?").stdout.strip() == NOT_FOUND_MESSAGE


def test_renamed_document_is_one_removed_one_new_and_cites_new_title(world: World) -> None:
    world.put("Old Name.pdf", pdf("Parking is on level 2."))
    world.chat.needles["parking"] = "level 2"
    world.run("ingest")
    world.put("New Name.pdf", world.blobs.files.pop("Old Name.pdf"))
    counts = _summary(world.run("ingest").stdout)
    assert (counts["removed"], counts["new"], counts["updated"]) == (1, 1, 0)
    answer = world.run("ask", "Where is parking?").stdout
    assert "[1] New Name, p. 1" in answer and "Old Name" not in answer


def test_emptied_folder_removes_all_15_and_says_no_documents(world: World) -> None:
    _fifteen(world)
    world.run("ingest")
    world.blobs.files.clear()
    result = world.run("ingest")
    assert result.exit_code == 0
    assert _summary(result.stdout)["removed"] == 15
    assert "No documents found in the document folder." in result.stdout


# --- 2.3 -----------------------------------------------------------------------------------


def test_password_protected_pdf_fails_the_run_but_others_are_ingested(world: World) -> None:
    for n in range(14):
        world.put(f"Doc {n:02d}.pdf", pdf(f"Document {n}. {FILLER}"))
    world.put("Confidential Salary Bands.pdf", b"PROTECTED")
    result = world.run("ingest")
    counts = _summary(result.stdout)
    assert (counts["new"], counts["failed"]) == (14, 1)
    assert "Confidential Salary Bands.pdf: password-protected" in result.stdout
    assert "Ingest finished with 1 failed document(s)." in result.stdout
    assert result.exit_code == 1


def test_damaged_pdf_is_reported_not_readable_and_others_continue(world: World) -> None:
    _fifteen(world)
    world.put("Policy.pdf", b"JUNK plain text renamed")
    result = world.run("ingest")
    assert "Policy.pdf: not a readable PDF" in result.stdout
    assert _summary(result.stdout)["new"] == 15
    assert result.exit_code == 1


def test_connection_loss_lists_each_unread_document_as_temporary(world: World) -> None:
    world.put("A.pdf", pdf(f"Readable. {FILLER}"))
    world.put("B.pdf", b"NET one")
    world.put("C.pdf", b"NET two")
    world.parser.offline = True
    result = world.run("ingest")
    assert "B.pdf: temporary problem — try again later" in result.stdout
    assert "C.pdf: temporary problem — try again later" in result.stdout
    assert "Ingest finished with 2 failed document(s)." in result.stdout
    assert result.exit_code == 1


def test_all_readable_run_ends_successfully(world: World) -> None:
    _fifteen(world)
    result = world.run("ingest")
    assert result.exit_code == 0
    assert result.stdout.rstrip().endswith("Ingest finished successfully.")


def test_previously_failed_pdf_becomes_new_once_replaced(world: World) -> None:
    world.put("Policy.pdf", b"JUNK")
    assert world.run("ingest").exit_code == 1
    world.put("Policy.pdf", pdf("Now a real policy."))
    result = world.run("ingest")
    counts = _summary(result.stdout)
    assert (counts["new"], counts["failed"]) == (1, 0)
    assert "not a readable PDF" not in result.stdout
    assert result.exit_code == 0
