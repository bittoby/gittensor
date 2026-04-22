# The MIT License (MIT)
# Copyright © 2025 Entrius

"""
Tests for is_valid_issue (issue #605).

Verifies that is_valid_issue mirrors the anti-gaming state_reason gate already
applied in issue_discovery/scoring.py: only state_reason == 'COMPLETED' grants
the 1.33x / 1.66x issue multiplier. Anything else (NOT_PLANNED, TRANSFERRED,
DUPLICATE, None) is rejected.
"""

from datetime import datetime, timedelta, timezone

import pytest

from gittensor.constants import MAX_ISSUE_CLOSE_WINDOW_DAYS
from gittensor.validator.oss_contributions.scoring import is_valid_issue


class TestIsValidIssueStateReasonGate:
    """Lock down the state_reason gate symmetry with issue_discovery/scoring.py."""

    @pytest.mark.parametrize(
        'state_reason,expected',
        [
            ('COMPLETED', True),
            ('NOT_PLANNED', False),
            ('TRANSFERRED', False),
            ('DUPLICATE', False),
            (None, False),
        ],
    )
    def test_only_completed_state_reason_is_valid(self, pr_factory, issue_factory, state_reason, expected):
        now = datetime.now(timezone.utc)
        pr = pr_factory.merged(merged_at=now)
        pr.author_login = 'miner_user'
        pr.created_at = now - timedelta(days=1)
        pr.last_edited_at = None

        issue = issue_factory.create(
            author_login='other_user',
            created_at=now - timedelta(days=5),
            closed_at=now,
            state='CLOSED',
            state_reason=state_reason,
        )

        assert is_valid_issue(issue, pr) is expected


class TestIsValidIssueOpenPRStateReason:
    """Open PRs must also reject closed non-COMPLETED issues (blocks collateral inflation)."""

    @pytest.mark.parametrize(
        'state_reason,expected',
        [
            ('COMPLETED', True),
            ('NOT_PLANNED', False),
            ('DUPLICATE', False),
            ('TRANSFERRED', False),
        ],
    )
    def test_open_pr_rejects_closed_non_completed_issue(
        self, pr_factory, issue_factory, state_reason, expected
    ):
        now = datetime.now(timezone.utc)
        pr = pr_factory.open()
        pr.author_login = 'miner_user'
        pr.created_at = now - timedelta(days=1)

        issue = issue_factory.create(
            author_login='other_user',
            created_at=now - timedelta(days=5),
            closed_at=now,
            state='CLOSED',
            state_reason=state_reason,
        )

        assert is_valid_issue(issue, pr) is expected

    def test_open_pr_accepts_still_open_issue(self, pr_factory, issue_factory):
        now = datetime.now(timezone.utc)
        pr = pr_factory.open()
        pr.author_login = 'miner_user'
        pr.created_at = now - timedelta(days=1)

        issue = issue_factory.create(
            author_login='other_user',
            created_at=now - timedelta(days=5),
            closed_at=None,
            state='OPEN',
            state_reason=None,
        )

        assert is_valid_issue(issue, pr) is True


class TestIsValidIssueCloseWindow:
    """Close-window must be directional: reject issues closed before pr.merged_at."""

    @pytest.mark.parametrize(
        'close_offset,expected',
        [
            (timedelta(0), True),
            (timedelta(days=MAX_ISSUE_CLOSE_WINDOW_DAYS, seconds=1), False),
            (timedelta(seconds=-1), False),
            (timedelta(hours=-23), False),
        ],
    )
    def test_close_window_is_directional(self, pr_factory, issue_factory, close_offset, expected):
        now = datetime.now(timezone.utc)
        pr = pr_factory.merged(merged_at=now)
        pr.author_login = 'miner_user'
        pr.created_at = now - timedelta(days=2)
        pr.last_edited_at = None

        issue = issue_factory.create(
            author_login='other_user',
            created_at=now - timedelta(days=5),
            closed_at=now + close_offset,
        )

        assert is_valid_issue(issue, pr) is expected
