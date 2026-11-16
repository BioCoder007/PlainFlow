from cve_engine.cache import ExplanationCache


def test_put_then_get_roundtrips(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    cache.put("k", {"s1": "A"}, now=100.0)
    assert cache.get("k") == {"s1": "A"}
    assert cache.get("missing") is None


def test_cache_persists_across_instances(tmp_path):
    ExplanationCache(tmp_path / "c.sqlite").put("k", {"s1": "A"}, now=1.0)
    assert ExplanationCache(tmp_path / "c.sqlite").get("k") == {"s1": "A"}


def test_cache_sweep_removes_only_old_rows(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    cache.put("k1", {"s1": "A"}, now=100.0)
    cache.put("k2", {"s1": "B"}, now=200.0)
    assert cache.sweep(150.0) == 1
    assert cache.get("k1") is None
    assert cache.get("k2") == {"s1": "B"}
