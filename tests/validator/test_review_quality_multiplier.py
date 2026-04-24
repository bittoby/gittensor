#!/usr/bin/env python3
# The MIT License (MIT)
# Copyright © 2025 Entrius

"""
Tests for PR review quality multiplier (issue #303).

Covers:
- calculate_review_quality_multiplier standalone function
- review_quality_multiplier field on PullRequest and its effect on earned_score
"""

from math import ceil

import pytest

from gittensor.classes import MinerEvaluation, PRState, PullRequest
from gittensor.constants import OPEN_PR_COLLATERAL_PERCENT, REVIEW_PENALTY_RATE
from gittensor.utils.github_api_tools import _MAX_CHANGES_REQUESTED_REVIEWS
from gittensor.validator.oss_contributions.scoring import (
    calculate_open_pr_collateral_score,
    calculate_pr_multipliers,
    calculate_review_quality_multiplier,
)
from gittensor.validator.utils.load_weights import RepositoryConfig
from tests.validator.conftest import PRBuilder

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def builder():
    return PRBuilder()


# ============================================================================
# TestCalculateReviewQualityMultiplier
# ============================================================================


class TestCalculateReviewQualityMultiplier:
    """Tests for the standalone calculate_review_quality_multiplier function."""

    def test_no_reviews_returns_one(self):
        assert calculate_review_quality_multiplier(0) == 1.0

    def test_one_review_applies_single_penalty(self):
        result = calculate_review_quality_multiplier(1)
        assert result == pytest.approx(1.0 - REVIEW_PENALTY_RATE)

    def test_two_reviews_cumulative(self):
        result = calculate_review_quality_multiplier(2)
        assert result == pytest.approx(1.0 - 2 * REVIEW_PENALTY_RATE)

    def test_table_values(self):
        """Verify expected values across the penalty range."""
        expected = {
            0: 1.00,
            1: 0.85,
            2: 0.70,
            3: 0.55,
            4: 0.40,
            5: 0.25,
            6: 0.10,
        }
        for n, mult in expected.items():
            assert calculate_review_quality_multiplier(n) == pytest.approx(mult, abs=1e-9), f'n={n}'

    def test_floor_at_zero(self):
        """Multiplier must not go below 0.0 for extreme counts."""
        assert calculate_review_quality_multiplier(7) == 0.0

    def test_large_count_stays_at_zero(self):
        assert calculate_review_quality_multiplier(100) == 0.0

    def test_returns_float(self):
        assert isinstance(calculate_review_quality_multiplier(0), float)


# ============================================================================
# TestReviewQualityMultiplierOnPullRequest
# ============================================================================


class TestReviewQualityMultiplierOnPullRequest:
    """Tests for review_quality_multiplier field on PullRequest and its effect on earned_score."""

    def test_default_multiplier_is_one(self, builder):
        pr = builder.create(state=PRState.MERGED)
        assert pr.review_quality_multiplier == 1.0

    def test_default_changes_requested_count_is_zero(self, builder):
        pr = builder.create(state=PRState.MERGED)
        assert pr.changes_requested_count == 0

    def test_review_multiplier_reduces_earned_score(self, builder):
        pr = builder.create(state=PRState.MERGED)
        pr.base_score = 100.0
        pr.repo_weight_multiplier = 1.0
        pr.issue_multiplier = 1.0
        pr.open_pr_spam_multiplier = 1.0
        pr.time_decay_multiplier = 1.0
        pr.credibility_multiplier = 1.0

        pr.review_quality_multiplier = 1.0
        score_no_penalty = pr.calculate_final_earned_score()

        pr.review_quality_multiplier = calculate_review_quality_multiplier(1)
        score_one_review = pr.calculate_final_earned_score()

        assert score_one_review == pytest.approx(score_no_penalty * 0.85)

    def test_zero_multiplier_zeroes_earned_score(self, builder):
        pr = builder.create(state=PRState.MERGED)
        pr.base_score = 50.0
        pr.repo_weight_multiplier = 1.0
        pr.issue_multiplier = 1.0
        pr.open_pr_spam_multiplier = 1.0
        pr.time_decay_multiplier = 1.0
        pr.credibility_multiplier = 1.0
        pr.review_quality_multiplier = 0.0

        assert pr.calculate_final_earned_score() == 0.0

    def test_multiplier_participates_in_product(self, builder):
        """review_quality_multiplier participates in the product of all multipliers."""
        pr = builder.create(state=PRState.MERGED)
        pr.base_score = 80.0
        pr.repo_weight_multiplier = 1.0
        pr.issue_multiplier = 1.0
        pr.open_pr_spam_multiplier = 1.0
        pr.time_decay_multiplier = 1.0
        pr.credibility_multiplier = 1.0
        pr.review_quality_multiplier = calculate_review_quality_multiplier(3)  # 0.55

        earned = pr.calculate_final_earned_score()
        assert earned == pytest.approx(80.0 * 0.55)


