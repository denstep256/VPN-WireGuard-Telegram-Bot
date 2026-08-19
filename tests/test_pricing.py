import unittest

from app.payments.pricing import (
    MAX_DISCOUNT_PERCENT,
    MIN_PAY_RUB,
    apply_discount,
    build_buy_payload,
    build_renew_payload,
    calc_bonus_to_use,
    calculate_invoice_price,
    get_base_price,
    parse_buy_payload,
    parse_renew_payload,
)


class PricingTests(unittest.TestCase):
    def test_discount_and_bonus_keep_minimum_payment(self):
        base_price = get_base_price("monthly_subs")
        discounted = apply_discount(base_price, 10)
        bonus = calc_bonus_to_use(discounted, 10_000)

        self.assertEqual(discounted - bonus, MIN_PAY_RUB)
        self.assertEqual(calculate_invoice_price("monthly_subs", 10, bonus), MIN_PAY_RUB)

    def test_discount_validation(self):
        with self.assertRaises(ValueError):
            apply_discount(100, -1)
        with self.assertRaises(ValueError):
            apply_discount(100, MAX_DISCOUNT_PERCENT + 1)

    def test_buy_payload_round_trip_and_strict_options(self):
        payload = build_buy_payload("monthly_subs", "Amsterdam", 1, 10, 20)
        self.assertEqual(
            parse_buy_payload(payload),
            ("monthly_subs", "Amsterdam", 1, 10, 20),
        )
        with self.assertRaises(ValueError):
            parse_buy_payload(payload + "|unexpected")
        with self.assertRaises(ValueError):
            build_buy_payload("unknown", "Amsterdam", 1, 0, 0)

    def test_renew_payload_round_trip(self):
        payload = build_renew_payload("annual_subs", 42, 0, 0)
        self.assertEqual(parse_renew_payload(payload), ("annual_subs", 42, 0, 0))
        with self.assertRaises(ValueError):
            parse_renew_payload("renew|unknown|42|d0|b0")


if __name__ == "__main__":
    unittest.main()
