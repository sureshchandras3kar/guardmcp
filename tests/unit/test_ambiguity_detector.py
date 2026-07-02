from guardmcp.core.planning.ambiguity import AmbiguityDetector


def test_two_active_candidates_is_ambiguous():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool"}
    r = d.detect("show active users", schema, indexed_fields=set())
    assert r.ambiguous is True
    assert len(r.interpretations) >= 2
    assert "clarif" in r.recommendation.lower()
    assert r.confidence == r.interpretations[0].confidence


def test_single_candidate_not_ambiguous():
    d = AmbiguityDetector()
    schema = {"status": "string"}
    r = d.detect("show active users", schema, indexed_fields=set())
    assert r.ambiguous is False
    assert len(r.interpretations) == 1
    assert r.interpretations[0].field == "status"
    assert r.confidence == 1.0


def test_no_candidate_not_ambiguous():
    d = AmbiguityDetector()
    r = d.detect("list projects", {"name": "string"}, indexed_fields=set())
    assert r.ambiguous is False
    assert r.interpretations == []


def test_indexed_candidate_ranks_first():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool"}
    r = d.detect("active", schema, indexed_fields={"is_active"})
    assert r.interpretations[0].field == "is_active"
    assert r.interpretations[0].confidence == 0.6


def test_deterministic_output():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool", "enabled": "bool"}
    a = d.detect("active", schema, set())
    b = d.detect("active", schema, set())
    assert a.model_dump() == b.model_dump()
