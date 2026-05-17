"""GitHub API wrapper. PR comments, descriptions, diffs."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from github import Auth, Github, GithubException
from github.PullRequest import PullRequest

from trace_cli.credentials import Credentials

log = logging.getLogger("trace.github")

PR_URL_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)/?$"
)


# --- Exceptions ----------------------------------------------------------

class GitHubAuthError(Exception):
    """Token invalid / lacks scope."""


class GitHubError(Exception):
    """Catch-all."""


# --- Models --------------------------------------------------------------

@dataclass(frozen=True)
class PRRef:
    owner: str
    repo: str
    number: int
    url: str

    @classmethod
    def parse(cls, url: str) -> "PRRef":
        m = PR_URL_RE.match(url)
        if not m:
            raise ValueError(
                f"Invalid PR URL: {url!r}. Expected https://github.com/<owner>/<repo>/pull/<n>"
            )
        return cls(owner=m.group(1), repo=m.group(2), number=int(m.group(3)), url=url)


def validate_pr_url(url: str) -> PRRef:
    """R4.7: return PRRef on match, raise ValueError otherwise."""
    return PRRef.parse(url)


# --- Client --------------------------------------------------------------

class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        Credentials.require("GITHUB_TOKEN")
        self._token = token or os.environ["GITHUB_TOKEN"]
        self._gh = Github(auth=Auth.Token(self._token))

    def _pr(self, ref: PRRef) -> PullRequest:
        try:
            return self._gh.get_repo(f"{ref.owner}/{ref.repo}").get_pull(ref.number)
        except GithubException as e:
            if e.status in (401, 403):
                raise GitHubAuthError(str(e)) from e
            raise GitHubError(str(e)) from e

    def get_pr_files(self, pr_url: str) -> list[dict]:
        """Returns list of {path, additions, deletions, changes, patch}."""
        ref = validate_pr_url(pr_url)
        pr = self._pr(ref)
        try:
            return [
                {
                    "path": f.filename,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "changes": f.changes,
                    "patch": f.patch or "",
                }
                for f in pr.get_files()
            ]
        except GithubException as e:
            raise GitHubError(str(e)) from e

    def post_comment(self, pr_url: str, body: str) -> str:
        """Post issue comment on PR. Returns comment URL."""
        ref = validate_pr_url(pr_url)
        pr = self._pr(ref)
        try:
            c = pr.create_issue_comment(body)
            log.info("posted PR comment id=%s", c.id)
            return c.html_url
        except GithubException as e:
            if e.status in (401, 403):
                raise GitHubAuthError(str(e)) from e
            raise GitHubError(str(e)) from e

    def list_comments(self, pr_url: str, since_iso: str | None = None) -> list[dict]:
        """List issue comments. since_iso filters client-side when provided."""
        ref = validate_pr_url(pr_url)
        pr = self._pr(ref)
        try:
            since_dt = None
            if since_iso:
                from datetime import datetime, timezone
                since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
            comments = []
            for c in pr.get_issue_comments():
                if since_dt and c.created_at and c.created_at.replace(tzinfo=timezone.utc if c.created_at.tzinfo is None else c.created_at.tzinfo) <= since_dt:
                    continue
                comments.append({
                    "id": c.id,
                    "body": c.body or "",
                    "user": c.user.login if c.user else "",
                    "created_at": c.created_at.isoformat() if c.created_at else "",
                    "html_url": c.html_url,
                })
            return comments
        except GithubException as e:
            raise GitHubError(str(e)) from e

    def append_description(self, pr_url: str, addendum: str) -> None:
        """R9.8/9.9: append below existing, preserve original verbatim."""
        ref = validate_pr_url(pr_url)
        pr = self._pr(ref)
        existing = pr.body or ""
        new_body = f"{existing}\n\n{addendum}" if existing.strip() else addendum
        try:
            pr.edit(body=new_body)
        except GithubException as e:
            raise GitHubError(str(e)) from e
