# FC Envelopeの計算

## 概要
振電相互作用、振動数(ω_α)、温度(T)の３点を元にFranck-Condon Enveropeを計算する。
振電相互作用は g・Δ・S・λ の 4 つの流儀のいずれで書いてもよく、エネルギーの単位も
cm⁻¹・eV・hartree・THz・kJ/mol・kcal/mol から選べる。どちらも入力を読む時点で
内部の正準形（ε [cm⁻¹] と Huang-Rhys 因子 S）へ畳まれる。
併せて、主要な離散FC因子とその遷移エネルギーの一覧も出力できる。
両者は同じ縦軸で1枚に重ねてグラフ化できる。

## 技術構成
python + uv で実装。Python 3.11 以上。
CLI（typer）から入力 JSON の読み込み・結果 JSON の書き出し・グラフ出力ができる。
ライブラリとしては `pip install` でインストールし、スペクトルの表現ごとに
「計算・保存・読み込み・描画」の自由関数 4 つを 1 組として公開する。

| 表現 | 計算 | 保存 | 読み込み | 描画 |
|---|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` | `save_envelope` | `load_envelope` | `plot_envelope` |
| 線 | `compute_fc_lines` | `save_lines` | `load_lines` | `plot_lines` |

加えて、両者を 1 枚に重ねる `plot_overlay` と、理論式の行列そのものを返す
`fc_factor_matrix` を公開する。結果クラスは純粋なデータ容器で、I/O と描画の責務は持たない。

## ディレクトリ
- CONTEXT.md: 用語集。語の定義と避けるべき言い換えのみ。
- src/: 実装本体。`src/<パッケージ名>/` の形で置く。
- docs/: ドキュメント
  - adr/: 設計上の決定記録（Architecture Decision Record）。連番・追記のみ。決定を覆すときは新しい ADR を起こし、古い方の状態を更新する。
  - dev/: 実装関係。開発者のための資料。
    - spec/: 仕様。実装とずれやすいので、変更が行われにくいインターフェイス部分のみを簡潔に記載し、詳細は実際のコードの方を本体とする。
    - plan/: 実行が決まった作業の段取り。完了したら削除するか spec/ に畳む。
    - idea/: 考え中のアイデア・思いつきなど。実行に写すかどうか未確定のメモ。
  - readme/: READMEの補助ドキュメント。ユーザとして使う人のための資料。
    - examples/: そのまま動く入力ファイルの実例。文書の説明と食い違わないことをテストで見る。
  - theory/: 実装のための元になる理論
- test/: テスト用。pytestによる実装


## インストール / 実行

[uv](https://docs.astral.sh/uv/) で管理。

```bash
uv sync          # 依存関係をインストール
uv run fcenvelope --help
uv run fcenvelope --version
```

## 使い方

```bash
uv run fcenvelope run input.json -o result.json --plot spectrum.png
uv run fcenvelope lines input.json -o lines.json --plot sticks.png
uv run fcenvelope plot result.json -o spectrum.png --title "300 K"
uv run fcenvelope plot result.json lines.json -o overlay.png   # 2つを重ねる
uv run fcenvelope run input.json -o result.json --log run.log  # 節目のログを残す
```

```python
from fcenvelope import (
    FCEnvelopeInput, compute_envelope, compute_fc_lines,
    plot_envelope, plot_overlay, save_envelope, save_lines,
)

parsed = FCEnvelopeInput.from_path("input.json")
system = parsed.to_system()

result = compute_envelope(
    system,
    temperature=parsed.to_temperature(),
    broadening=parsed.to_broadening(),
    grid=parsed.to_grid(),
)
save_envelope(result, "result.json")
plot_envelope(result).savefig("spectrum.png", dpi=300)

lines = compute_fc_lines(
    system, temperature=parsed.to_temperature(), selection=parsed.to_selection()
)
save_lines(lines, "lines.json")

plot_overlay(result, lines).savefig("overlay.png", dpi=300)
```

`--log` を指定しなければログファイルは作らない。エラーで終わったときだけ、そこまでの
節目の記録を出力ファイルの隣（`result.log`）に残す。

入力ファイルの書き方・流儀と単位の選び方・E 軸の符号規約・診断値の読み方・ログの
読み方は [docs/readme/usage.md](docs/readme/usage.md) を参照。
単位を書いた入力の実例は [docs/readme/examples/](docs/readme/examples/) にある。
インターフェイスの一覧は [docs/dev/spec/interface.md](docs/dev/spec/interface.md)。

## テスト

pytest は dev 依存なので `uv sync` で入る。

```bash
uv run pytest
```
