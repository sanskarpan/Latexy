"""Operator-configured Weekly and Lifetime Dodo catalog contract."""

from app.core.config import get_dodo_product_id, get_plan_config, is_b57_sku_configured, settings


def test_weekly_and_lifetime_skus_require_a_dodo_product_and_price(monkeypatch):
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_WEEKLY", "")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_LIFETIME", "")
    monkeypatch.setattr(settings, "WEEKLY_AMOUNT_MINOR", 0)
    monkeypatch.setattr(settings, "LIFETIME_AMOUNT_MINOR", 0)

    assert not is_b57_sku_configured("weekly")
    assert not is_b57_sku_configured("lifetime")

    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_WEEKLY", "p_test_weekly")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_LIFETIME", "p_test_lifetime")
    monkeypatch.setattr(settings, "WEEKLY_AMOUNT_MINOR", 1300)
    monkeypatch.setattr(settings, "LIFETIME_AMOUNT_MINOR", 14900)

    assert is_b57_sku_configured("weekly")
    assert is_b57_sku_configured("lifetime")
    assert get_dodo_product_id("weekly") == "p_test_weekly"
    assert get_plan_config("lifetime")["price"] == 14900


def test_live_mode_never_falls_back_to_test_product(monkeypatch):
    monkeypatch.setattr(settings, "DODO_MODE", "live")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    monkeypatch.setattr(settings, "DODO_LIVE_PRODUCT_PRO_MONTHLY", "")

    assert get_dodo_product_id("pro") == ""
