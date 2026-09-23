from adapters.keyphrase_extraction import GENERIC_TERMS


def test_generic_product_terms_are_filtered():
    assert {"app", "service", "update"} <= GENERIC_TERMS
