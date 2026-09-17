# `schema_version` を 2 へ上げ、v1 の互換層を置かない

- 日付: 2026-09-16
- 状態: 受理

ADR-0035 で入力 JSON の形が変わり（`conditions` → `temperature` / `broadening` / `grid` /
`selection`）、ADR-0031 / ADR-0032 で出力の `kind` と `spectrum.intensity` → `density` が
変わる。`schema_version` を 2 へ上げ、v1 は `SchemaVersionError` で明示的に拒否する。

v1 を読むための変換層は**置かない**。v1 は実運用に上げておらず、現存するのは `data/` の
数個だけで、入力 JSON から数秒で再生成できる。互換層は一度置くと恒久的に維持コストが
かかり、version 3 のときには v1→v2→v3 の連鎖になる。

## 検討した選択肢

`schema_version` を 1 のまま意味だけ変えることも検討した（v1 は仕様を固めるための仮置き
であり、外に出ていないため）。採らなかった理由は互換性ではなく**エラーの質**である。
バージョンを据え置くと `data/` の現存ファイルは「`temperature` が無い」という欠損
フィールドのエラーになるが、上げれば「schema_version 1 は非対応」と一言で出る。実際に
これを踏むのは開発者一人なので、その一人にとって分かりやすい方を取る。整数 1 つのコスト。
