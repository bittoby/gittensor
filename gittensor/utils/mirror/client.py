"""HTTP client for the das-github-mirror scoring API.

Three read endpoints (public, no auth, Cloudflare-rate-limited at 50 req / 10s
per IP) and one admin backfill endpoint (not used by the validator). This
client only covers the scoring-hot-path read endpoints.
"""

import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import bittensor as bt
import requests

from gittensor.constants import (
    GITTENSOR_MIRROR_DEFAULT_URL,
    MIRROR_HTTP_TIMEOUT_SECONDS,
    MIRROR_MAX_ATTEMPTS,
)
from gittensor.utils.mirror.models import (
    MirrorIssuesResponse,
    MirrorPullRequestFilesResponse,
    MirrorPullRequestsResponse,
)


class MirrorRequestError(RuntimeError):
    """Raised when a mirror request fails with a non-retryable status or
    exhausts all retries on transient failures."""


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse Retry-After seconds or HTTP-date into a non-negative delay."""
    if not value:
        return None

    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _retry_delay(attempt: int, response: Optional[requests.Response] = None) -> float:
    """Compute retry delay with capped backoff and bounded jitter."""
    backoff = min(5 * (2**attempt), 30)
    retry_after = _parse_retry_after(response.headers.get('Retry-After')) if response is not None else None
    base_delay = max(backoff, retry_after) if retry_after is not None else backoff
    return base_delay + (random.uniform(0, 0.5) * base_delay)


class MirrorClient:
    """Client for https://mirror.gittensor.io scoring endpoints."""

    def __init__(
        self,
        timeout: int = MIRROR_HTTP_TIMEOUT_SECONDS,
        max_attempts: int = MIRROR_MAX_ATTEMPTS,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = GITTENSOR_MIRROR_DEFAULT_URL.rstrip('/')
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = session or requests.Session()

    def get_miner_pulls(
        self,
        github_id: str,
        since: Optional[datetime] = None,
    ) -> MirrorPullRequestsResponse:
        """Fetch every tracked PR authored by ``github_id`` since the given
        datetime. If ``since`` is omitted the mirror defaults to 35 days back.
        Response contains all mirror-tracked repos; caller must filter to the
        scoring config's mirror-enabled subset if it's narrower.
        """
        path = f'/api/v1/miners/{github_id}/pulls'
        params = {'since': since.astimezone(timezone.utc).isoformat()} if since else None
        data = self._get(path, params=params)
        return MirrorPullRequestsResponse.from_dict(data)

    def get_miner_issues(
        self,
        github_id: str,
        since: Optional[datetime] = None,
    ) -> MirrorIssuesResponse:
        """Fetch issues authored by ``github_id`` since the given datetime,
        each with an inline ``solving_pr`` when ``solved_by_pr`` is populated."""
        path = f'/api/v1/miners/{github_id}/issues'
        params = {'since': since.astimezone(timezone.utc).isoformat()} if since else None
        data = self._get(path, params=params)
        return MirrorIssuesResponse.from_dict(data)

    def get_pr_files(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> MirrorPullRequestFilesResponse:
        """Fetch per-file diff metadata and head/base content for a single PR.

        Called only after eligibility filtering — file contents are the
        heaviest payload and shouldn't be pulled speculatively.
        """
        path = f'/api/v1/pulls/{repo_full_name}/{pr_number}/files'
        data = self._get(path)
        return MirrorPullRequestFilesResponse.from_dict(data)

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f'{self.base_url}{path}'
        last_error: Optional[str] = None

        for attempt in range(self.max_attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last_error = f'request exception: {e}'
                if attempt < self.max_attempts - 1:
                    delay = _retry_delay(attempt)
                    bt.logging.warning(
                        f'Mirror GET {path} raised {e} '
                        f'(attempt {attempt + 1}/{self.max_attempts}), retrying in {delay:.2f}s...'
                    )
                    time.sleep(delay)
                continue

            if 200 <= response.status_code < 300:
                return response.json()

            # 4xx except 429 are not retryable — fail fast so callers see the real error.
            if 400 <= response.status_code < 500 and response.status_code != 429:
                raise MirrorRequestError(f'Mirror GET {path} returned {response.status_code}: {response.text[:200]}')

            last_error = f'status {response.status_code}: {response.text[:200]}'
            if attempt < self.max_attempts - 1:
                delay = _retry_delay(attempt, response)
                bt.logging.warning(
                    f'Mirror GET {path} failed ({last_error}) '
                    f'(attempt {attempt + 1}/{self.max_attempts}), retrying in {delay:.2f}s...'
                )
                time.sleep(delay)

        raise MirrorRequestError(f'Mirror GET {path} failed after {self.max_attempts} attempts: {last_error}')
