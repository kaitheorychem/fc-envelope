# 変更履歴

このファイルは、利用者から見て何が変わったかを版ごとに記録する。番号の付け方と
リリースの手順は [ADR-0073](docs/adr/0073-version-is-pyproject-and-a-matching-git-tag.md)
と [docs/dev/release.md](docs/dev/release.md) にある。

書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に倣い、版番号は
[semantic versioning](https://semver.org/lang/ja/) に従う。

## 未リリース

### 追加

- 入力ファイルの雛形を書き出す `fcenvelope template`。項目ごとに、それが何を設定する数かの
  短いコメントが 1 行ずつ付く。`-o` を省くと端末に出る。既にあるファイルは上書きせずに
  残す（`--force` で上書きする）。コメントが雛形の中身なので、書式は TOML だけである。
- 流儀 `coupling_convention = "vcc"`。振電相互作用定数 V を `hartree/(bohr*sqrt(m_e))`
  （別名 `a.u.`）で受け、S = V²/(2ε³) で読む。相手プログラムの出力は
  `coupling = [-0.3, 1e-4, "a.u."]` のようにそのまま写せる。
- 単位の別名と倍率。`"a.u."` はエネルギーの欄では `hartree`、V の欄では
  `hartree/(bohr*sqrt(m_e))` を指す。倍率は配列の要素として数で書き、単位の欄なら
  `[1e-3, "eV"]`、値に添えるなら `[18.6, 1e-3, "eV"]` とする。
  実効設定には別名を正式名に置き換えた形で書き出す。

### 修正

- 流儀 `lambda` で振動数を 0 にすると `ZeroDivisionError` で落ちていた。どのモードの
  振動数が正でないかを名指しした入力の誤りとして止まるようにした。

### 変更

- **入力ファイルの形が変わり、`schema_version` が 4 になった。** 版 3 の入力ファイルは
  読めないので、次のように書き換える（ADR-0079）。
  - トップレベルの `frequency_unit` / `coupling_convention` / `coupling_unit` を、新しい
    `[modes]` ブロックへ移す。これらが効くのはモード表の列だけなので、表の側に置く。
  - `[[modes]]` を `[[modes.rows]]` に書き換える。
  - `modes = { path = "modes.csv" }` を、`[modes]` の中の `csv = { path = "modes.csv" }`
    に書き換える。
- **結果ファイルの `input`（入力エコー）が `conditions`（計算条件）に変わり、結果
  ファイルの `schema_version` が 4 になった。** 入力ファイルの形は写さず、モードは
  `{"frequency", "huang_rhys"}` で書き、流儀の欄は持たない。入力の書き方が今後
  変わっても結果ファイルの形と版は変わらない。
- **結果ファイルの単位を入力ファイルと同じ書き方にした。** 有次元の値は `[値, "単位"]`
  の組（例 `"sigma": [150.0, "cm^-1"]`）、表は表のブロックに列の単位を書く
  （`spectrum.energy_unit`、`lines.energy_unit`、`conditions.modes.frequency_unit`）。
  ヘッダの `energy_unit` / `density_unit` はなくなった。`lines` は `rows` を持つ表になった
  （ADR-0081）。版 3 の結果ファイルは読めず、生成済みの
  作図スクリプトは版 4 の結果ファイルを読まないので、`fcenvelope script` で作り直す
  （ADR-0080）。
- CSV から読むモード表に、列の並びと列ごとの単位を書けるようになった。
  `csv = { path = "modes.csv", columns = [["frequency", "eV"], "coupling"] }` のように書き、
  単位を添えない列は `[modes]` の既定の単位で読む。`columns` を省くと今までどおり
  `frequency, coupling` の順で読む。CSV にヘッダがあり `columns` も書いたときは、両者の
  並びが一致しなければ止まる。
- `[broadening]` と `[grid]` を書かなくても入力ファイルが読めるようになった。この 2 つを
  読むのは `run` だけなので、`lines` しか使わない入力に使わないグリッドを書く必要はない。
  `run` に渡して足りなければ、どのブロックが要るかを名指しして止まる。

## 0.1.0 - 2026-09-20

最初のリリース。この版で使えることは次のとおり。

### 追加

- エンベロープ F(E) の計算（`compute_envelope`）。無次元化振電相互作用・振動数・温度から、
  変位型調和振動子の Franck-Condon スペクトルを時間相関関数のフーリエ変換で求める。
- 離散 FC 因子の計算（`compute_fc_lines`、`fc_factor_matrix`）。どのモードが何量子ぶん
  変化した線かというラベルつきで返す。
- 結果の保存と読み込み（`save_envelope` / `load_envelope` / `save_lines` / `load_lines`）。
  結果ファイルには入力の正準形と来歴（計算した版と時刻）と診断値が入る。
- 作図（`plot_envelope` / `plot_lines` / `plot_overlay`）。エンベロープと線を同じ縦軸で
  1 枚に重ねられる。
- CLI の 3 つの副命令。`fcenvelope run`（エンベロープ）、`fcenvelope lines`（線）、
  `fcenvelope script`（作図スクリプトの生成）。`--version` でパッケージの版を表示する。
- 計算に添えて生成される作図スクリプト。`json` と `matplotlib` だけで動き、図の設定は
  すべてその中の定数にある。計算をやり直しても上書きされない。
- 入力ファイル。TOML を基本とし、生成された設定を読み返すために JSON でも読める。
  書式は拡張子で決まる。
- 振電相互作用の 4 つの流儀（`g` / `delta` / `huang_rhys` / `lambda`）。読んだ時点で
  Huang-Rhys 因子 S へ正準化する。
- エネルギー単位 6 種（`cm^-1` / `eV` / `hartree` / `THz` / `kJ/mol` / `kcal/mol`）。
  有次元の値は `sigma = [0.0186, "eV"]` のように値そのものに単位を添えて書ける。
  添えなければブロックの既定の単位で読む。
- `--override` による入力項目の一時的な差し替え。入力ファイルと同じ単位・流儀で読む。
  `modes` と `schema_version` は対象外。
- 実効設定の書き出し（`*_config.json`）。その実行で実際に使われた設定が計算の前に
  書き出され、そのまま入力として読み返せる。
- 診断値と品質の警告。警告文はその値を動かすつまみを名指しする。
- `--log` による節目のログ。指定が無くても、エラーで終わったときは出力の隣に残る。

### 備考

- 入力ファイルと結果ファイルの `schema_version` は 3 である。これはファイル形式の版で、
  パッケージの版とは別の数である。
- 振電相互作用定数 V の流儀は保留で、まだ受け付けない。
