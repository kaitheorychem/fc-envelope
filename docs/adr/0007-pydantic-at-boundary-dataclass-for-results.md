# 境界は pydantic、結果クラスは frozen dataclass にする

- 日付: 2026-07-25
- 状態: 受理

入力 JSON のパース・検証には pydantic v2 を使う。フィールドパス付きのエラーメッセージが自動生成され、typer とも相性が良いため。一方、ndarray を抱える結果クラスは frozen dataclass とする。pydantic の `arbitrary_types_allowed` の濁りと、大配列の検証コストを避けるため。
