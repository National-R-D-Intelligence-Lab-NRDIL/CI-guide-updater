import unittest
from unittest.mock import patch

import generator


class GeneratorInputBudgetTests(unittest.TestCase):
    def test_source_input_budget_keeps_a_minimum_per_source(self) -> None:
        self.assertGreaterEqual(generator._source_input_budget(20), generator.MIN_SOURCE_INPUT_CHARS)

    @patch("generator.MAX_INPUT_CHARS", 60_000)
    def test_source_input_budget_divides_available_context(self) -> None:
        self.assertEqual(generator._source_input_budget(3), 20_000)


if __name__ == "__main__":
    unittest.main()
