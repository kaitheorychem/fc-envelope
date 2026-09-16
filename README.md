# FC Envelopeの計算

## 概要
無次元化VCC (g_α)、振動数(ω_α)、温度(T)の３点を元にFranck-Condon Enveropeを計算する。
併せて、主要な離散FC因子とその遷移エネルギーの一覧も出力できる。

## 技術構成
python+uvで実装。
CLI呼び出しでjsonからのデータ読み込み+グラフ出力に対応。CLIはtyper使う。
ライブラリとしては`pip install`でインストール。以下の４点くらいがあると良いかな。

- パラメータを引数で受け取り、計算結果を結果クラスとして吐く関数
- 結果クラスのファイル出力を担当する関数
- 計算済みのファイルから結果クラスを再現する関数
- 結果クラスからグラフ出力する関数

## ディレクトリ
- src/: 実装本体。`src/<パッケージ名>/` の形で置く。
- docs/: ドキュメント
  - dev/: 実装関係。開発者のための資料。
    - agreement/: 過去の決定事項。イミュータブル。
    - spec/: 仕様。実装とずれやすいので、変更が行われにくいインターフェイス部分のみを簡潔に記載し、詳細は実際のコードの方を本体とする。
    - idea/: 考え中のアイデア・思いつきなど。実行に写すかどうか未確定のメモ。
  - readme/: READMEの補助ドキュメント。ユーザとして使う人のための資料。
  - theory/: 実装のための元になる理論
- test/: テスト用。pytestによる実装


## インストール / 実行

[uv](https://docs.astral.sh/uv/) で管理。

```bash
uv sync          # 依存関係をインストール
uv run fcenvelope --help
```

## 使い方

```bash
uv run fcenvelope run input.json -o result.json --plot spectrum.png
uv run fcenvelope lines input.json -o lines.json --plot sticks.png
uv run fcenvelope plot result.json -o spectrum.png --title "300 K"
```

```python
from fcenvelope import (
    FCEnvelopeInput, compute_envelope, compute_fc_lines,
    plot_result, save_fc_lines, save_result,
)

parsed = FCEnvelopeInput.from_path("input.json")
result = compute_envelope(parsed.to_modes(), parsed.conditions)
save_result(result, "result.json")
plot_result(result).savefig("spectrum.png", dpi=300)

lines = compute_fc_lines(parsed.to_modes(), temperature=parsed.conditions.temperature)
save_fc_lines(lines, "lines.json")
```

入力ファイルの書き方・E 軸の符号規約・診断値の読み方は
[docs/readme/usage.md](docs/readme/usage.md) を参照。
インターフェイスの一覧は [docs/dev/spec/interface.md](docs/dev/spec/interface.md)。

## テスト

```bash
uv add --dev pytest   # 初回のみ
uv run pytest
```
