import os

import requests

from setup import get_version_from_changelog

GITHUB_API_TOKEN = os.environ["GITHUB_API_TOKEN"]


def make_github_release():
    version = get_version_from_changelog()
    tag = f"v{version}"

    with open("CHANGELOG.md", "r", encoding="utf-8") as f:
        changelog_data = f.read()

    changelog_lines = []

    for line in changelog_data.splitlines():
        if line.startswith("# "):
            if line != f"# {tag}":
                break
            continue

        changelog_lines.append(line)

    changelog = "\n".join(changelog_lines).strip()

    response = requests.post(
        "https://api.github.com/repos/pyinfra-dev/pyinfra/releases",
        json={
            "tag_name": tag,
            "body": changelog,
        },
        headers={
            "Authorization": f"token {GITHUB_API_TOKEN}",
        },
    )
    response.raise_for_status()


if __name__ == "__main__":
    make_github_release()
