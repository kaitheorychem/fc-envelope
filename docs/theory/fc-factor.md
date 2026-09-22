# FC因子

スペクトル全体を良い精度で計算するためには時間相関関数のフーリエ変換を用いて多数の振動モードを考慮することが重要であるが、定性的な考察や解析においては離散的なFC因子の内主要なもののみに絞って取得することも意義がある。

## 平行移動された調和振動子のFC因子
平行移動された二つの調和振動子があり、それらの変位が無次元化VCC$g$で特徴付けられる時、振動状態間のFC因子は平行移動演算子$U(g)$を使って次のようになる。

$$
\mathrm{FC}= |\braket{m|\exp(g(a^\dagger-a))|n}|^2
= |\braket{m|U(g)|n}|^2
$$

生成消滅演算子の平行移動はBCH公式で以下。

$$
U(g) aU^\dagger(g)=a + [g(a^\dagger -a) ,a ]+ \frac12 [g(a^\dagger -a) ,[g(a^\dagger -a) ,a ]] + \dots
=a-g
$$

$$
U(g) a^\dagger U^\dagger(g)=a^\dagger-g
$$

したがって最後の式を$Ua^\dagger=(a^\dagger-g)U$と変形し、m,nで挟むことで平行移動の行列要素同士の漸化式が得られる。

$$
\braket{m| U(g)a^\dagger |n}=\braket{m|a^\dagger U(g)|n}-g\braket{m|U(g)|n}
$$

$$
\sqrt{n+1}\braket{m|U(g)|n+1}=\sqrt{m}\braket{m-1|U(g)|n}-g\braket{m|U(g)|n}
$$

本プログラムでは以上の漸化式により求めた行列要素を二乗することでFC因子を計算する。

なお、漸化式により再帰的に$n$を増やしていく計算のための初期条件として次の値を用いる。

$$
\braket{m|U|0}=e^{-g^2/2}\braket{m|\exp(ga^\dagger)|0}
=e^{-g^2/2}\frac{g^m}{\sqrt{m!}}
$$

