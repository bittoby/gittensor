# The MIT License (MIT)
# Copyright © 2025 Entrius

"""Tests for calculate_open_pr_collateral_score, covering the label_multiplier fix.

Regression: before the fix, label_multiplier was silently dropped from the open-PR
collateral formula, so two PRs with identical base/repo/issue multipliers produced
identical collateral even when one was labeled (e.g., `feature` = 1.5×).
"""

import pytest

from gittensor.classes import PRState
from gittensor.constants import LABEL_MULTIPLIERS, OPEN_PR_COLLATERAL_PERCENT
from gittensor.validator.oss_contributions.scoring import calculate_open_pr_collateral_score
from tests.validator.conftest import PRBuilder


@pytest.fixture
def builder():
    return PRBuilder()


def _open_pr_with_multipliers(
    builder: PRBuilder,
    *,
    base_score: float = 100.0,
    repo_weight: float = 1.0,
    issue: float = 1.0,
    label: float = 1.0,
):
    pr = builder.create(state=PRState.OPEN, uid=1)
    pr.base_score = base_score
    pr.repo_weight_multiplier = repo_weight
    pr.issue_multiplier = issue
    pr.label_multiplier = label
    return pr


class TestOpenPrCollateralLabelMultiplier:
    def test_feature_label_boosts_collateral(self, builder):
        """A `feature`-labeled PR should get more collateral than an unlabeled PR."""
        unlabeled = _open_pr_with_multipliers(builder, label=1.0)
        feature = _open_pr_with_multipliers(builder, label=LABEL_MULTIPLIERS['feature'])

        assert calculate_open_pr_collateral_score(feature) > calculate_open_pr_collateral_score(unlabeled)

    def test_label_multiplier_is_applied_to_collateral(self, builder):
        """Collateral = base × repo_weight × issue × label × OPEN_PR_COLLATERAL_PERCENT."""
        pr = _open_pr_with_multipliers(
            builder, base_score=100.0, repo_weight=1.0, issue=1.0, label=1.5
        )

        expected = 100.0 * 1.0 * 1.0 * 1.5 * OPEN_PR_COLLATERAL_PERCENT
        assert calculate_open_pr_collateral_score(pr) == pytest.approx(expected)

    def test_all_label_tiers_differentiate_collateral(self, builder):
        """Each defined label tier should yield a distinct collateral proportional to its multiplier."""
        scores = {}
        for label_name, mult in LABEL_MULTIPLIERS.items():
            pr = _open_pr_with_multipliers(builder, label=mult)
            scores[label_name] = calculate_open_pr_collateral_score(pr)

        # Ordering: feature(1.5) > bug(1.25) > enhancement(1.1) > refactor(1.0)
        assert scores['feature'] > scores['bug']
        assert scores['bug'] > scores['enhancement']
        assert scores['enhancement'] >= scores['refactor']

    def test_default_label_multiplier_is_neutral(self, builder):
        """label_multiplier=1.0 (unlabeled) should not change collateral vs. pre-fix baseline."""
        pr = _open_pr_with_multipliers(
            builder, base_score=100.0, repo_weight=0.5, issue=1.33, label=1.0
        )
        expected = 100.0 * 0.5 * 1.33 * OPEN_PR_COLLATERAL_PERCENT
        assert calculate_open_pr_collateral_score(pr) == pytest.approx(expected)

    def test_combined_with_repo_and_issue_multipliers(self, builder):
        """All three applicable multipliers compound together."""
        pr = _open_pr_with_multipliers(
            builder, base_score=50.0, repo_weight=0.8, issue=1.33, label=1.5
        )
        expected = 50.0 * 0.8 * 1.33 * 1.5 * OPEN_PR_COLLATERAL_PERCENT
        assert calculate_open_pr_collateral_score(pr) == pytest.approx(expected)

    def test_two_prs_identical_except_label_differ(self, builder):
        """Issue scenario: two PRs matched on everything but label must produce different collateral."""
        pr_unlabeled = _open_pr_with_multipliers(
            builder, base_score=100.0, repo_weight=1.0, issue=1.33, label=1.0
        )
        pr_feature = _open_pr_with_multipliers(
            builder, base_score=100.0, repo_weight=1.0, issue=1.33, label=LABEL_MULTIPLIERS['feature']
        )

        collat_unlabeled = calculate_open_pr_collateral_score(pr_unlabeled)
        collat_feature = calculate_open_pr_collateral_score(pr_feature)

        assert collat_feature == pytest.approx(collat_unlabeled * LABEL_MULTIPLIERS['feature'])
