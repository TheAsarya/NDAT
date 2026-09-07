from ndat.positions import normalize_position


def test_position_normalization_is_conservative_and_uses_ngs_edge_evidence() -> None:
    assert normalize_position("LB", depth_chart_position="OLB") == "LB"
    assert normalize_position("LB", depth_chart_position="OLB", ngs_position="EDGE") == "EDGE"
    assert normalize_position("FB") == "RB"
    assert normalize_position("SAF") == "S"
    assert normalize_position(None) is None
