"""パッケージバージョンの解決。

インストール済みメタデータを唯一の情報源とし、未インストール（ソースツリー
直参照）の場合のみフォールバックする。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _metadata_version

__all__ = ["__version__"]

try:
    __version__ = _metadata_version("fcenvelope")
except PackageNotFoundError:  # pragma: no cover - インストールされていない場合のみ
    __version__ = "0.0.0.dev0"
