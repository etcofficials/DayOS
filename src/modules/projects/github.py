"""Optional, read-only GitHub information for a project's repository (official REST API).

Works without an account for public repositories (GitHub allows about 60 requests an
hour). Users who want private repositories or a higher limit can save a personal access
token, which is kept only in Windows Credential Manager — never in DayOS's database,
settings, exports, logs or source. DayOS only reads; it never changes anything on GitHub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.services import credentials, http

API = "https://api.github.com"
CREDENTIAL = "github-token"
_REPO = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")


def parse_repo(url: str) -> tuple[str, str] | None:
    m = _REPO.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _headers(token: str | None) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@dataclass
class RepoInfo:
    full_name: str
    description: str = ""
    html_url: str = ""
    private: bool = False
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    default_branch: str = ""
    pushed_at: str = ""
    issues: list[dict] = field(default_factory=list)  # {number, title, url, updated}
    pulls: list[dict] = field(default_factory=list)
    releases: list[dict] = field(default_factory=list)  # {name, tag, url, published, draft, prerelease}
    authenticated: bool = False


def _get(path: str, token: str | None):
    return http.get_json(API + path, headers=_headers(token))


def fetch_repo(owner: str, repo: str, token: str | None = None) -> RepoInfo:
    """A few GET requests (call from a worker thread). Raises http.HttpError."""
    base = f"/repos/{owner}/{repo}"
    try:
        data = _get(base, token)
    except http.HttpError as exc:
        if exc.status == 404:
            raise http.HttpError("http", "GitHub couldn't find that repository (or it's private and no token is "
                                         "saved).", 404) from None
        raise
    info = RepoInfo(data.get("full_name", f"{owner}/{repo}"), data.get("description") or "",
                    data.get("html_url", ""), bool(data.get("private")), int(data.get("stargazers_count") or 0),
                    int(data.get("forks_count") or 0), int(data.get("open_issues_count") or 0),
                    data.get("default_branch", ""), data.get("pushed_at", ""), authenticated=bool(token))
    for item in _get(base + "/issues?state=open&per_page=10&sort=updated", token) or []:
        if "pull_request" not in item:  # the issues endpoint also lists pull requests
            info.issues.append({"number": item.get("number"), "title": item.get("title", ""),
                                "url": item.get("html_url", ""), "updated": item.get("updated_at", "")})
    for item in _get(base + "/pulls?state=open&per_page=10&sort=updated", token) or []:
        info.pulls.append({"number": item.get("number"), "title": item.get("title", ""),
                           "url": item.get("html_url", ""), "updated": item.get("updated_at", "")})
    for item in _get(base + "/releases?per_page=5", token) or []:
        info.releases.append({"name": item.get("name") or item.get("tag_name", ""), "tag": item.get("tag_name", ""),
                              "url": item.get("html_url", ""), "published": item.get("published_at") or "",
                              "draft": bool(item.get("draft")), "prerelease": bool(item.get("prerelease"))})
    return info


def saved_token() -> str | None:
    return credentials.load(CREDENTIAL)


def check_token(token: str) -> str:
    """Returns the GitHub login the token belongs to (raises http.HttpError if it doesn't work)."""
    data = _get("/user", token)
    return str(data.get("login", ""))
