# 時間領域からのフーリエ変換による計算

## 概要
FCエンベロープ$F(E)$は実用的には時間相関関数$\rho(t)$のフーリエ変換により計算される。$^1$

$$
F(E)=\frac{1}{2\pi} \int d\tau \rho(\tau) e^{iE\tau -\frac12\sigma^2 \tau^2}
$$

ただし$\tau=t/\hbar$、$\sigma$はスペクトルの幅を決めるパラメータである。

本プログラムの標準として調和振動子の時間相関関数を利用する。平行移動のみを行った調和振動子同士の時間相関関数は以下$^2$。エネルギーの原点がズレてるならその分位相がずれるので適宜補正する。

$$
\rho(\tau)=\prod_\alpha \exp(-g_\alpha^2(2n_\alpha+1)+g_\alpha^2(n_\alpha+1)\exp(i\hbar\omega_\alpha\tau) + g_\alpha^2n_\alpha\exp(-i\hbar\omega_\alpha\tau) )
$$

$\omega_\alpha$は基準振動$\alpha$の振動数、
$g_\alpha$は振動モード$\alpha$ごとに固有のパラメータ(無次元化振電相互作用定数)。$g$の与え方には定数倍程度異なるものがいくつかあるので内部で変換するようにする。

$n_\alpha$は振動モード$\alpha$のフォノンの占有数

$$
n_\alpha=\frac{1}{e^{\frac{\hbar\omega_\alpha}{kT}}-1}
$$

この数値計算コードでは、
量子化学計算で求めた$g_\alpha,\omega_\alpha$を入力として、指定したパラメータ$T,\sigma$におけるスペクトルを計算・可視化を行うことを目的とする。

1. R. Englman et al., Mol. Phys. 18, 145 (1970).
2. M. Lax, J. Chem. Phys. 20, 1752 (1952).

