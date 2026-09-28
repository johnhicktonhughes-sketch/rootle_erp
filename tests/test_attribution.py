import unittest

from attribution import ATTRIBUTION_FIELDS, clean_attribution


class CleanAttributionTests(unittest.TestCase):
    def test_non_dict_input_is_ignored(self):
        for raw in (None, "gclid=abc", ["gclid"], 5):
            self.assertIsNone(clean_attribution(raw))

    def test_keeps_only_known_non_empty_string_values(self):
        cleaned = clean_attribution(
            {
                "gclid": " abc123 ",
                "fbclid": "",
                "gbraid": None,
                "wbraid": 42,
                "utm_source": "google",
                "not_a_field": "x",
            }
        )
        self.assertEqual(cleaned, {"gclid": "abc123", "utm_source": "google"})

    def test_returns_none_when_nothing_usable(self):
        self.assertIsNone(clean_attribution({"gclid": "  ", "other": "x"}))

    def test_truncates_long_values(self):
        cleaned = clean_attribution({"referrer": "x" * 2000})
        self.assertEqual(len(cleaned["referrer"]), 512)

    def test_all_declared_fields_are_accepted(self):
        raw = {field: "v" for field in ATTRIBUTION_FIELDS}
        self.assertEqual(clean_attribution(raw), raw)


if __name__ == "__main__":
    unittest.main()
