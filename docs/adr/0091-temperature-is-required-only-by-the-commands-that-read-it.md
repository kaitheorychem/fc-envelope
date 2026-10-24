# temperature も読む命令にとってだけ必須にし、show は CSV に最小の入力を案内する

- 日付: 2026-10-24
- 状態: 受理（ADR-0075 の「必須かどうかは読む側が決める」を `temperature` にも広げる。
  ADR-0086 の `show` が入力ファイルを読むことはそのまま）

ADR-0086 で `show` は入力ファイルから結合の図を出せるようになった。結合の図に要るのは
`[modes]` だけだが、入力ファイルの型は `temperature` を必須フィールドにしていたので、
CSV のモード表を一目見るためだけの入力にも、使われない温度を書く必要があった。これは
ADR-0075 が `broadening` / `grid` について取り除いたのと同じ形の制約である。

また、CSV そのものを `show` に渡すと「拡張子から書式が分からない」とだけ言って止まり、
何を書けば見られるのかが伝わらなかった。

**`temperature` は省略でき、無いことは `to_temperature()` が言う。`show` は CSV を
渡されると、読まずに、その CSV を辿る最小の入力ファイルを案内する。**

```
$ fcenvelope show modes.csv
error: modes.csv: `show` does not take a CSV file directly, because a CSV holds only
numbers and not what its columns are. Pass an input file that points to the CSV instead:
save the two lines below as modes.toml next to the CSV

    [modes]
    csv = { path = "modes.csv", columns = ["frequency", "coupling"] }

and run `fcenvelope show modes.toml`. ...

$ fcenvelope lines modes.toml
error: temperature: required by `fcenvelope run` and `fcenvelope lines` (add temperature = <T in K>; 0 is allowed)
```

## 決まりごと

- `temperature` を省略しても既定値では埋めない。温度は計算ごとに選ぶ条件で、分子に
  よらない既定値は無い（ADR-0035, 0075 と同じ理由）。
- `run` / `lines` は `temperature` が無ければ終了コード 1 で止まる。`--override temperature=...`
  で補える。
- CSV の判定は拡張子 `.csv` で行う（ADR-0069 と同じく中身は見ない）。CLI では読む前に分かる
  使い方の誤りなので、使用法エラー（終了コード 2）にして痕跡のログは残さない。ライブラリの
  `show` / `load_shown` は `InvalidInputError` で同じ案内を返す。
- 案内は、まず CSV を直接は受け付けないことと入力ファイルを渡せばよいことを言い、次に
  保存するファイル名と実行する命令まで具体的に示す。書く中身は `show` が読む `[modes]` だけである。既定の列の並び（振動数 cm⁻¹、結合 g）を
  示し、単位と流儀の変え方を一言添える。

## 検討した選択肢

- **`show` が CSV を直接読み、列の並び・単位・流儀を CLI のオプションで受ける**: 入力
  ファイルの `[modes]` と同じことをオプションでもう一度表すことになり、書き方が 2 通りに
  なる。CSV には数しか無いので、何かで列の意味を書く必要は残る。それなら入力ファイルに
  書いてもらい、`run` / `lines` にそのまま回せるほうがよい。
- **CSV を既定の列の並びとみなして黙って描く**: 単位や流儀の取り違えを確かめるための図
  （ADR-0086）なのに、取り違えたまま「それらしい」図が出る。
- **`show` のときだけ `temperature` の検査を外す**: 入力ファイルの型が命令ごとに変わる。
  ADR-0075 の形（型は省略を許し、読む側が言う）にそろえるほうが単純である。
