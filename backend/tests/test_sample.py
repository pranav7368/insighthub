"""Built-in sample dataset generator."""

from app.ingest.sample import build_sample_df


def test_sample_shape_and_columns():
    df = build_sample_df(months=12)
    assert len(df) == 12 * 4 * 3          # months × regions × products
    for col in ("date", "region", "product", "revenue", "profit", "units_sold"):
        assert col in df.columns
    assert df["revenue"].sum() > 0 and df["profit"].sum() > 0
    assert df["region"].nunique() == 4


def test_sample_is_deterministic():
    assert build_sample_df(seed=42).equals(build_sample_df(seed=42))
