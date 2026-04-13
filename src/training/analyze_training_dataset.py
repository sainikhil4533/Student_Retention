from pathlib import Path

import pandas as pd


PROCESSED_DATA_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "processed" / "training_dataset.csv"
)

CATEGORICAL_COLUMNS = [
    "gender",
    "highest_education",
    "age_band",
    "disability_status",
    "final_result",
]

NUMERICAL_COLUMNS = [
    "num_previous_attempts",
    "lms_clicks_7d",
    "lms_clicks_14d",
    "lms_clicks_30d",
    "lms_unique_resources_7d",
    "days_since_last_lms_activity",
    "lms_7d_vs_14d_percent_change",
    "engagement_acceleration",
    "assessment_submission_rate",
    "weighted_assessment_score",
    "late_submission_count",
    "total_assessments_completed",
    "assessment_score_trend",
    "risk_label",
]


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def main() -> None:
    df = pd.read_csv(PROCESSED_DATA_PATH)

    print_section("Training Dataset Overview")
    print(f"Path: {PROCESSED_DATA_PATH}")
    print(f"Rows: {len(df):,}")
    print(f"Columns: {len(df.columns)}")
    print(f"Column names: {list(df.columns)}")

    print_section("Missing Values")
    print(df.isna().sum().sort_values(ascending=False))

    print_section("Risk Label Distribution")
    print(df["risk_label"].value_counts(dropna=False))
    print("\nRisk label percentage:")
    print((df["risk_label"].value_counts(normalize=True) * 100).round(2))

    print_section("Categorical Feature Summary")
    for column in CATEGORICAL_COLUMNS:
        print(f"\nColumn: {column}")
        print(df[column].value_counts(dropna=False).head(10))

    print_section("Numerical Feature Summary")
    print(df[NUMERICAL_COLUMNS].describe().transpose())

    print_section("Preview")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