# ============================================================================
# TestChangesRequestedCountFromGraphQL
# ============================================================================


def _make_graphql_pr(state: str, changes_requested_reviews: list, merged_at: str = '2025-06-01T00:00:00Z') -> dict:
    """Build minimal GraphQL PR response data for from_graphql_response"""
    return {
        'number': 1,
        'title': 'Test PR',
        'state': state,
        'additions': 10,
        'deletions': 5,
        'createdAt': '2025-06-01T00:00:00Z',
        'mergedAt': merged_at if state == 'MERGED' else None,
        'author': {'login': 'testuser'},
        'repository': {'name': 'repo', 'owner': {'login': 'owner'}},
        'changesRequestedReviews': {'nodes': changes_requested_reviews},
    }


class TestChangesRequestedCountFromGraphQL:
    """Tests that from_graphql_response correctly parses changesRequestedReviews into changes_requested_count"""

    def test_merged_pr_counts_only_maintainer_reviews(self):
        pr_data = _make_graphql_pr(
            'MERGED',
            [
                {'authorAssociation': 'OWNER'},
                {'authorAssociation': 'CONTRIBUTOR'},
                {'authorAssociation': 'COLLABORATOR'},
                {'authorAssociation': 'NONE'},
            ],
        )
        pr = PullRequest.from_graphql_response(pr_data, uid=1, hotkey='hk', github_id='123')
        assert pr.changes_requested_count == 2

    def test_non_merged_pr_counts_maintainer_reviews(self):
        pr_data = _make_graphql_pr(
            'OPEN',
            [
                {'authorAssociation': 'OWNER'},
                {'authorAssociation': 'CONTRIBUTOR'},
                {'authorAssociation': 'MEMBER'},
            ],
        )
        pr = PullRequest.from_graphql_response(pr_data, uid=1, hotkey='hk', github_id='123')
        assert pr.changes_requested_count == 2


def test_max_changes_requested_reviews_matches_penalty_rate():
    # Tripwire: the GraphQL fetch cap must stay aligned with REVIEW_PENALTY_RATE so that any
    # review beyond the cap is already forced to a 0.0 multiplier by calculate_review_quality_multiplier
    assert _MAX_CHANGES_REQUESTED_REVIEWS == ceil(1 / REVIEW_PENALTY_RATE)
    assert calculate_review_quality_multiplier(_MAX_CHANGES_REQUESTED_REVIEWS) == 0.0


# ============================================================================
# TestReviewQualityMultiplierOnOpenPR
# ============================================================================


def _make_repo_config() -> dict:
    return {'test/repo': RepositoryConfig(weight=1.0)}


def _make_eval() -> MinerEvaluation:
    return MinerEvaluation(uid=0, hotkey='hk', github_id='1')


