# FC Envelopeの計算

## 概要
振電相互作用、振動数(ω_α)、温度(T)の３点を元にFranck-Condon Enveropeを計算する。
振電相互作用は g・Δ・S・λ の 4 つの流儀のいずれで書いてもよく、エネルギーの単位も
cm⁻¹・eV・hartree・THz・kJ/mol・kcal/mol から選べる。どちらも入力を読む時点で
内部の正準形（ε [cm⁻¹] と Huang-Rhys 因子 S）へ畳まれる。
併せて、主要な離散FC因子とその遷移エネルギーの一覧も出力できる。
両者は同じ縦軸で1枚に重ねてグラフ化できる。

グラフは計算に添えて生成される**作図スクリプト**で作る。図の設定はすべてそのスクリプトの
中にあるので、計算をやり直さずに何度でも調整でき、実行後も読み返せる。

## 技術構成
python + uv で実装。Python 3.11 以上。
CLI（typer）から入力ファイルの読み込みと結果 JSON の書き出しができる。入力ファイルは
TOML を基本とし、JSON でも同じように読める（書式は拡張子で決まる）。図は CLI では
描かず、結果の隣に置かれる作図スクリプト（matplotlib）を走らせて作る。
ライブラリとしては `pip install` でインストールし、スペクトルの表現ごとに
「計算・保存・読み込み・描画」の自由関数 4 つを 1 組として公開する。

| 表現 | 計算 | 保存 | 読み込み | 描画 |
|---|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` | `save_envelope` | `load_envelope` | `plot_envelope` |
| 線 | `compute_fc_lines` | `save_lines` | `load_lines` | `plot_lines` |

加えて、両者を 1 枚に重ねる `plot_overlay` と、理論式の行列そのものを返す
`fc_factor_matrix` を公開する。結果クラスは純粋なデータ容器で、I/O と描画の責務は持たない。
作図スクリプトの生成は `fcenvelope.emit`、その雛形は `src/fcenvelope/templates/` にある。

## ディレクトリ
- CONTEXT.md: 用語集。語の定義と避けるべき言い換えのみ。
- CHANGELOG.md: 版ごとの変更履歴。利用者から見て何が変わったかだけを書く。
- src/: 実装本体。`src/<パッケージ名>/` の形で置く。
- docs/: ドキュメント
  - adr/: 設計上の決定記録（Architecture Decision Record）。連番・追記のみ。決定を覆すときは新しい ADR を起こし、古い方の状態を更新する。
  - dev/: 実装関係。開発者のための資料。
    - spec/: 仕様。実装とずれやすいので、変更が行われにくいインターフェイス部分のみを簡潔に記載し、詳細は実際のコードの方を本体とする。
    - plan/: 実行が決まった作業の段取り。完了したら削除するか spec/ に畳む。
    - idea/: 考え中のアイデア・思いつきなど。実行に写すかどうか未確定のメモ。
    - release.md: リリースの手順。版の上げ方とタグの打ち方。
  - readme/: READMEの補助ドキュメント。ユーザとして使う人のための資料。
    - examples/: そのまま動く入力ファイルの実例（TOML と JSON）。文書の説明と食い違わないことをテストで見る。
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
uv run fcenvelope run input.toml     # -> input_envelope.json, input_envelope_config.json,
                                     #    input_envelope_plot.py
uv run python input_envelope_plot.py # 図を作る。端末にも出る
uv run fcenvelope lines input.toml   # -> input_lines.json, ...

# 名前を決めるなら -o。条件を差し替えるなら --override
uv run fcenvelope run input.toml -o result.json --override temperature=0

# 2つを1枚に重ねる作図スクリプトを作る
uv run fcenvelope script input_envelope.json input_lines.json -o overlay_plot.py
uv run python overlay_plot.py

uv run fcenvelope run input.toml --log run.log  # 節目のログを残す
```

`-o` を省くと入力ファイルの名前を継いだ出力が入力の隣に出る。その実行で実際に使われた
設定は `*_config.json` に書き出され、それをそのまま入力として与えれば同じ計算になる。
入力を書くのは TOML、この正準化された設定を読み返すのが JSON、という使い分けである。

作図スクリプトは `json` と `matplotlib` だけで動き、`fcenvelope` を import しない。
表題・色・軸の範囲・横軸の単位はすべてその中の定数で、直して走らせ直せば図が変わる。
計算をやり直しても上書きされないので、調整した設定は新しいデータにそのまま当たる。

```python
from fcenvelope import (
    FCEnvelopeInput, compute_envelope, compute_fc_lines,
    plot_envelope, plot_overlay, save_envelope, save_lines,
)

parsed = FCEnvelopeInput.from_path("input.toml")
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
入力ファイルの実例は [docs/readme/examples/](docs/readme/examples/) にある。
インターフェイスの一覧は [docs/dev/spec/interface.md](docs/dev/spec/interface.md)。

## テスト

pytest は dev 依存なので `uv sync` で入る。

```bash
uv run pytest
```

同じコマンドが GitHub Actions でも走る（`.github/workflows/test.yaml`）。main への push と
pull request のたびに、Python 3.11 と 3.13 の 2 つで実行される。

## 版とリリース

版番号は `pyproject.toml` の `version` に書き、リリースのときに同じ番号の git タグ
`vX.Y.Z` を打つ。書かれた版が唯一の情報源で、タグはそれを指す印である。

```bash
uv run fcenvelope --version   # 0.1.0
git describe --tags           # v0.1.0
```

番号は semantic versioning として読む。判定の対象は、利用者から見える公開 API・CLI・
ファイル形式の 3 つである。取り上げれば X、足せば Y、どれも変わらなければ Z が上がる。
同じ入力から出る数が変わる変更は、不具合修正であっても Y を上げる。1.0.0 の前は X を
上げず、Y が major と minor を兼ねる。

入力ファイルと結果ファイルの `schema_version` は**これとは別の数**である。形式が 3 の
まま版だけが進むことも、形式だけが上がることもある。

版ごとに何が変わったかは [CHANGELOG.md](CHANGELOG.md)、リリースの手順は
[docs/dev/release.md](docs/dev/release.md)、そう決めた理由は
[ADR-0073](docs/adr/0073-version-is-pyproject-and-a-matching-git-tag.md) にある。
