# 単位変換と流儀の追加 作業計画

入力フォーマットに単位を導入し、流儀 `delta` と `lambda` を足す。**この文書は実装者への
引き継ぎ用**である。決定そのものは `docs/adr/`、語彙は `CONTEXT.md`、現行の仕様は
`docs/dev/spec/interface.md` にある。

## 前提

- **抽象化リファクタリングで用意した足場の上に機能を載せる作業である。** 流儀の型
  （ADR-0033）、入力ファイルの型と計算用の値の型の分離（ADR-0045）、CLI の上書き経路
  （ADR-0050）はすべて実装済みで、そのまま使う。
- **単位の軸は項目ごとに独立**（ADR-0053）。全体で 1 つの `energy_unit` にはしない。
- **変換は入力ファイルの型の中だけで起こる**（ADR-0054）。`models.py` 以降は常に `cm^-1`
  で、計算・結果・描画は単位を知らないままにする。
- **既存の入力ファイルを壊さない。** 単位フィールドはすべて省略可で、既定は現行の `cm^-1`。
  `schema_version` は 2 に据え置く。

## 非目的

- **流儀 `vcc`（V）の実装**（ADR-0055）。相手プログラムの単位が判明してから着手する。
  `energy_power: float` で表せるかどうかもそのとき決める。
- **描画の横軸の単位**。当面 `cm^-1` 固定で据え置く。単位変換が入った後に決める。
- 出力ファイル形式の変更。入力エコーは常に正準形（ADR-0010）なので変更は生じない。
- 線形状の拡張（ADR-0038, 0039、提案のまま）。

---

## 目標の形

### 入力ファイル

```json
{
  "schema_version": 2,
  "frequency_unit": "cm^-1",
  "coupling_convention": "lambda",
  "coupling_unit": "eV",
  "modes": [ { "frequency": 1200.0, "coupling": 0.037 } ],
  "temperature": 300.0,
  "broadening": { "sigma": 0.0186, "unit": "eV" },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0, "unit": "cm^-1" },
  "selection": { "min_weight": 0.0001 }
}
```

- 単位フィールドは 4 つとも省略可。省略時はすべて `cm^-1`（`coupling_unit` は無次元の流儀
  なら省略必須、有次元の流儀なら指定必須）。
- `coupling_unit` の位置はトップレベル。モードごとではない。CSV 参照のときも JSON 側が
  担う（ADR-0019）。
- `broadening` と `grid` は別々に単位を持つ。

### `units.py`

```python
CANONICAL_ENERGY_UNIT = "cm^-1"
ENERGY_UNITS: dict[str, float]          # 名前 -> cm^-1 への換算係数。scipy.constants から導出
energy_conversion_factor(unit) -> float # 未知の単位は UnsupportedUnitError
CouplingConvention.to_huang_rhys(coupling, frequency)   # 引数は両方とも正準単位
COUPLING_CONVENTIONS = {g, delta, huang_rhys, lambda}   # vcc は保留
```

有次元の流儀の coupling は、換算係数を `energy_power` 乗して掛けてから変換式に入れる。

## 作業の段階

各段階の完了条件は **`uv run pytest` が緑になること**。段階をまたいで赤のまま進めない。

### 段階 0 — 流儀 `delta` の追加（ADR-0055）

`COUPLING_CONVENTIONS` に 1 エントリ足すだけ。無次元なので単位の話が入らず、既存の経路が
そのまま通ることを先に確かめる。

- テスト: S = Δ²/2。`Δ = √2·g` の関係から、同じ系を `g` と `delta` で書いて結果が一致すること
  （ADR-0015 の「解析的な恒等式から作る」に沿う）。

### 段階 1 — エネルギー単位の変換表（ADR-0054）

`units.py` に変換表と引き当て関数を足す。この段階では入力ファイルの型を触らず、`units.py`
単体で閉じてテストする。

