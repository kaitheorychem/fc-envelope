# リリースの手順

版は `pyproject.toml` の `version` に書き、git タグ `vX.Y.Z` をそれに合わせる。
なぜそうするかは [ADR-0073](../adr/0073-version-is-pyproject-and-a-matching-git-tag.md)
にある。ここに書くのは手順だけである。

## 何番を打つか

直前のリリースから何が変わったかで決める。

| 変わったもの | 上げる桁 |
|---|---|
| 公開 API・CLI・ファイル形式のどれかを取り上げた、意味を変えた | X |
| そのどれかに足した。または同じ入力から出る数が変わった | Y |
| どれも変わらない（文書・テスト・内部の整理・数の変わらない修正） | Z |

1.0.0 の前は X を上げない。上の表の X に当たる変更も Y を上げる。

## 手順

以下は `main` が緑（CI が通っている）ことを確かめてから行う。

### 1. 版を上げる

`pyproject.toml` の `version` を書き換える。

```toml
[project]
version = "0.2.0"
```

続けて lock を追随させる。`uv.lock` は本体の版も記録しているので、これを忘れると
CI の `uv sync --locked` が止まる。

```bash
uv lock
```

### 2. `CHANGELOG.md` を書く

`## 未リリース` の見出しを `## 0.2.0 - 2026-09-20` の形（版番号と、打つ日の日付）に
変える。その上に空の `## 未リリース` を新しく置く。

中身は利用者から見て何が変わったかで書く。内部の整理は書かない。

### 3. テストを走らせる

```bash
uv sync
uv run pytest
```

`uv sync` を先に打つのは、`fcenvelope.__version__` がインストール済みメタデータから
来るためである。入れ直さないと版を上げる前の値が残り、`test/test_version.py` が
落ちる。

### 4. コミットして PR を出す

```bash
git switch -c release/v0.2.0
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "v0.2.0"
git push -u origin release/v0.2.0
```

PR の CI が緑になったら main へマージする。

### 5. タグを打つ

マージ後の main に対して打つ。**タグが指すのはマージコミットである。**

```bash
git switch main
git pull origin main
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

タグ名は `v` を付けた `vX.Y.Z`。`pyproject.toml` に書いた版には `v` を付けない。

### 6. 確かめる

```bash
git describe --tags          # v0.2.0
uv run fcenvelope --version  # 0.2.0
```

2 つが（`v` の有無を除いて）一致していればよい。

## 打ち間違えたとき

**まだ push していないタグ**は付け替えてよい。

```bash
git tag -d v0.2.0
```

**push した後のタグは動かさない。** 他の人の手元にある `v0.2.0` と、リモートの
`v0.2.0` が違うコミットを指す状態になるためである。間違いに気づいたら、そのタグは
そのままにして、直した内容で次の番号（`v0.2.1`）を打つ。`CHANGELOG.md` には
その版で何を直したかを書く。
