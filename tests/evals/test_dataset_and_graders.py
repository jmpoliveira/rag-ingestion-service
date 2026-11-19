from __future__ import annotations

from pathlib import Path

import pytest

from evals.dataset import DatasetError, Expect, load_dataset
from evals.graders import grade, score
from tests.evals.helpers import case, dataset, hit

ROOT = Path(__file__).resolve().parents[2]


def test_the_committed_dataset_is_valid_and_points_at_the_sample_corpus():
    # Act
    data = load_dataset(ROOT / "evals" / "datasets" / "knowledge_base.toml")

    # Assert
    corpus = ROOT / "samples" / "knowledge-base"
    assert all((corpus / source).is_file() for source in data.sources)
    for item in data.cases:  # every evidence text really is in a relevant document
        texts = " ".join(
            " ".join((corpus / s).read_text(encoding="utf-8").split()) for s in item.expect.sources
        )
        assert any(" ".join(e.split()) in texts for e in item.expect.evidence_any), item.id


def test_fingerprint_ignores_the_description_but_not_the_cases():
    # Arrange
    base = dataset(case("a", "q?", ["x.md"]))

    # Act / Assert
    assert base.fingerprint == base.model_copy(update={"description": "new"}).fingerprint
    assert base.fingerprint != dataset(case("a", "other?", ["x.md"])).fingerprint
    assert base.fingerprint != dataset(case("a", "q?", ["x.md"]), k=3).fingerprint


def test_select_by_id_or_tag():
    # Arrange
    data = dataset(
        case("a", "q", ["x"], tags=["sla"]), case("b", "q", ["x"]), case("c", "q", ["x"])
    )

    # Act / Assert
    assert [c.id for c in data.select(set(), set())] == ["a", "b", "c"]
    assert [c.id for c in data.select({"b"}, {"sla"})] == ["a", "b"]


@pytest.mark.parametrize(
    "content",
    [
        "not toml [",
        'name = "kb"\nversion = 1\n',  # no cases
        'name = "kb"\nversion = 1\nsurprise = true\n[[cases]]\nid="a"\nquestion="q"\n'
        '[cases.expect]\nsources=["x"]\n',  # unknown field
        'name = "kb"\nversion = 1\n[[cases]]\nid="a"\nquestion="q"\n[cases.expect]\nsources=[]\n',
        'name = "kb"\nversion = 1\n'
        + '[[cases]]\nid="a"\nquestion="q"\n[cases.expect]\nsources=["x"]\n' * 2,  # duplicate
    ],
)
def test_invalid_datasets_are_rejected(tmp_path: Path, content: str):
    # Arrange
    path = tmp_path / "d.toml"
    path.write_text(content, encoding="utf-8")

    # Act / Assert
    with pytest.raises(DatasetError):
        load_dataset(path)


def test_missing_dataset_file(tmp_path: Path):
    with pytest.raises(DatasetError, match="cannot read"):
        load_dataset(tmp_path / "nope.toml")


def test_scores_rank_and_recall():
    # Arrange
    hits = [hit("other.md"), hit("b.md"), hit("a.md")]

    # Act
    result = score(hits, Expect(sources=("a.md", "b.md", "c.md")))

    # Assert
    assert result.hit
    assert result.first_relevant_rank == 2
    assert result.reciprocal_rank == pytest.approx(0.5)
    assert result.recall == pytest.approx(2 / 3)


def test_nothing_relevant_scores_zero():
    result = score([hit("other.md")], Expect(sources=("a.md",)))
    assert (result.hit, result.reciprocal_rank, result.recall) == (False, 0.0, 0.0)
    assert score([], Expect(sources=("a.md",))).first_relevant_rank is None


def test_evidence_must_be_in_a_relevant_chunk_ignoring_case_and_spacing():
    # Arrange
    expect = Expect(sources=("a.md",), evidence_any=("within 30  days",))
    wrong_doc = [hit("b.md", "Within 30 days"), hit("a.md", "unrelated")]
    right = [hit("a.md", "refund WITHIN 30\ndays of purchase")]

    # Act
    _, failing = grade(wrong_doc, expect, k=2)
    _, passing = grade(right, expect, k=2)

    # Assert
    assert [c.name for c in failing] == ["hit@2", "recall@2", "evidence"]
    assert not failing[2].passed
    assert passing[2].passed


def test_checks_explain_a_miss():
    # Act
    _, checks = grade([hit("b.md", page=3)], Expect(sources=("a.md",)), k=5)

    # Assert
    assert not checks[0].passed
    assert "b.md#p3" in checks[0].detail
