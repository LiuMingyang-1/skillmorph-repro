"""SmartCouponCalculator — reference implementation for P1-A preflight.

Implements progressive + category + tier discounts stacked in the order
the acceptance tests assume: category first, then progressive on the
discounted subtotal, then user-tier percentage on the result.
"""


class SmartCouponCalculator:
    """Calculate final price with stacked discount strategies."""

    TIER_DISCOUNT = {"regular": 0.0, "VIP": 0.05, "SVIP": 0.10}

    def calculate(self, items, user_tier="regular", promo_categories=None):
        promo_categories = promo_categories or []
        # 1) category discount: 10% off promo-category items
        subtotal = 0.0
        for it in items:
            price = it.get("price", 0) * it.get("quantity", 1)
            if it.get("category") in promo_categories:
                price *= 0.9
            subtotal += price
        # 2) progressive discount on the discounted subtotal
        if subtotal >= 200:
            subtotal -= 25
        elif subtotal >= 100:
            subtotal -= 10
        if subtotal < 0:
            subtotal = 0.0
        # 3) user-tier discount on the result
        tier = self.TIER_DISCOUNT.get(user_tier)
        if tier is None:
            raise ValueError(f"unknown user_tier: {user_tier}")
        return subtotal * (1 - tier)
