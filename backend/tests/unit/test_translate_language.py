from controllers.translate_controller import _normalize_target_language


def test_normalize_target_language_maps_known_codes():
    assert _normalize_target_language("en") == "English"
    assert _normalize_target_language("zh") == "中文"


def test_normalize_target_language_rejects_custom_without_value():
    assert _normalize_target_language("custom") is None


def test_normalize_target_language_keeps_readable_language():
    assert _normalize_target_language("English") == "English"