- 対応単位は `cm^-1` / `eV` / `hartree` / `THz` / `kJ/mol` / `kcal/mol`。`nm` は入れない。
- 係数は `scipy.constants` から導出する。自前の数値定数表は持たない。
- `check_frequency_unit()` を「正準単位か検証する」から「換算係数を引く」へ差し替える
  （ADR-0002 が予定していた検証点 → 変換点の差し替え）。
- テスト: 往復（`cm^-1` → X → `cm^-1`）の一致、既知の値（1 eV = 8065.54 cm⁻¹ 程度）との照合、
  未知の単位が `UnsupportedUnitError` になること。

### 段階 2 — `frequency_unit` を実際に変換する（ADR-0053, 0054）

`FCEnvelopeInput` の検証器と `to_system()` を変換点に変える。既定値は `cm^-1` のままなので
既存の入力ファイルとテストは無変更で通るはずである。

- テスト: 同じ物理系を `cm^-1` と `eV` で書いた 2 つの入力から、同一の `VibrationalSystem`
  が得られること。

### 段階 3 — `broadening` と `grid` の単位（ADR-0053）

`BroadeningSpec` / `EnergyGridSpec` に単位フィールドを足し、`to_broadening()` / `to_grid()`
で消費する。`_Spec` は `extra="forbid"` なので、フィールドを足すまで未知キーは弾かれる。

- CLI の上書きは ADR-0050 の経路がそのまま効く（`model_dump` → 上書き → 再検証）。
  **`--sigma` を入力ファイルと同じ単位で読む**ことをテストで固定する。
- テスト: `eV` で書いた σ とグリッドが `cm^-1` の等価な入力と同じ結果を出すこと。
  `broadening` だけ `eV`、`grid` は `cm^-1` という混在が通ること（軸が独立であることの確認）。

### 段階 4 — `coupling_unit` と流儀 `lambda`（ADR-0055）

有次元の流儀を初めて通す段階。

- トップレベルに `coupling_unit` を足し、`to_system()` の `check_coupling_unit(None)` 決め打ち
  （現 `inputs.py`）を実際の値に差し替える。
- `LAMBDA = CouplingConvention(name="lambda", energy_power=1.0, converter=...)` を登録。
- 換算係数を `energy_power` 乗して coupling に掛けてから変換式へ渡す。
- テスト: S = λ/ε。`huang_rhys` で書いた系と、λ = S·ε を `eV` で書いた系が一致すること。
  無次元の流儀に `coupling_unit` を添えると `InvalidInputError`、有次元の流儀で省くと
  `UnsupportedUnitError` になること（`check_coupling_unit` の両方の枝）。

### 段階 5 — 文書の追随

- `docs/dev/spec/interface.md`: 「単位・規約」「単位と流儀」「ファイル形式（入力）」の表、
  および「将来の拡張のための足場」から済んだ行を落とす。
- `src/fcenvelope/units.py` の冒頭の表と `energy_power` の docstring から、「同じエネルギー
  単位に揃えれば打ち消し合う」の記述を外す（ADR-0053 の帰結）。
- `CONTEXT.md` の「流儀」「単位」の項、`README.md`、`docs/readme/usage.md`。
- ADR-0002 / 0003 / 0033 の状態欄に追跡先（ADR-0053〜0055）を書く。

## 検証

- **単位を変えても結果が変わらない**ことが、この作業全体の主な検証軸になる。同じ物理系を
  違う単位・違う流儀で書いた入力が、同一の `VibrationalSystem` と同一のスペクトルを出すこと。
- `data/` の既存入力がすべて無変更で通ること（上位互換の確認）。
- `load → save` でファイルが変化しないこと（ADR-0008）は出力側に変更がないため維持される。

## 保留事項

| 事項 | 待っているもの | 参照 |
|---|---|---|
| 流儀 `vcc`（V） | 相手プログラムが V をどの単位で出すかの調査。`energy_power: float` で表せるかもそこで決まる | ADR-0055 |
| 描画の横軸の単位 | 単位変換の完了。指定場所（CLI オプションか入力ファイルか）も未決 | ADR-0053 |
