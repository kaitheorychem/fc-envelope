# 使い方

無次元化 VCC（g_α）・振動数（ω_α）・温度（T）から Franck-Condon スペクトルを計算する。
出力には 2 つの表現がある。

- **エンベロープ F(E)**（`run`）— 時間相関関数のフーリエ変換による連続スペクトル。多数のモードを
  含めた全体像を精度よく得たいとき。
- **線**（`lines`）— 個々の振電遷移の FC 因子と、その遷移エネルギーの一覧。
  どのモードが何量子ぶん効いているかを定性的に見たいとき。

両者は同じ物理量の別表現で、線を σ のガウシアンで畳んで足し上げるとエンベロープに一致する。
縦軸もそれに対応していて、エンベロープは**密度**（1/cm⁻¹、∫F dE = 1）、線は**重み**
（無次元、総和 1）である。同じ確率分布の連続版と離散版なので、どちらも `intensity` とは
呼ばない。

## エネルギーの向き

E = 0 が ZPL（zero-phonon line）で、E は ZPL からの符号付き変位 [cm⁻¹]。
振動量子を k 個生成するサイドバンドは **E = −k·ε_α**（負側）に立つ。
有限温度ではホットバンドにより正側にも重みが乗り、F(E) は左右非対称になる。

吸収／発光の区別は導入していない。F(E) はどちらでもない中立な量である。

## 入力ファイル

モードデータと計算条件を 1 ファイルに入れる。このファイル 1 つで計算が完全に再現できる。
書式は **TOML**（`.toml`）を基本とする。JSON（`.json`）でも同じように動くが、そちらの
出番は主に実効設定の読み返しである（下の「JSON で書く」）。

```toml
schema_version = 4
temperature = 300.0

# モード表。単位と流儀はこの表の列にだけ効く。
[modes]
frequency_unit = "cm^-1"
coupling_convention = "g"

# 1 モード = 1 つの [[modes.rows]]。並び順は結果に効かない。
[[modes.rows]]
frequency = 1200.0
coupling = 0.5

[[modes.rows]]
frequency = 450.0
coupling = 0.8

[broadening]
sigma = 150.0

[grid]
e_min = -4500.0
e_max = 1000.0

[grid.points]
de = 4.0

[selection]
min_weight = 0.0001
max_lines = 10000
# max_quanta は省略すると自動
```

そのまま動く例が [`examples/basic.toml`](examples/basic.toml) にある。

