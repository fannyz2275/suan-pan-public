def test_router_paths_registered():
    from app.findings.router import router

    paths = {r.path for r in router.routes}
    assert "/findings" in paths
    assert "/findings/count" in paths
    assert "/findings/{kind}/{finding_id}/decision" in paths
