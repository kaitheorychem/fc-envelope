"""版番号が 3 か所で一致していること（ADR-0073）。

`pyproject.toml` に書いた版が唯一の情報源で、`uv.lock` と `CHANGELOG.md` と
インストール済みメタデータはそれに追随する。どれか 1 つを上げ忘れた組み合わせを
ここで止める。タグは push の後に打つので、手順書（`docs/dev/release.md`）の側で見る。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import fcenvelope

ROOT = Path(__file__).resolve().parents[1]

#: `vX.Y.Z` の X.Y.Z の部分。前後に何も付かない 3 つの数だけを許す。
RELEASE_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

#: `CHANGELOG.md` の版の見出し。`## 0.1.0 - 2026-09-20`。
HEADING_PATTERN = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)

UNRELEASED_HEADING = "## 未リリース"


@pytest.fixture(scope="module")
def declared_version() -> str:
    """`pyproject.toml` に書かれた版。これが情報源である。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


@pytest.fixture(scope="module")
def changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_declared_version_is_x_y_z(declared_version: str) -> None:
    assert RELEASE_PATTERN.match(declared_version), (
        f"pyproject.toml の version は X.Y.Z の 3 つの数で書く: {declared_version!r}"
    )


def test_installed_metadata_matches_pyproject(declared_version: str) -> None:
    """`fcenvelope.__version__` はインストール済みメタデータから来る。

    版を上げた後に入れ直していないと、ここで古い値が見える。結果ファイルの来歴
    （`fcenvelope_version`）に入るのはこちらなので、ずれたまま計算させない。
    """
    assert fcenvelope.__version__ == declared_version, (
        f"インストール済みの版 {fcenvelope.__version__!r} が pyproject.toml の "
        f"{declared_version!r} と違う。`uv sync` で入れ直す"
    )


def test_lockfile_matches_pyproject(declared_version: str) -> None:
    """`uv.lock` は本体の版も記録している。ずれると CI の `uv sync --locked` が止まる。"""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    root = [p for p in lock["package"] if p["name"] == "fcenvelope"]
    assert len(root) == 1, "uv.lock に fcenvelope の項目が 1 つだけあるはず"
    assert root[0]["version"] == declared_version, (
        f"uv.lock の版 {root[0]['version']!r} が pyproject.toml の "
        f"{declared_version!r} と違う。`uv lock` で追随させる"
    )


def test_changelog_has_an_unreleased_section(changelog: str) -> None:
    """次のリリースまでの変更を積む場所。リリースのときにここが版の見出しになる。"""
    assert UNRELEASED_HEADING in changelog, (
        f"CHANGELOG.md に {UNRELEASED_HEADING!r} の見出しが要る"
    )


def test_changelog_newest_entry_is_the_declared_version(
    changelog: str, declared_version: str
) -> None:
    headings = HEADING_PATTERN.findall(changelog)
    assert headings, "CHANGELOG.md に `## X.Y.Z - YYYY-MM-DD` の見出しが 1 つも無い"
    newest = headings[0][0]
    assert newest == declared_version, (
        f"CHANGELOG.md の最新の見出しは {newest!r} だが pyproject.toml は "
        f"{declared_version!r}。版を上げたら CHANGELOG.md にも見出しを足す"
    )


def test_changelog_versions_descend(changelog: str) -> None:
    """見出しは新しい順に並ぶ。重複も許さない。"""
    versions = [tuple(int(n) for n in v.split(".")) for v, _ in HEADING_PATTERN.findall(changelog)]
    assert versions == sorted(set(versions), reverse=True), (
        f"CHANGELOG.md の版の見出しが新しい順に並んでいない: {versions}"
    )
