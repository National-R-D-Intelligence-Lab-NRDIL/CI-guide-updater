import unittest

import differ


class DifferTests(unittest.TestCase):
    def test_extract_changes_both_empty(self) -> None:
        result = differ.extract_changes("", "")
        self.assertEqual(result, "No content in either version — nothing to compare.")

    def test_extract_changes_old_empty(self) -> None:
        new_text = "Freshly published content.\nIncludes eligibility details."
        result = differ.extract_changes("", new_text)
        self.assertIn("### Entirely New Content", result)
        self.assertIn(new_text, result)

    def test_extract_changes_new_empty(self) -> None:
        old_text = "Previously available content.\nNow archived."
        result = differ.extract_changes(old_text, "")
        self.assertIn("### Content Removed", result)
        self.assertIn(old_text, result)

    def test_extract_changes_no_meaningful_changes(self) -> None:
        old_text = "Line one\n\nLine two"
        new_text = "Line one\nLine two\n\n"
        result = differ.extract_changes(old_text, new_text)
        self.assertEqual(result, "No meaningful changes detected.")

    def test_extract_changes_normal_change_includes_added_and_removed_sections(self) -> None:
        old_text = "Deadline: March 1\nBudget: Up to $300,000\nAudience: Undergraduate institutions"
        new_text = (
            "Deadline: June 15\nBudget: Up to $300,000\n"
            "Audience: Undergraduate institutions\nNew: Data Management Plan required"
        )
        result = differ.extract_changes(old_text, new_text)

        self.assertIn("### Added/Modified Text", result)
        self.assertIn("### Removed Text", result)
        self.assertIn("  + Deadline: June 15", result)
        self.assertIn("  - Deadline: March 1", result)
        self.assertIn("  + New: Data Management Plan required", result)


if __name__ == "__main__":
    unittest.main()
