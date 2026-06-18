import unittest

from utils.si_recommendation_queue import is_cross_stack_source


class TestCrossStackQueue(unittest.TestCase):
    def test_capability_review_is_cross_stack(self):
        self.assertTrue(is_cross_stack_source("capability_review"))

    def test_integrity_scan_not_cross_stack(self):
        self.assertFalse(is_cross_stack_source("integrity_scan"))


if __name__ == "__main__":
    unittest.main()
