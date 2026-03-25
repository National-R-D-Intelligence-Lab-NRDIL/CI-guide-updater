"""Diff Engine module.

Compares two text snapshots and extracts meaningful additions, deletions, and
modifications in a format optimized for downstream LLM consumption.
"""

import difflib


def extract_changes(old_text: str, new_text: str) -> str:
    """Compare two text blocks and return a structured summary of changes.

    The output groups changes under ``### Added/Modified Text`` and
    ``### Removed Text`` headers so an LLM can quickly parse the delta.

    Completely empty lines are stripped before diffing to reduce noise.

    Args:
        old_text: The previous version of the content (may be empty for a
            brand-new page).
        new_text: The current version of the content (may be empty if the
            page was taken down).

    Returns:
        A human- and LLM-readable string summarising only the changed lines.
        Returns a short notice when the inputs are identical or when one side
        is empty (indicating entirely new or entirely removed content).
    """
    if not old_text and not new_text:
        return "No content in either version — nothing to compare."

    if not old_text:
        return (
            "### Entirely New Content\n\n"
            "The previous snapshot was empty. Full text of the new version:\n\n"
            + new_text
        )

    if not new_text:
        return (
            "### Content Removed\n\n"
            "The new snapshot is empty. Full text of the removed version:\n\n"
            + old_text
        )

    old_lines = [ln for ln in old_text.splitlines() if ln.strip()]
    new_lines = [ln for ln in new_text.splitlines() if ln.strip()]

    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")

    added: list[str] = []
    removed: list[str] = []

    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])

    if not added and not removed:
        return "No meaningful changes detected."

    sections: list[str] = []

    if added:
        sections.append(
            "### Added/Modified Text\n\n" + "\n".join(f"  + {ln}" for ln in added)
        )

    if removed:
        sections.append(
            "### Removed Text\n\n" + "\n".join(f"  - {ln}" for ln in removed)
        )

    return "\n\n".join(sections)


if __name__ == "__main__":
    old = (
        "NIH R15 Research Enhancement Award\n"
        "\n"
        "Application Deadline: March 1, 2025\n"
        "Award Budget: Up to $300,000 in direct costs over the entire project period.\n"
        "Eligible Institutions: Undergraduate-focused institutions that have not\n"
        "received more than $6 million per year in NIH support.\n"
        "\n"
        "The R15 mechanism supports small-scale research projects at eligible\n"
        "institutions to strengthen their research environment and expose students\n"
        "to research.\n"
    )

    new = (
        "NIH R15 Research Enhancement Award\n"
        "\n"
        "Application Deadline: June 15, 2025\n"
        "Award Budget: Up to $300,000 in direct costs over the entire project period.\n"
        "Eligible Institutions: Undergraduate-focused institutions that have not\n"
        "received more than $6 million per year in NIH support.\n"
        "New: Applicants must now include a Data Management and Sharing Plan.\n"
        "\n"
        "The R15 mechanism supports small-scale research projects at eligible\n"
        "institutions to strengthen their research environment and expose students\n"
        "to meritorious research.\n"
    )

    print("=" * 60)
    print("DIFF ENGINE — Demo Output")
    print("=" * 60)
    print()
    print(extract_changes(old, new))
    print()

    print("-" * 60)
    print("Edge case: old text is empty (new page)")
    print("-" * 60)
    print()
    print(extract_changes("", "Brand-new page content here."))
    print()

    print("-" * 60)
    print("Edge case: new text is empty (page removed)")
    print("-" * 60)
    print()
    print(extract_changes("Some old content.", ""))
    print()

    print("-" * 60)
    print("Edge case: both texts identical")
    print("-" * 60)
    print()
    print(extract_changes(old, old))
