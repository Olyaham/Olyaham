"""Update line-change totals for Olyaham's own, non-merge project commits."""

import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen


LOGIN = "Olyaham"
REPOSITORIES = ("Mar2ianen/project-thessa", "Olyaham/freshGram")
ROOT = Path(__file__).resolve().parents[1]
MARKER = re.compile(
    r"<!-- commit-loc:start -->\n.*?<!-- commit-loc:end -->", re.DOTALL
)
HISTORY_QUERY = """
query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    isPrivate
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $author}) {
            pageInfo { hasNextPage endCursor }
            nodes {
              oid additions deletions
              parents { totalCount }
              author { user { login } }
            }
          }
        }
      }
    }
  }
}
"""


def graphql(query, variables):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "Olyaham-profile-stats",
        },
    )
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"]))
    return result["data"]


def collect_totals():
    user = graphql(
        "query($login: String!) { user(login: $login) { id } }", {"login": LOGIN}
    )["user"]
    commits = {}
    for full_name in REPOSITORIES:
        owner, name = full_name.split("/")
        cursor = None
        while True:
            repository = graphql(
                HISTORY_QUERY,
                {"owner": owner, "name": name, "author": user["id"], "cursor": cursor},
            )["repository"]
            if repository is None or repository["isPrivate"]:
                raise RuntimeError(f"Public repository unavailable: {full_name}")
            branch = repository["defaultBranchRef"]
            if branch is None:
                break
            history = branch["target"]["history"]
            for commit in history["nodes"]:
                author = commit["author"]["user"]
                if (
                    author is not None
                    and author["login"].casefold() == LOGIN.casefold()
                    and commit["parents"]["totalCount"] <= 1
                ):
                    # Shared commits across repositories must only count once.
                    commits[commit["oid"]] = commit
            if not history["pageInfo"]["hasNextPage"]:
                break
            next_cursor = history["pageInfo"]["endCursor"]
            if next_cursor is None or next_cursor == cursor:
                raise RuntimeError(f"Invalid history cursor: {full_name}")
            cursor = next_cursor
    return (
        len(commits),
        sum(commit["additions"] for commit in commits.values()),
        sum(commit["deletions"] for commit in commits.values()),
    )


def main():
    count, added, deleted = collect_totals()
    en = f"**{count:,} commits** · **+{added:,}** / **−{deleted:,}** lines"
    ru = f"Коммитов: **{count:,}** · Строк: **+{added:,}** / **−{deleted:,}**".replace(
        ",", " "
    )
    updates = []
    for filename, text in (("README.md", en), ("README_RU.md", ru)):
        path = ROOT / filename
        original = path.read_text(encoding="utf-8")
        replacement = f"<!-- commit-loc:start -->\n{text}\n<!-- commit-loc:end -->"
        updated, matches = MARKER.subn(lambda _: replacement, original)
        if matches != 1:
            raise RuntimeError(f"Expected one stats block in {filename}, got {matches}")
        if updated != original:
            updates.append((path, updated))
    for path, updated in updates:
        path.write_text(updated, encoding="utf-8")
    print(f"{count} commits; +{added} / -{deleted} lines across {len(REPOSITORIES)} projects")


if __name__ == "__main__":
    main()
