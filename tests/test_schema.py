import pytest

from joh.schema import SchemaError, validate_question, validate_request


def q_choice(n):
    return {"type": "choice", "instructions": "x?", "criteria": {f"o{i}": None for i in range(n)}}


def test_choice_limits():
    validate_question("q", q_choice(2))
    validate_question("q", q_choice(255))
    with pytest.raises(SchemaError):
        validate_question("q", q_choice(256))
    with pytest.raises(SchemaError):
        validate_question("q", q_choice(1))


def test_score_limits_and_distinct_levels():
    validate_question("q", {"type": "score", "instructions": "x?", "criteria": [str(i) for i in range(10)]})
    with pytest.raises(SchemaError):
        validate_question("q", {"type": "score", "instructions": "x?", "criteria": [str(i) for i in range(11)]})
    with pytest.raises(SchemaError):
        validate_question("q", {"type": "score", "instructions": "x?", "criteria": ["a", "a"]})


def test_noul_criteria_keys():
    validate_question("q", {"type": "noul", "instructions": "x?"})
    validate_question("q", {"type": "noul", "instructions": "x?", "criteria": {"true": "t"}})
    with pytest.raises(SchemaError):
        validate_question("q", {"type": "noul", "instructions": "x?", "criteria": {"yes": "t"}})


def test_local_fields_are_never_sent():
    with pytest.raises(SchemaError, match="本地字段"):
        validate_question("q", {"type": "noul", "instructions": "x?", "polarity": "honest_low"})


def test_instructions_required():
    with pytest.raises(SchemaError):
        validate_question("q", {"type": "noul", "instructions": ""})


def test_request_requires_state_and_questions():
    with pytest.raises(SchemaError):
        validate_request({"state": "", "questions": {"a": {"type": "noul", "instructions": "x"}}})
    with pytest.raises(SchemaError):
        validate_request({"state": "s", "questions": {}})
