# coupling の単位と流儀の噛み合わせは入力を読んだ時点で確かめる

- 日付: 2026-10-23
- 状態: 受理

## 背景

coupling の欄の単位の種類は流儀が決める（ADR-0033, 0076）。これまで、単位が流儀に合うか
（無次元の流儀に単位が添えてないか、有次元の流儀に単位があるか）は正準化
（`ModesSpec.to_system` の `coupling_to_canonical`）で確かめていた。フィールドの検証器からは
流儀が見えない、というのがその理由だった。

その結果、次のことが起きていた。

- 誤った入力でも `FCEnvelopeInput.from_obj` は通る。CLI は読み込みの直後に実効設定を
  書き出すので、通らない設定が `*_config.json` として残る。
- 正準化の位置からは単位がどこに書かれたか分からない。`modes.coupling_unit` に書いても
  CSV の列に添えても、報告は `modes.rows[0]` を指していた。
- 雛形の CSV の例（流儀 g に `["coupling", "cm^-1"]`）のような誤りが、読み込みのテストでは
  見つからなかった。

## 決定

- 噛み合わせは、流儀の見える `ModesSpec` の検証器で確かめる。
  - 無次元の流儀に添えた単位は、単位を正式形へ置き換えるのと同じ `_read_rows`（before）が、
    書いた位置（`modes.coupling_unit` / `modes.rows[i].coupling` / `modes.csv.columns`）を
    添えて `InvalidInputError` にする。
  - 有次元の流儀での単位の書き忘れは、表の既定と各値の単位が揃ってから判定できるので、
    after の検証器が `UnsupportedUnitError` にする。どの値にも単位が無ければ
    `modes.coupling_unit` を、一部の値にだけ無ければその最初の行を指す。
- 例外の型と文言の本体は `CouplingConvention.check_coupling_unit` のものをそのまま使う。
  正準化での検査も残す（`coupling_to_canonical` は係数を引くのに単位の妥当性を要するため）。
  検証を通った入力では、そこで落ちることはもうない。
- 報告に載せる単位は入力ファイルの書き方（`"eV"` / `[2.0, "eV"]`）で出す
  （`units.format_unit`）。

## 影響

- 読み込みが通った `FCEnvelopeInput` は、coupling の単位が流儀に合っていることが保証される。
- 流儀の名前が未知のときは噛み合わせを確かめない。名前の誤りが先に報告される。
