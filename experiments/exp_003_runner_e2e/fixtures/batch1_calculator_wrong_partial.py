"""Partial/incorrect SmartCouponCalculator — progressive discount only.

Deliberately ignores promo_categories and user-tier discounts: only the
raw subtotal and progressive discount are applied. Serves as the
known-wrong implementation for P1-B preflight scoring.
"""


class SmartCouponCalculator:
    """Calculate final price (partial implementation)."""

    def calculate(self, items, user_tier="regular", promo_categories=None):
        subtotal = 0.0
        for it in items:
            subtotal += it.get("price", 0) * it.get("quantity", 1)
        if subtotal >= 200:
            subtotal -= 25
        elif subtotal >= 100:
            subtotal -= 10
        return subtotal
