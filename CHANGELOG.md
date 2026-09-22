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