**トップレベルに単位の欄はない。** 既定の単位は、それを使うブロックがそれぞれ持つ。
モード表の列の単位は `[modes]`、σ は `[broadening]`、グリッドは `[grid]` に書く
（[単位](#単位)）。モードが多ければ、行を CSV から読める（[モードを CSV で渡す](#モードを-csv-で渡す)）。

### 雛形から書き始める

`fcenvelope template` が、この形の入力ファイルを項目ごとの短いコメント付きで書き出す。

```bash
uv run fcenvelope template                      # 端末に出して眺める
uv run fcenvelope template -o mymolecule.toml   # ファイルに書いて、そこから直す
```

雛形が答えるのは「入力ファイルに何が書けるか」だけで、条件の作り込みは入っていない。
値の意味・単位・流儀の選び方はこの文書の側にあり、雛形のコメントはそれを繰り返さない。

既にある `mymolecule.toml` は上書きせず `kept ...` と言って残す（本当に上書きするなら
`--force`）。コメントが雛形の中身なので書式は TOML だけで、`-o` に `.json` は渡せない。

| フィールド | 意味 | 制約 |
|---|---|---|
| `schema_version` | 入力ファイルの版 | `4` 固定 |
| `modes.coupling_convention` | `coupling` の列の流儀（下の流儀表） | 既定は `"g"` |
| `modes.frequency_unit` | `frequency` の列の既定の単位 | 下の単位表のいずれか（別名・倍率も可）、既定 `"cm^-1"` |
| `modes.coupling_unit` | `coupling` の列の既定の単位 | 有次元の流儀では必須、無次元の流儀では書けない |
| `modes.rows[].frequency` | ε_α | > 0 |
| `modes.rows[].coupling` | 流儀に従った値（キー名は流儀によらず `coupling`） | 流儀による |
| `modes.csv` | 行を CSV から読むときの参照 | `rows` とは排他。[モードを CSV で渡す](#モードを-csv-で渡す) |
| `temperature` | T [K] | ≥ 0（0 は許可） |
| `broadening.sigma` | 線形状の幅 σ | > 0。`run` では必須 |
| `broadening.unit` | σ の既定の単位 | 既定 `"cm^-1"` |
| `grid.e_min` / `e_max` | 出力窓 | `e_min` < `e_max`。`run` では必須 |
| `grid.unit` | `e_min` / `e_max` / `points.de` の既定の単位 | 既定 `"cm^-1"` |
| `grid.points.n` | 全域グリッドの点数 | 2 の冪。`de` とは排他 |
| `grid.points.de` | 出力グリッド間隔 | > 0。`n` とは排他 |
| `grid.points.shift` | 冪のずらし幅 | ≥ 0、既定 0。`de` と一緒のときだけ書ける |
| `selection.min_weight` | 保持する重みの下限 | 0 < x ≤ 1、既定 1e-4 |
| `selection.max_lines` | 保持・列挙する線数の上限 | ≥ 1、既定 10000 |
| `selection.max_quanta` | 1 モードあたりの振動量子数の上限 | ≥ 0、省略すると自動（既定）|

### どの副命令がどこを読むか

1 つのファイルを両方の副命令が使う。読む場所だけが違う。

| 位置 | 読む副命令 | 省いたら |
|---|---|---|
| `[modes]` / `temperature` | 両方 | エラー |
| `[broadening]` / `[grid]` | `run` だけ | `run` はエラー、`lines` は通る |
| `[selection]` | `lines` だけ | 既定値で埋まる |

片方しか使わないなら、読まれないブロックはブロックごと省ける。`lines` だけを回す入力に
使わないグリッドを書く必要はない（ADR-0075）。

```
$ fcenvelope run modes-only.toml
error: broadening: required by `fcenvelope run` (add a [broadening] block with sigma)
```

`[broadening]` と `[grid]` が省けても既定値では埋まらないのは、σ も E 窓も分子と目的ごとに
決まる量だからである。書き忘れが黙って通って、それらしい図が出るほうが困る。`[selection]`
が既定値で埋まるのは、あれが「どこで打ち切るか」のつまみで、分子によらない妥当な既定が
あるからである。

有次元の値（`modes.rows[].frequency` / `modes.rows[].coupling` / `broadening.sigma` /
`grid.e_min` / `e_max` / `grid.points.de`）は、`sigma = [0.0186, "eV"]` のように値の側に
単位を添えても書ける。[値に単位を添えて書く](#値に単位を添えて書く)を参照。

### グリッドの取り方

`e_min` / `e_max` は**出力窓**、つまりどこからどこまでを結果ファイルに書き出すかである。
実際に FFT を掛ける全域グリッドは別で、その取り方を `[grid.points]` に書く。FFT の基数は
2 の冪なので、点数はいつでも 2 の冪になる（ADR-0070）。

書き方は 2 つあり、どちらか一方だけを書く。

```toml
[grid.points]
n = 4096        # 点数を直接。2 の冪でなければエラー
```

点数を固定したいときはこちら。全域幅は窓ちょうど（`2 * max(|e_min|, |e_max|)`）になり、
ΔE = 全域幅 / n はたいてい端数になる。`de` の側は 2 の冪へ切り上げるぶん全域幅が窓より
広くなるので、同じ窓でも `n` の側のほうが端の折り返しは出やすい。気になるなら窓自体を
広げる。

```toml
[grid.points]
de = 5.0        # 刻みから。ΔE はちょうど 5.0 になる
shift = 1       # 任意。冪を 1 段上げ、ΔE = 2.5、点数は倍
```

横軸の刻みを丸くしたい、条件を振った複数の計算で刻みを揃えたいときはこちら。点数は
`2 * max(|e_min|, |e_max|) / de` 以上で最小の 2 の冪になるので、全域幅は窓より広くなる。

`shift` は**全域幅を保ったまま**点数を増やす。覆う範囲は変えずに刻みだけを細かくする
つまみなので、`edge_intensity_ratio`（端の折り返し）の警告には効かない。

実際に使われた点数と ΔE は、`run` の終了行（`N=...`）と結果ファイルの
`conditions.grid` / `diagnostics` に残る。

E 範囲の目安は `e_min ≲ −(λ + 5√Var)`、`e_max ≳ +5σ`。
ここで λ = Σ S_α ε_α、Var = Σ S_α ε_α²(2n_α+1) + σ²。

これは**窓**の目安である。端の折り返し（`edge_intensity_ratio`）が見ているのは窓では
なく**全域グリッドの端**で、全域幅は 2 の冪に切り上げた点数 × ΔE だから、窓を少し
広げても切り上げ先の冪が変わらないあいだは 1 も動かない。窓が目安を満たしているのに
警告が出るときは、窓を広げるより `de` を変えるほうが効くことがある。冒頭の入力ファイルの例（λ = 588）
では、窓 −4500〜1000 に対して `de = 5.0` だと全域幅が 10240 で
`edge_intensity_ratio` = 1.9e-4（警告が出る）、`de = 4.0` だと 16384 になって 9.4e-8 に落ちる。

### TOML で書く

TOML で書くときの決まりごとは 2 つだけである。

- モードは `[[modes.rows]]` を並べる。1 つの `[[modes.rows]]` が 1 モードで、`frequency` と
  `coupling` をその下に書く。1 行で済ませたいなら `[modes]` の中に
  `rows = [{ frequency = 1200.0, coupling = 0.5 }]` とも書ける。
- **TOML に `null` はない。** 「無し」にあたる `coupling_unit` と `selection.max_quanta`
  は、`null` と書くかわりに**その項目ごと省略する**。省略すれば既定値（どちらも「無し」）
  になる。すでに書いてある項目をその実行だけ「無し」に戻すなら
  `--override selection.max_quanta=null` を使う。

### JSON で書く

`.json` の入力ファイルも同じように読まれる。読んだ後は TOML と区別がないので、どちらで
書いても結果は変わらない（ADR-0069）。

JSON の主な出番は、実行のたびに書き出される**実効設定**（`*_config.json`）をそのまま
入力として与え直すことである。これは省略した項目が既定値で埋まった正準化済みのファイルで、
「何が使われたのか」を確かめたり、その条件をもう一度再現したりするのに使う（下の
「実際に使われた設定を見る」）。実効設定が TOML ではなく JSON なのは、`null` を書けるのが
JSON だけだからである。

書式は**拡張子だけ**で決まる。中身は見ないので、`.txt` のような知らない拡張子は
読む前にエラーになる。

### 流儀

`coupling` をどの量で書くかを `[modes]` の `coupling_convention` で選ぶ。量どうしの関係は
`docs/theory/vcc.md` にある。

| 流儀 | `coupling` が表すもの | S への変換 | 単位 |
|---|---|---|---|
| `"g"` | 無次元化振電相互作用定数 g | S = g² | 無次元 |
| `"delta"` | 無次元変位 Δ | S = Δ²/2 | 無次元 |
| `"huang_rhys"` | Huang-Rhys 因子 S | そのまま | 無次元 |
| `"lambda"` | 再配列エネルギー λ_α | S = λ_α/ε_α | エネルギー |
| `"vcc"` | 振電相互作用定数 V_α | S = V_α²/(2ε_α³) | 振電相互作用定数 |

無次元の流儀（`"g"` / `"delta"` / `"huang_rhys"`）では `coupling_unit` を書いてはいけない。
`"lambda"` と `"vcc"` では必ず書く（値に添えてもよい）。

流儀 `"g"` / `"delta"` / `"vcc"` では S が 2 乗で決まるので `coupling` の符号は結果に効かない。
`"huang_rhys"` と `"lambda"` では負の値はエラーになる。

#### 振電相互作用定数 V を使う

V の単位は `"hartree/(bohr*sqrt(m_e))"` の 1 つだけで、質量重み付き基準座標を電子の質量で
測った原子単位である（ADR-0077）。別名 `"a.u."` もこれを指すので、V を `a.u.` で出す
プログラムの値はそのまま写せる。見出しに 10⁻⁴ a.u. のような倍率が付いていれば、倍率を
値と単位の間に数で写す（[別名と倍率](#別名と倍率)）。

```toml
[modes]
coupling_convention = "vcc"

[[modes.rows]]
frequency = 500.0
coupling = [-0.3, 1e-4, "a.u."]   # 出力の VCC 列と、見出しの 10^-4 a.u.
```

このモードは S = 0.0381、Δ = √(2S) = 0.2759 になる。V の欄にエネルギーの単位（`eV` など）を
書くと未知の単位として止まる。質量を amu で測った `a.u.` とは約 43 倍ずれる（S では約
1823 倍）ので、相手の出力がどちらかを確かめてから写すこと。

### 単位

エネルギーの単位は次の 6 つから選べる。省略するとすべて `"cm^-1"` として読まれるので、
単位を書いていない入力ファイルは今までどおりの意味で動く。

| 名前 | 備考 |
|---|---|
| `"cm^-1"` | 既定。内部・出力で使う単位でもある |
| `"eV"` | |
| `"hartree"` | 原子単位 |
| `"THz"` | 振動数だが ε = hν としてエネルギーに読む |
| `"kJ/mol"` | |
| `"kcal/mol"` | 熱化学カロリー（1 cal = 4.184 J） |

波長（`nm`）は受け付けない。エネルギーとの関係が逆数なので、等間隔のエネルギーグリッドを
波長で指定できないためである。

**単位の軸は項目ごとに独立している。** 1 つの指定がファイル全体に効くのではなく、
`modes.frequency_unit` / `modes.coupling_unit` / `broadening.unit` / `grid.unit` の 4 つが
それぞれ別々の単位を取れる。どれも自分のブロックの値にだけ効き、トップレベルに単位の欄は
ない。振動数はほぼ常に cm⁻¹ で、`coupling` は値を出した外部プログラムの
都合で単位が決まり、σ とグリッドは利用者が計算窓として選ぶ量なので、揃うことを前提に
できないためである。

```toml
schema_version = 4
temperature = 300.0

[modes]
frequency_unit = "cm^-1"
coupling_convention = "lambda"
coupling_unit = "eV"

[[modes.rows]]
frequency = 1200.0
coupling = 0.037

[broadening]
sigma = 0.0186
unit = "eV"

[grid]
e_min = -4500.0
e_max = 1000.0
unit = "cm^-1"

[grid.points]
de = 4.0
```

この例では振動数を cm⁻¹、λ と σ を eV、グリッドを cm⁻¹ で書いている。結果は単位の
書き方によらず同じで、出力ファイルの中身は常に cm⁻¹ である。

そのまま動く例が [`examples/sigma-in-ev.toml`](examples/sigma-in-ev.toml) にある。同じ
内容を JSON で書いたものが [`examples/sigma-in-ev.json`](examples/sigma-in-ev.json) に
並べてあり、両者が同じ実効設定になることはテストで見ている。

```bash
uv run fcenvelope run docs/readme/examples/sigma-in-ev.toml -o result.json
```

描画の横軸は当面 cm⁻¹ 固定で、この 4 つの軸とは別である。

#### 別名と倍率

単位の名前には、上の表の**正式名**のほかに**別名**が使える。今ある別名は `"a.u."` だけで、
どの欄に書いたかで意味が決まる。エネルギーの欄（`modes.frequency_unit` / `broadening.unit` /
`grid.unit` と、流儀 `"lambda"` の coupling）では `"hartree"`、流儀 `"vcc"` の coupling では
`"hartree/(bohr*sqrt(m_e))"` になる。

**倍率**は名前と組にして配列に数で書き、値全体をその数倍して読む（ADR-0078）。単位の欄では
`[倍率, "単位"]`、値に添えるときは `[値, 倍率, "単位"]` である。倍率は正の数に限り、`1e-3`
とも `0.001` とも書ける。

```toml
[broadening]
sigma = [18.6, 1e-3, "eV"]        # meV で書く

[grid]
unit = [1e-3, "eV"]               # 窓とグリッド間隔をまとめて meV で
```

`"10^-3 eV"` のように倍率を文字列の中に書いても切り出さない。全体が 1 つの名前として読まれて
未知の単位で止まる。実効設定には別名を正式名に置き換えた**正式形**が出る
（`[1e-4, "a.u."]` → V の欄なら `[0.0001, "hartree/(bohr*sqrt(m_e))"]`）。

#### 値に単位を添えて書く

有次元の値は `[値, "単位"]` の組でも書ける。単位がその値のすぐ隣にあるので、ブロックを
見に行かなくても何の単位で書いたのか分かる。

```toml
[broadening]
sigma = [0.0186, "eV"]      # unit = "eV" の行を別に書くのと同じ
```

書き方は次の 3 つで、どれも同じ量を表す。

| 書き方 | 意味 |
|---|---|
| `sigma = 150.0` | 既定の単位（ブロックの `unit`、省略時は `"cm^-1"`） |
| `sigma = [150.0]` | 同上 |
| `sigma = [0.0186, "eV"]` | 添えた単位で読む |
| `sigma = [18.6, 0.001, "eV"]` | 倍率つきの単位で読む（[別名と倍率](#別名と倍率)） |

組を書けるのは有次元の値、すなわち `modes.rows[].frequency` / `modes.rows[].coupling` /
`broadening.sigma` / `grid.e_min` / `grid.e_max` / `grid.points.de` の 6 つである。
無次元の値（`grid.points.n` / `shift` / `selection` のつまみ）には書けない。温度は K
固定なので、これにも書けない。

上の 4 つの単位フィールドは**既定**として残っている。値に単位を添えればそちらが勝ち、
添えなければ既定で読む。`grid` のように 3 つの値が同じ単位を共有するブロックは、
`unit` を 1 回書くほうが短い。

```toml
[[modes.rows]]
frequency = [0.05579, "eV"]   # このモードだけ eV
coupling = 0.8

[broadening]
sigma = [0.0186, "eV"]        # σ ひとつのために unit の行を足さずに済む

[grid]
unit = "eV"                   # e_min / e_max / points.de をまとめて eV
e_min = -0.5579
e_max = 0.124
```

そのまま動く例が [`examples/units-on-values.toml`](examples/units-on-values.toml) にある。

`--override` の値も同じ組で渡せる（値は書式によらず JSON として読まれる）。

```bash
uv run fcenvelope run mymolecule.toml --override 'broadening.sigma=[0.0186, "eV"]'
```

CSV から読むモードにも、列ごとに同じ組の形で単位を添えられる（次の節）。

### モードを CSV で渡す

モード数が多い場合や外部プログラムの出力を使う場合は、行を CSV から読める。`[modes]` の
中に、`[[modes.rows]]` の並びの代わりに `csv` を 1 行書く。

```toml
schema_version = 4
temperature = 300.0

[modes]
coupling_convention = "g"
csv = { path = "modes.csv", columns = [["frequency", "eV"], "coupling"] }

[broadening]
sigma = 150.0

[grid]
e_min = -4500.0
e_max = 1000.0

[grid.points]
de = 4.0
```

```csv
0.14878,0.5
0.05579,0.8
```

CSV には数だけを書き、**ファイル名・列の並び・単位は入力ファイルの側に書く**。

| キー | 意味 | 省略したとき |
|---|---|---|
| `path` | CSV のファイル名。相対パスは**入力ファイルの場所**が基準 | 省略できない |
| `columns` | 列の並び。各列は列名か、列名に単位を添えた組 | `["frequency", "coupling"]` |

列の単位の書き方は、値に単位を添える書き方（[値に単位を添えて書く](#値に単位を添えて書く)）の
値の位置に列名を入れたものである。

| 書き方 | その列の値の読み方 |
|---|---|
| `"frequency"` | `[modes]` の既定の単位（`frequency_unit`、省略時は `"cm^-1"`） |
| `["frequency", "eV"]` | eV |
| `["frequency", 1e-3, "eV"]` | meV（[別名と倍率](#別名と倍率)） |
| `["coupling", 1e-4, "a.u."]` | 流儀 `vcc` なら 10⁻⁴ a.u. の V |

列に添えた単位は、その列のすべての値に `[値, "単位"]` と添えたのと同じである。単位を
添えない列は、行を直接書いたときと同じく `[modes]` の既定の単位で読む。したがって
既定の単位のままなら `columns = ["frequency", "coupling"]` と名前だけで書け、この並びなら
`columns` ごと省ける。

```toml
[modes]
coupling_convention = "vcc"
coupling_unit = [1e-4, "a.u."]                     # coupling の列の既定
csv = { path = "modes.csv", columns = ["coupling", "frequency"] }   # 並びだけ変える
```

そのまま動く例が [`examples/modes-from-csv.toml`](examples/modes-from-csv.toml) にあり、
[`examples/basic.toml`](examples/basic.toml) と同じ系を指していることはテストで見ている。

- `csv` と `[[modes.rows]]` はどちらか一方だけを書く。
- `columns` には `frequency` と `coupling` をちょうど 1 回ずつ並べる。ほかの列は置けない。
- ヘッダ行は省略できる。ヘッダを書いて `columns` を省くと、ヘッダの並びで読む。ヘッダと
  `columns` の両方を書くなら並びを揃える。食い違うとどちらを信じるか決められないので止まる。
- 書式は CSV の標準（RFC 4180）に従い、区切りはカンマのみ。RFC 4180 にはコメントの規定が
  ないため、コメント行は書けない。空行もエラー（ファイル末尾の改行 1 つは可）。
- 行の順序は計算結果に影響しない。縮重モードは同じ値の行を複数書く。
- **構造の誤り**（列数違い、数値として読めない、空行、引用の誤りなど）は `modes.csv:3: ...`
  のように行番号付きで報告される。**値の範囲**（ε ≤ 0 など）は流儀と単位を消費した後で
  判定するので、位置は `modes.rows[2]` のようにモードの番号で報告される。
- 実効設定と結果 JSON にはモードの値そのものが埋め込まれる（列の単位は各値に添えた形に
  なる）ので、CSV が後で変わっても再現できる。

## CLI

```bash
# 入力ファイルの雛形を書き出す（コメント付き。既にあるファイルは残す）
uv run fcenvelope template -o mymolecule.toml

# 計算して結果 JSON を書き出す。実効設定と作図スクリプトも一緒に出る
uv run fcenvelope run mymolecule.toml
#   -> mymolecule_envelope.json          計算結果
#   -> mymolecule_envelope_config.json   この実行で実際に使われた設定
#   -> mymolecule_envelope_plot.py       作図スクリプト

# 図を作る。ここを何度でも繰り返す（次の節を参照）
uv run python mymolecule_envelope_plot.py

# 名前を決めるなら -o
uv run fcenvelope run mymolecule.toml -o result.json

# 条件だけ振る（modes は上書きできない。値は入力ファイルと同じ単位で読む）
uv run fcenvelope run mymolecule.toml -o result_0K.json --override temperature=0

# 離散 FC 因子の一覧を書き出す
uv run fcenvelope lines mymolecule.toml -o lines.json --override selection.min_weight=1e-5

# 2 つの結果を 1 枚に重ねる作図スクリプトを作る（与える順序は問わない）
uv run fcenvelope script result.json lines.json -o overlay_plot.py

# 名前を変えながら掃引するときは作図スクリプトを作らせない
uv run fcenvelope run mymolecule.toml -o T100.json --override temperature=100 --no-script

# 版を表示して終了する
uv run fcenvelope --version

# 節目のログをファイルに残す（どの副命令でも使える）
uv run fcenvelope run mymolecule.toml --log run.log
```

終了コードは 正常 `0` / 入力・計算エラー `1` / 使用法エラー `2`。

### 出力の名前

`-o` を省くと、**入力ファイルの拡張子を除いた部分**に種類の名前を付けたものが、
**入力ファイルの隣**に出る。

| 呼び出し | 結果 | 実効設定 | 作図スクリプト |
|---|---|---|---|
| `fcenvelope run mymolecule.toml` | `mymolecule_envelope.json` | `mymolecule_envelope_config.json` | `mymolecule_envelope_plot.py` |
| `fcenvelope lines mymolecule.toml` | `mymolecule_lines.json` | `mymolecule_lines_config.json` | `mymolecule_lines_plot.py` |

`_envelope` / `_lines` が付くので、既定の出力が入力ファイルを潰すことはなく、同じ入力に
`run` と `lines` を当てても衝突しない。結果と実効設定は計算のたびに上書きされ、手で直す
作図スクリプトだけが残る。名前を変えながら掃引するときは今までどおり `-o` を書く。

### 条件を差し替える

入力ファイルの項目を差し替えるつまみは `--override KEY=VALUE` 1 つで、何度でも書ける。
キーは**入力ファイル中の項目の位置**そのもので、入れ子はドットで繋ぐ。

```bash
uv run fcenvelope run mymolecule.toml --override temperature=0 --override grid.points.de=2.5
uv run fcenvelope lines mymolecule.toml --override selection.max_quanta=null
```

- 値は**入力ファイルの書式によらず** JSON として読む。`null` も数も文字列（`eV` など）も
  同じ規則で通る。入力が TOML でも `--override selection.max_quanta=null` と書けるのは
  このためで、TOML では書けない「無し」を渡せる唯一の口である。
- 値は**入力ファイルと同じ単位・流儀**で読む。σ を eV で書いたファイルなら
  `--override broadening.sigma=0.02` も eV である。
- `modes` とその下（流儀・列の単位を含む）は上書きできない。どの分子を計算したかが履歴に
  残らなくなるため。
- 知らないキーはエラーになる。`grid.points.dee=4` は黙って無視されず、その場で止まる。

### 実際に使われた設定を見る

`run` と `lines` は、入力を読んで上書きを当てた直後、**計算を始める前**に、その実行で
実際に使われる設定を書き出す。上書き後の値も、書かなかったので既定値になった項目も、
ここを見れば分かる。

```bash
uv run fcenvelope run mymolecule.toml --override temperature=77
cat mymolecule_envelope_config.json   # -> "temperature": 77.0, "selection": { ... 既定値 ... }
```

書き出しは入力ファイルと同じ単位・流儀のままなので、手元の入力ファイルと突き合わせられる。
ただし別名で書いた単位は正式名に置き換わる（`"a.u."` → `"hartree"` など）。量としては同じ
値なので、そのまま入力に戻せば同じ計算になる。
`csv = { path = "modes.csv" }` で読んだモードは行に展開されるため、このファイルだけで完結する。
**そのまま入力として与えれば同じ計算が再現できる。**

入力を TOML で書いても実効設定は JSON で出る。省略した項目が既定値で埋まっていることが
このファイルの取り柄で、「無し」という既定値（`coupling_unit` と `selection.max_quanta`）を
書けるのが JSON だけだからである。手で書き直す種類のファイルではないので、読みやすさより
埋めた結果がそのまま書けることを採る（ADR-0069）。

```bash
uv run fcenvelope run mymolecule_envelope_config.json -o again.json
```

計算の前に書くので、値の誤りで止まった実行でも「何が使われるはずだったか」は残る。
場所を変えるなら `--config FILE`、要らないなら `--no-config`。

**図のつまみは CLI にない。** 表題も色も軸の範囲も作図スクリプトの中にあり、調整は
そのファイルを直して行う。

## 図を仕上げる

`run` と `lines` は結果 JSON の隣に作図スクリプトを置く。図はそれを走らせて作る。

```bash
uv run fcenvelope run mymolecule.toml -o result.json   # 重いのはここだけ
uv run python result_plot.py                      # 端末に図が出る
vi result_plot.py                                 # 軸・色・注釈を直す
uv run python result_plot.py                      # すぐ出る
```

スクリプトは `json` と `matplotlib` だけで動き、`fcenvelope` を import しない。中身を
読めば何を描いているかが全部分かるし、matplotlib にできることは何でも書ける。

`uv run python` で起動しているのは、`uv sync` で入れた matplotlib がプロジェクトの
仮想環境の中にあるからである。matplotlib が入った環境が既に有効なら（`pip install` で
入れた場合や、`uv run` の中から呼ぶ場合）素の `python` でよい。

出力先は 2 つある。

- **画像ファイル**（`fcenvelope-result.png`）は毎回書かれる。書き出し先は先頭の
  `OUTPUT` にあり、引数でほかの結果を指したときはその結果の名前に追従する（下記）。
- **端末**には、標準出力が端末のときだけ図がそのまま出る（kitty graphics protocol）。
  パイプやリダイレクトのときは何も出ない。端末に出す図だけは窓の幅に合わせて描き直す
  ので、ファイルの `DPI` とは別に決まる。

よく触る設定はファイルの頭にまとまっている。

```python
FIGSIZE = (7.0, 4.2)
DPI = 150
TITLE = None
XLIM = None          # (-3000.0, 500.0) のように書ける
X_UNIT = "cm$^{-1}$"
X_SCALE = 1.0        # eV にするなら "eV", 1.0 / 8065.543937
```

図の中身は `draw(ax, data)` にある。2 本目を足すのもここを 1 行増やすだけである。

```python
draw(ax, load("result_100K.json", KIND), label="100 K", color="C3")
```

ここに書くファイル名は**スクリプトの隣**が基準である。`DATA` や `OUTPUT` と同じ基準
なので、どのディレクトリから起動しても同じ図が出る。

別のデータに同じ設定を当てるなら引数で渡す。条件を振った結果を同じ体裁で見るときに使う。
こちらの名前は、シェルで書くものなので**カレントディレクトリ**が基準である。

```bash
uv run python result_plot.py result_0K.json
#   -> fcenvelope-result_0K.png
```

**画像の名前は描いたデータに追従する。** 引数でほかの結果を指すと、その結果の隣に
`fcenvelope-<結果の名前>.png` が出る。見比べるために走らせるたびに前の図が消える、
ということにはならない。引数なしで走らせたときだけ `OUTPUT` に書くので、書き出し先を
手で決めたければ `OUTPUT` を書き替えればよい。

**計算をやり直しても作図スクリプトは上書きされない。** 調整した設定はそのまま残り、
新しいデータに当たる。

```bash
uv run fcenvelope run mymolecule.toml -o result.json --override broadening.sigma=80
#   -> result.json を更新、result_plot.py はそのまま（kept ... と出る）
uv run python result_plot.py
```

作り直したいときは `--force-script`、保存済みの結果から作り直すときは `script` を使う。

```bash
uv run fcenvelope run mymolecule.toml -o result.json --force-script
uv run fcenvelope script result.json -o result_plot.py --force
```

## 線

`docs/theory/fc-factor.md` の漸化式で FC 因子 |⟨m|U(g)|n⟩|² を求め、対応する遷移エネルギーと
一緒に並べる。エネルギーは E 軸の規約どおり **E = −Σ_α (m_α − n_α)·ε_α**。

入力ファイルは `run` と同じものをそのまま使う。読むのは `temperature` と `selection` だけで、
`broadening` と `grid` は使わない。

```bash
# FC 因子と遷移エネルギーを書き出し、重みの上位 10 本を表示する
uv run fcenvelope lines mymolecule.toml -o lines.json
uv run python lines_plot.py              # 棒スペクトルはこれで出る

# T = 0 で、より細かい閾値まで拾う
uv run fcenvelope lines mymolecule.toml -o lines_0K.json --override temperature=0 \
    --override selection.min_weight=1e-6

# 表示だけ増やす（--top 0 で表を出さない）
uv run fcenvelope lines mymolecule.toml -o lines.json --top 30
```

`--top` が決めるのは端末に出す**表**の行数だけで、書き出す線の本数ではない。

```
wrote lines.json (58 lines, captured=0.997261, <E>=-583.531 cm^-1, lambda=588 cm^-1)
     E / cm^-1            FC        weight  transition
             0      0.410656       0.36206  ZPL
          -450       0.26282      0.231718  #1:0->1
         -1200      0.102664     0.0905149  #0:0->1
          -900     0.0841023     0.0741498  #1:0->2
         -1650     0.0657049     0.0579296  #0:0->1, #1:0->1
           450       0.26282      0.026772  #1:1->0
          -450      0.243056     0.0247588  #1:1->2
         -2100     0.0210256     0.0185375  #0:0->1, #1:0->2
          -900      0.156139      0.015905  #1:1->3
         -1350     0.0179418     0.0158186  #1:0->3
  ... 48 more (see lines.json)
```

`#1:0->1` は「1 番目のモード（`modes` の並び順、0 始まり）が n = 0 から m = 1 へ」の意味。
量子数がすべて 0 の線は `ZPL`。線は**重みの降順**に並ぶので、主要なものから順に読めばよい。

### FC 因子と重み

| 値 | 意味 |
|---|---|
| `fc_factor` | FC 因子そのもの Π_α FC_{m_α n_α}（無次元）。熱占有を含まない |
| `weight` | 始状態の熱占有を掛けた重み Π_α P(n_α)·FC_{m_α n_α}。全遷移にわたる総和は 1 |

T = 0 では始状態が振動基底状態だけなので両者は一致する。有限温度ではホットバンド
（n_α > m_α）が正側に立ち、その `weight` は始状態の占有ぶんだけ小さくなる。

### どこまで返すか

`selection.min_weight`（既定 1e-4）以上の線を**すべて**返す。全遷移は無限個あるので閾値が要る。

- どれだけ拾えたかは `captured_weight`（拾った線の重みの総和）で分かる。1 に近いほど
  スペクトルの全体を見ていることになる。
- 閾値が高すぎて 1 本も残らない場合は、最大の線の重みを警告に載せるので、そこまで下げればよい。
- 熱的に活性なモードが多い系では重みが膨大な数の線に分散し、線での記述自体が意味を失う。
  その場合は `run`（エンベロープ）を使う。

## ライブラリとして使う

計算関数は系（分子に固有の情報）と条件を別々に受け取る。同じ系を条件だけ変えて
何度も計算するのが典型的な使い方だからである。

```python
from fcenvelope import (
    Broadening, EnergyGrid, FCEnvelopeInput, VibrationalMode, VibrationalSystem,
    compute_envelope, load_envelope, plot_envelope, save_envelope,
)

# 引数から直接
system = VibrationalSystem([VibrationalMode(frequency=1200.0, huang_rhys=0.25)])
result = compute_envelope(
    system,
    temperature=300.0,
    broadening=Broadening(sigma=150.0),
    grid=EnergyGrid.from_spacing(e_min=-4500.0, e_max=1000.0, de=4.0),
)

# 入力ファイルから（流儀と単位はここで消費される。modes.csv の参照もここで解決）
parsed = FCEnvelopeInput.from_path("mymolecule.toml")
result = compute_envelope(
    parsed.to_system(),
    temperature=parsed.to_temperature(),
    broadening=parsed.to_broadening(),
    grid=parsed.to_grid(),
)

save_envelope(result, "result.json")
result = load_envelope("result.json")

fig = plot_envelope(result, label="300 K")   # 保存は呼び出し側の責務
fig.savefig("spectrum.png", dpi=300)
```

値の型は自分の不変条件を自分で検証するので、ライブラリから直接呼んでも
入力ファイル経由と同じように止まる。

```python
from fcenvelope import Broadening, InvalidInputError

try:
    Broadening(sigma=-1.0)
except InvalidInputError as exc:
    print(exc)   # sigma must be positive (got -1.0)
```

線も同じ 4 関数の形をしている。つまみは `Selection` に束ねて渡す。

```python
from fcenvelope import Selection, compute_fc_lines, load_lines, plot_lines, save_lines

lines = compute_fc_lines(
    system, temperature=300.0, selection=Selection(min_weight=1e-5)
)
for line in lines.lines[:5]:
    labels = [f"#{t.mode_index}: {t.initial}->{t.final}" for t in line.transitions]
    print(f"{line.energy:9.1f} cm^-1  FC={line.fc_factor:.5f}  w={line.weight:.5f}  {labels}")

save_lines(lines, "lines.json")
lines = load_lines("lines.json")
plot_lines(lines).savefig("sticks.png", dpi=300)
```

`lines.energies` / `lines.fc_factors` / `lines.weights` で ndarray としても取れる。
再配列エネルギー λ は系から決まるので `lines.system.reorganization_energy` から取る。
理論文書の行列そのものが要る場合は `fc_factor_matrix(S, m_max, n_max)` を使う。

エンベロープと線を 1 枚に重ねるには `plot_overlay` を使う（CLI から作るときは
`fcenvelope script` が重ね描きの作図スクリプトを書き出す）。

```python
from fcenvelope import plot_overlay

plot_overlay(result, lines, title="300 K").savefig("overlay.png", dpi=300)
```

複数条件を 1 枚に重ねる場合は `ax` を渡す。

```python
import matplotlib.pyplot as plt

broadening = Broadening(sigma=150.0)
grid = EnergyGrid.from_spacing(e_min=-4500.0, e_max=1000.0, de=4.0)

fig, ax = plt.subplots()
for temperature in (0.0, 77.0, 300.0):
    result = compute_envelope(
        system, temperature=temperature, broadening=broadening, grid=grid
    )
    plot_envelope(result, ax=ax, label=f"{temperature:g} K")
```

## エンベロープと離散線を重ねる

`run` の曲線と `lines` の棒は同じ物理量の別表現で、E 軸の規約も共通しているので 1 枚に重ねられる。

```bash
uv run fcenvelope run    mymolecule.toml -o result.json
uv run fcenvelope lines  mymolecule.toml -o lines.json
uv run fcenvelope script result.json lines.json -o overlay_plot.py
uv run python overlay_plot.py                     # -> fcenvelope-overlay.png
```

引数でほかの結果を指したときは `fcenvelope-<エンベロープの名前>-overlay.png` になり、
同じ結果を単独で描いた図と混ざらない。

**縦軸は 1 本しかない。** 線の重み w は無次元だが、規格化した線形状の頂点値
L(0)（ガウス型なら 1/(σ√(2π))）を掛けて密度と同じ 1/cm⁻¹ に直してから描く。この高さは
「その線が F(E) に立てる山の高さそのもの」なので、棒と曲線の高さをそのまま比べてよい。

- 孤立した線では棒の先端が曲線の山にぴたりと一致する。
- σ の中に線が何本も密集するところでは曲線が棒より高くなる。これは縮尺の都合ではなく、
  その山が 1 本の遷移では説明できないことを意味する。

線形状は `result` 側の条件から取る（`lines` は線形状を持たない）。

線が密集して棒が潰れる場合は、作図スクリプトの `MAGNIFY` で棒だけを拡大できる。倍率は
凡例に `(×N)` と出るので、拡大したことが図から失われない。

```python
MAGNIFY = 5.0        # overlay_plot.py の頭にある
```

注意点が 2 つある。

- 横軸は `result` の E 窓に合わせるので、窓の外に立つ線は描かれない。落ちた本数は
  スクリプトが警告に出す。すべて見たいなら `run` の `grid.e_min` / `grid.e_max` を広げる。
- 2 つの結果の系か温度が食い違っていると警告が出る。棒と曲線の対応が
  成り立つのは同じ系・同じ温度で計算した場合だけなので、図には出すが鵜呑みにしない。

## 結果の中身

`EnvelopeResult` は配列（`energy` / `density`）に加えて、計算条件（`system` /
`temperature` / `broadening` / `grid`）・診断値・来歴（`provenance`）を持つ。
`save_envelope` はこれらをすべて 1 つの JSON に書くため、そのファイルだけから
`load_envelope` で完全に復元でき、後から信頼可否も判定できる。

`LinesResult` も同じ作りで、`lines`（各線のエネルギー・FC 因子・重み・量子数）に加えて
`system` / `temperature` / `selection` ・診断値・来歴を持つ。出力 JSON は
`kind` が `"fcenvelope.fc_lines"` になる点だけが異なり、`load_lines` で完全に復元できる。

結果クラスが持つのは**計算で決まったものだけ**である。再配列エネルギー λ は系から一意に
決まるので `result.system.reorganization_energy` から、単位はファイル形式の知識なので
出力 JSON の `energy_unit` / `density_unit` から得る。λ は出力 JSON の `derived` にも
書き出されるが、読み込み時は読み飛ばして系から計算し直す。

## 数値品質の見方

計算は常に完走し、品質は `result.diagnostics` に記録される。閾値を超えた項目は
`NumericalQualityWarning` として警告され、同じ文言が `diagnostics.messages` に残る。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `sigma_tau_max` | 小さい（< 6）と τ 窓の打ち切りによるリンギング | `de` を σ/2 より小さく（同じ窓で `n` や `shift` を上げても同じ） |
| `edge_intensity_ratio` | 大きい（> 1e-4）とエイリアシング | 全域グリッド `n_fft * de` を広く。窓を広げるか `de` を小さくして冪を上げる（`n` や `shift` では広がらない） |
| `window_captured_fraction` | 小さい（< 0.99）と窓がエンベロープを取りこぼしている | `e_min` / `e_max` を広く（こちらは窓そのもの） |
| `total_area` | 1 から外れるのは実装の誤り | — |
| `max_imaginary_ratio` | 大きいのは ρ の対称性の破れ（実装の誤り） | — |

`edge_intensity_ratio` は `total_area` では検出できない失敗（重みが折り返して
戻るため面積は 1 のまま）を捉える。両方を見ること。

端の折り返しと窓の取りこぼしは似た見た目で出るが、動かすつまみが違う。警告文は
全域グリッドと窓の値を両方並べて出すので（ADR-0071）、2 つが同じなら窓を広げれば
そのまま効き、離れていればその差ぶんは窓を広げても効かないことがその場で読める。

線（`compute_fc_lines`）の診断値は別の項目を持つ。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `captured_weight` | 小さい（< 0.9）と閾値が粗く、スペクトルの大半を取りこぼしている | `selection.min_weight` を下げる |
| `beam_truncated` | True なら `max_lines` で列挙を打ち切っており、閾値以上の線が欠けている | `selection.max_lines` を上げるか閾値を粗くする |
| `min_mode_completeness` | 1 から外れると振動梯子の打ち切り | `selection.max_quanta` を上げる |
| `recurrence_limited` | True なら漸化式の桁落ちを避けて始状態を打ち切っている | 閾値を粗くするか温度を下げる |
| `mean_energy` | ⟨E⟩。収束していれば −λ に一致する（記録のみ） | — |

## ログ

「どこまで進んだか」を後から読むための記録である。結果を信じてよいかを答えるのは
診断値（上の節）で、こちらが答えるのは**どこで止まったか**だけである。

```
2026-09-17 12:34:56,102 INFO fcenvelope.inputs: begin read mymolecule.toml
2026-09-17 12:34:56,104 INFO fcenvelope.inputs: end read mymolecule.toml (0.002 s)
2026-09-17 12:34:56,104 INFO fcenvelope.envelope: begin envelope: 2 modes, T=300 K, de=4
2026-09-17 12:34:56,131 INFO fcenvelope.envelope: end envelope: 2 modes, T=300 K, de=4 (0.027 s)
2026-09-17 12:34:56,131 INFO fcenvelope.envelope: envelope: 1376 points, N_fft=4096, area=1, captured=0.999013
2026-09-17 12:34:56,133 INFO fcenvelope.io: begin write result.json
2026-09-17 12:34:56,158 INFO fcenvelope.io: end write result.json (0.025 s)
2026-09-17 12:34:56,158 INFO fcenvelope.plotting: begin plot envelope (1376 points)
2026-09-17 12:34:56,377 INFO fcenvelope.plotting: end plot envelope (1376 points) (0.219 s)
2026-09-17 12:34:56,377 INFO fcenvelope.cli: begin write spectrum.png
2026-09-17 12:34:56,538 INFO fcenvelope.cli: end write spectrum.png (0.161 s)
```

記録するのは**節目**だけで、1 回の実行で数十行にしかならない。`begin` と `end` が対に
なっていて、例外で抜けた節目には `end` が出ない。**`begin` だけが残っている行が、止まった
場所である。** 完了までの所要時間は `end` の行に出る。

モードごと・線ごとの記録は取らない。モード数や線の本数が増えてもログの行数は変わらない。

書き出す条件は 2 つだけである。

| 状況 | ログファイル |
|---|---|
| `--log FILE` を指定した | 最初から `FILE` に書く |
| 指定せず、異常終了した | `-o` の拡張子を `.log` に替えた場所に、そこまでの記録を書く（場所は stderr に出る） |
| 指定せず、正常に終わった | **書かない**（ログのためにファイルに触れない） |

```bash
uv run fcenvelope run mymolecule.toml -o result.json --log run.log   # 常に残す
uv run fcenvelope run mymolecule.toml -o result.json                  # 失敗したときだけ result.log
```

異常終了には、入力・計算のエラーだけでなく、想定外のエラーと **Ctrl-C** も含まれる。
計算が返ってこないときに Ctrl-C で止めれば、最後の `begin` がどこで止まったかを指す。
使用法の誤り（オプションの綴り違いなど）では書かない。

ライブラリとして使う場合は `logging` の作法そのままで、`fcenvelope` ロガーにハンドラを
付ければよい。付けなければ何も出ない。

```python
import logging

logging.basicConfig(
    filename="run.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("fcenvelope").setLevel(logging.INFO)
```

画面に出る警告——品質の警告（`NumericalQualityWarning`）、重ね描きの系・温度の食い違い、
E 窓から外れて描かれなかった線——は、同じ文言が WARNING としてこのログにも残る。`warnings`
で潰していても記録のほうは残る。逆に、結果の要約（`wrote ...` や線の表）は画面に出すだけで
ログには入れない。**画面はいま見ている人へのメッセージ、ログは後から追う人のための記録**、
という使い分けである。
