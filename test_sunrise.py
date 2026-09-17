import unittest
from monitor_sunrise import classify


class AvailabilityTests(unittest.TestCase):
    def test_sold_out(self):
        self.assertEqual(classify([['普通車指定席 禁煙席', 'B寝台 禁煙個室'], ['残席なし', '残席なし']]), {})

    def test_only_correct_category_is_available(self):
        self.assertEqual(classify([['普通車指定席 禁煙席', 'B寝台 禁煙個室'], ['残席なし', '空席残りわずか 2']]), {'B寝台 禁煙個室': '空席残りわずか 2'})

    def test_unknown_is_error_not_sold_out(self):
        with self.assertRaises(RuntimeError):
            classify([['A寝台 禁煙個室'], ['照会できません']])

    def test_changed_layout_is_error(self):
        with self.assertRaises(RuntimeError):
            classify([['A寝台 禁煙個室'], []])


if __name__ == '__main__':
    unittest.main()