class TestCalculatePrMultipliersForOpenPR:
    """calculate_pr_multipliers must apply review_quality to OPEN PRs, not just MERGED."""

    def test_open_pr_with_no_cr_reviews_keeps_multiplier_at_one(self, builder):
        pr = builder.create(state=PRState.OPEN, repo='test/repo')
        pr.changes_requested_count = 0

        calculate_pr_multipliers(pr, _make_eval(), _make_repo_config())

        assert pr.review_quality_multiplier == 1.0

    def test_open_pr_with_maintainer_cr_reviews_reduces_multiplier(self, builder):
        pr = builder.create(state=PRState.OPEN, repo='test/repo')
        pr.changes_requested_count = 3

        calculate_pr_multipliers(pr, _make_eval(), _make_repo_config())

        assert pr.review_quality_multiplier == pytest.approx(0.55)

    def test_open_pr_review_multiplier_can_reach_zero(self, builder):
        pr = builder.create(state=PRState.OPEN, repo='test/repo')
        pr.changes_requested_count = _MAX_CHANGES_REQUESTED_REVIEWS

        calculate_pr_multipliers(pr, _make_eval(), _make_repo_config())

        assert pr.review_quality_multiplier == 0.0

    def test_merged_and_open_agree_for_same_cr_count(self, builder):
        merged = builder.create(state=PRState.MERGED, repo='test/repo')
        merged.changes_requested_count = 2
        open_pr = builder.create(state=PRState.OPEN, repo='test/repo')
        open_pr.changes_requested_count = 2

        calculate_pr_multipliers(merged, _make_eval(), _make_repo_config())
        calculate_pr_multipliers(open_pr, _make_eval(), _make_repo_config())

        assert merged.review_quality_multiplier == open_pr.review_quality_multiplier


class TestOpenPrCollateralAppliesReviewQuality:
    """calculate_open_pr_collateral_score must fold review_quality into the product."""

    def _prepare(self, builder: PRBuilder, cr_count: int) -> PullRequest:
        pr = builder.create(state=PRState.OPEN, repo='test/repo')
        pr.base_score = 100.0
        pr.repo_weight_multiplier = 1.0
        pr.issue_multiplier = 1.0
        pr.label_multiplier = 1.0
        pr.changes_requested_count = cr_count
        calculate_pr_multipliers(pr, _make_eval(), _make_repo_config())
        return pr

    def test_clean_open_pr_collateral_unchanged(self, builder):
        pr = self._prepare(builder, cr_count=0)

        collateral = calculate_open_pr_collateral_score(pr)

        assert collateral == pytest.approx(100.0 * OPEN_PR_COLLATERAL_PERCENT)

    def test_open_pr_collateral_scales_with_review_quality(self, builder):
        clean = self._prepare(builder, cr_count=0)
        penalized = self._prepare(builder, cr_count=3)

        clean_collateral = calculate_open_pr_collateral_score(clean)
        penalized_collateral = calculate_open_pr_collateral_score(penalized)

        assert penalized_collateral == pytest.approx(clean_collateral * 0.55)

    def test_open_pr_collateral_zeroes_when_review_quality_zero(self, builder):
        pr = self._prepare(builder, cr_count=_MAX_CHANGES_REQUESTED_REVIEWS)

        assert calculate_open_pr_collateral_score(pr) == 0.0

    def test_open_pr_collateral_matches_projected_merged_earned_score(self, builder):
        """Regression guard: open-PR collateral should not overstate the merged projection."""
        cr_count = 3

        open_pr = builder.create(state=PRState.OPEN, repo='test/repo')
        open_pr.base_score = 80.0
        open_pr.repo_weight_multiplier = 1.0
        open_pr.issue_multiplier = 1.33
        open_pr.label_multiplier = 1.25
        open_pr.changes_requested_count = cr_count
        calculate_pr_multipliers(open_pr, _make_eval(), _make_repo_config())

        merged_projection = (
            open_pr.base_score
            * open_pr.repo_weight_multiplier
            * open_pr.issue_multiplier
            * open_pr.label_multiplier
            * open_pr.review_quality_multiplier
        )
        expected_collateral = merged_projection * OPEN_PR_COLLATERAL_PERCENT

        assert calculate_open_pr_collateral_score(open_pr) == pytest.approx(expected_collateral)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
