# 雛形は実物の Python ファイルとして持ち、生成ではヘッダだけを差し替える

- 日付: 2026-09-18
- 状態: 受理（スクリプトの中に書いた名前の基準は ADR-0067 が決める）

雛形は `src/fcenvelope/templates/{envelope,lines,overlay}.py` に、**そのまま走る Python
ファイル**として置く。生成は「読んで、生成ヘッダのマーカーに挟まれた範囲だけを差し替えて、
書く」だけで、文字列を組み立てて作らない。

- 雛形そのものが lint と型検査の対象になり、壊れたまま配られることがない。
- 図のコードの差分が、生成ロジックの差分ではなく**図のコードの差分**として読める。
- テストが雛形を直接走らせられる。

```python
# --- generated header (fcenvelope) ---------------------------------------
DATA = Path(__file__).parent / 'result.json'
OUTPUT = Path(__file__).parent / 'fcenvelope-result.png'
KIND = 'fcenvelope.envelope'
SCHEMA_VERSION = 2
# --- end generated header ------------------------------------------------
```

差し替わるのはこの区画だけである。ここから下は生成側が二度と触らない。データの位置は
スクリプトからの相対で解決するので、スクリプトと結果ファイルを一緒に移しても動く。

## 帰結

雛形はパッケージデータとして配る（`importlib.resources` で読む）。`templates/` は
`src/fcenvelope/` の下にあるので、hatchling の設定を足す必要はない。

3 つの雛形は `load` / `terminal_pixel_width` / `show` を同じ形で持つ。単独で動くという
性質（ADR-0058）のために共有できないので、**食い違わないことをテストで留める**。
