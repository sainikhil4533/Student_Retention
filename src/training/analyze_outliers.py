from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "training_dataset.csv"
OUTPUT_PATH = PROJECT_ROOT / "models" / "reports" / "outlier_analysis_report.txt"

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
]


def summarize_feature(series: pd.Series) -> list[str]:
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    outlier_mask = (series < lower_bound) | (series > upper_bound)
    outlier_count = int(outlier_mask.sum())
    outlier_percentage = (outlier_count / len(series)) * 100

    return [
        f"Feature: {series.name}",
        f"- min: {series.min():.4f}",
        f"- q1: {q1:.4f}",
        f"- median: {series.median():.4f}",
        f"- q3: {q3:.4f}",
        f"- max: {series.max():.4f}",
        f"- iqr: {iqr:.4f}",
        f"- lower_bound: {lower_bound:.4f}",
        f"- upper_bound: {upper_bound:.4f}",
        f"- outlier_count: {outlier_count}",
        f"- outlier_percentage: {outlier_percentage:.2f}%",
    ]


def main() -> None:
    df = pd.read_csv(DATASET_PATH)

    report_lines = []
    report_lines.append("Outlier Analysis Report")
    report_lines.append("=" * 80)

    for feature_name in NUMERICAL_FEATURES:
        report_lines.append("")
        report_lines.extend(summarize_feature(df[feature_name]))

    report_text = "\n".join(report_lines)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report_text)

    print(report_text)
    print(f"\nSaved outlier report to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
