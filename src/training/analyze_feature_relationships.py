from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "training_dataset.csv"
OUTPUT_PATH = PROJECT_ROOT / "models" / "reports" / "feature_relationships_report.txt"

NUMERICAL_FEATURES = [
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


def main() -> None:
    df = pd.read_csv(DATASET_PATH)
    correlation_matrix = df[NUMERICAL_FEATURES].corr(numeric_only=True)

    strong_pairs = []
    for left_index, left_column in enumerate(correlation_matrix.columns):
        for right_column in correlation_matrix.columns[left_index + 1 :]:
            correlation_value = correlation_matrix.loc[left_column, right_column]
            if abs(correlation_value) >= 0.6:
                strong_pairs.append((left_column, right_column, correlation_value))

    strong_pairs.sort(key=lambda item: abs(item[2]), reverse=True)

    report_lines = []
    report_lines.append("Feature Relationship Analysis")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append("Correlation matrix:")
    report_lines.append(correlation_matrix.round(4).to_string())
    report_lines.append("")
    report_lines.append("Strong correlation pairs (absolute correlation >= 0.60):")

    if strong_pairs:
        for left_column, right_column, correlation_value in strong_pairs:
            report_lines.append(
                f"- {left_column} <-> {right_column}: {correlation_value:.4f}"
            )
    else:
        report_lines.append("- No strong pairs found using the current threshold.")

    report_text = "\n".join(report_lines)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report_text)

    print(report_text)
    print(f"\nSaved feature relationship report to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
