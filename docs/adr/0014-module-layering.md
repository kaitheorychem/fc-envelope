# モジュールを責務別に分け、依存を一方通行に保つ

- 日付: 2026-07-25
- 状態: **破棄** — ADR-0041 が差し替える

`src/fcenvelope/` を責務別に分割し、依存を一方通行にして循環を作らない。主目的は **matplotlib を `plotting.py` に、typer を `cli.py` に閉じ込める**ことで、ライブラリとして使うときに描画・CLI の依存を引きずらないようにすること。

依存の向きは `errors → models → result → core → {io, plotting} → cli`。
