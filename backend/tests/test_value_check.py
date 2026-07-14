"""value_check 单元测试（纯计算函数，无需 mock，使用标准库 unittest）"""
import math
import unittest

from app.utils.value_check import (
    parse_numeric, convert_unit, is_within_tolerance, compare_numeric,
)


class TestParseNumeric(unittest.TestCase):
    def test_string_with_unit(self):
        self.assertEqual(parse_numeric("100 dBm"), (100.0, "dBm"))

    def test_string_with_prefix_symbol(self):
        self.assertEqual(parse_numeric("≥50 kg"), (50.0, "kg"))

    def test_string_no_space(self):
        self.assertEqual(parse_numeric("1.5GHz"), (1.5, "GHz"))

    def test_scientific_notation(self):
        self.assertEqual(parse_numeric("1.2e3 V"), (1200.0, "V"))

    def test_int_input(self):
        self.assertEqual(parse_numeric(100), (100.0, ""))

    def test_float_input(self):
        self.assertEqual(parse_numeric(3.14), (3.14, ""))

    def test_none(self):
        self.assertIsNone(parse_numeric(None))

    def test_empty(self):
        self.assertIsNone(parse_numeric(""))

    def test_no_number(self):
        self.assertIsNone(parse_numeric("abc"))


class TestConvertUnit(unittest.TestCase):
    def test_same_unit(self):
        self.assertEqual(convert_unit(100.0, "kg", "kg"), 100.0)

    def test_si_prefix_ghz_to_mhz(self):
        self.assertEqual(convert_unit(1.0, "GHz", "MHz"), 1000.0)

    def test_si_prefix_mhz_to_ghz(self):
        self.assertEqual(convert_unit(1000.0, "MHz", "GHz"), 1.0)

    def test_dbm_to_w(self):
        self.assertAlmostEqual(convert_unit(30.0, "dBm", "W"), 1.0, places=6)

    def test_w_to_dbm(self):
        self.assertAlmostEqual(convert_unit(1.0, "W", "dBm"), 30.0, places=6)

    def test_incompatible_units(self):
        self.assertIsNone(convert_unit(100.0, "kg", "V"))

    def test_empty_units(self):
        self.assertEqual(convert_unit(100.0, "", ""), 100.0)


class TestIsWithinTolerance(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(is_within_tolerance(100.0, 100.0, None))

    def test_within_tolerance(self):
        self.assertTrue(is_within_tolerance(100.0, 102.0, 5))

    def test_outside_tolerance(self):
        self.assertFalse(is_within_tolerance(100.0, 110.0, 5))

    def test_zero_base(self):
        self.assertTrue(is_within_tolerance(0.0, 0.01, 5))

    def test_isclose_float(self):
        self.assertTrue(is_within_tolerance(0.1 + 0.2, 0.3, None))


class TestCompareNumeric(unittest.TestCase):
    def test_match_same_unit(self):
        self.assertEqual(compare_numeric("100 kg", "100 kg"), "match")

    def test_match_with_tolerance(self):
        self.assertEqual(compare_numeric("100 kg", "102 kg", 5), "match")

    def test_deviation(self):
        self.assertEqual(compare_numeric("100 kg", "120 kg", 5), "deviation")

    def test_match_after_unit_conversion(self):
        self.assertEqual(compare_numeric("1 GHz", "1000 MHz"), "match")

    def test_need_confirm_non_numeric(self):
        self.assertEqual(compare_numeric("abc", "100 kg"), "need_confirm")

    def test_need_confirm_incompatible_units(self):
        self.assertEqual(compare_numeric("100 kg", "100 V"), "need_confirm")

    def test_none_input(self):
        self.assertEqual(compare_numeric(None, "100 kg"), "need_confirm")

    def test_dbm_to_w_match(self):
        self.assertEqual(compare_numeric("30 dBm", "1 W"), "match")


if __name__ == "__main__":
    unittest.main()
