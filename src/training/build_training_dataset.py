from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_PATH = PROCESSED_DATA_DIR / "training_dataset.csv"

GROUP_KEYS = ["code_module", "code_presentation", "id_student"]


def load_csv(file_name: str) -> pd.DataFrame:
    file_path = RAW_DATA_DIR / file_name
    return pd.read_csv(file_path)


def build_target(student_info: pd.DataFrame) -> pd.DataFrame:
    dataset = student_info.copy()

    # For the first version, we treat withdrawn and failed students as at-risk.
    dataset["risk_label"] = dataset["final_result"].isin(["Withdrawn", "Fail"]).astype(int)

    dataset = dataset.rename(
        columns={
            "num_of_prev_attempts": "num_previous_attempts",
            "disability": "disability_status",
        }
    )

    return dataset[
        GROUP_KEYS
        + [
            "gender",
            "highest_education",
            "age_band",
            "num_previous_attempts",
            "disability_status",
            "final_result",
            "risk_label",
        ]
    ]


def build_lms_features(student_vle: pd.DataFrame) -> pd.DataFrame:
    lms = student_vle.copy()
    lms["date"] = pd.to_numeric(lms["date"], errors="coerce")
    lms["sum_click"] = pd.to_numeric(lms["sum_click"], errors="coerce").fillna(0)
    lms = lms.dropna(subset=["date"])

    dataset_snapshot_day = lms["date"].max()

    latest_activity = (
        lms.groupby(GROUP_KEYS, as_index=False)["date"]
        .max()
        .rename(columns={"date": "last_lms_activity_day"})
    )
    latest_activity["days_since_last_lms_activity"] = (
        dataset_snapshot_day - latest_activity["last_lms_activity_day"]
    )

    clicks_7d = (
        lms.loc[lms["date"] >= dataset_snapshot_day - 6]
        .groupby(GROUP_KEYS, as_index=False)["sum_click"]
        .sum()
        .rename(columns={"sum_click": "lms_clicks_7d"})
    )

    clicks_14d = (
        lms.loc[lms["date"] >= dataset_snapshot_day - 13]
        .groupby(GROUP_KEYS, as_index=False)["sum_click"]
        .sum()
        .rename(columns={"sum_click": "lms_clicks_14d"})
    )

    clicks_30d = (
        lms.loc[lms["date"] >= dataset_snapshot_day - 29]
        .groupby(GROUP_KEYS, as_index=False)["sum_click"]
        .sum()
        .rename(columns={"sum_click": "lms_clicks_30d"})
    )

    unique_resources_7d = (
        lms.loc[lms["date"] >= dataset_snapshot_day - 6]
        .groupby(GROUP_KEYS, as_index=False)["id_site"]
        .nunique()
        .rename(columns={"id_site": "lms_unique_resources_7d"})
    )

    lms_features = latest_activity.merge(clicks_7d, on=GROUP_KEYS, how="left")
    lms_features = lms_features.merge(clicks_14d, on=GROUP_KEYS, how="left")
    lms_features = lms_features.merge(clicks_30d, on=GROUP_KEYS, how="left")
    lms_features = lms_features.merge(unique_resources_7d, on=GROUP_KEYS, how="left")

    lms_features = lms_features.fillna(
        {
            "lms_clicks_7d": 0,
            "lms_clicks_14d": 0,
            "lms_clicks_30d": 0,
            "lms_unique_resources_7d": 0,
        }
    )

    lms_features["prior_7d_clicks"] = (
        lms_features["lms_clicks_14d"] - lms_features["lms_clicks_7d"]
    ).clip(lower=0)

    lms_features["lms_7d_vs_14d_percent_change"] = np.where(
        lms_features["prior_7d_clicks"] > 0,
        (lms_features["lms_clicks_7d"] - lms_features["prior_7d_clicks"])
        / lms_features["prior_7d_clicks"],
        np.where(lms_features["lms_clicks_7d"] > 0, 1.0, 0.0),
    )

    lms_features["engagement_acceleration"] = (
        lms_features["lms_clicks_7d"] - lms_features["prior_7d_clicks"]
    )

    return lms_features[
        GROUP_KEYS
        + [
            "lms_clicks_7d",
            "lms_clicks_14d",
            "lms_clicks_30d",
            "lms_unique_resources_7d",
            "days_since_last_lms_activity",
            "lms_7d_vs_14d_percent_change",
            "engagement_acceleration",
        ]
    ]


def build_assessment_features(
    student_assessment: pd.DataFrame, assessments: pd.DataFrame
) -> pd.DataFrame:
    assessment_scores = student_assessment.copy()
    assessment_meta = assessments.copy()

    assessment_scores["date_submitted"] = pd.to_numeric(
        assessment_scores["date_submitted"], errors="coerce"
    )
    assessment_scores["score"] = pd.to_numeric(assessment_scores["score"], errors="coerce")

    assessment_meta["date"] = pd.to_numeric(assessment_meta["date"], errors="coerce")
    assessment_meta["weight"] = pd.to_numeric(assessment_meta["weight"], errors="coerce")

    merged = assessment_scores.merge(
        assessment_meta,
        on="id_assessment",
        how="left",
        suffixes=("", "_assessment"),
    )

    merged["weighted_score_component"] = (merged["score"].fillna(0) * merged["weight"].fillna(0)) / 100.0
    merged["is_late_submission"] = (
        merged["date_submitted"].notna()
        & merged["date"].notna()
        & (merged["date_submitted"] > merged["date"])
    ).astype(int)

    assessment_features = merged.groupby(GROUP_KEYS).agg(
        total_assessments_completed=("id_assessment", "count"),
        weighted_assessment_score=("weighted_score_component", "sum"),
        late_submission_count=("is_late_submission", "sum"),
        average_assessment_score=("score", "mean"),
        first_assessment_score=("score", "first"),
        last_assessment_score=("score", "last"),
    ).reset_index()

    total_available = (
        assessment_meta.groupby(["code_module", "code_presentation"])["id_assessment"]
        .nunique()
        .reset_index(name="total_available_assessments")
    )

    assessment_features = assessment_features.merge(
        total_available,
        on=["code_module", "code_presentation"],
        how="left",
    )

    assessment_features["assessment_submission_rate"] = np.where(
        assessment_features["total_available_assessments"] > 0,
        assessment_features["total_assessments_completed"]
        / assessment_features["total_available_assessments"],
        0.0,
    )

    assessment_features["assessment_score_trend"] = (
        assessment_features["last_assessment_score"].fillna(0)
        - assessment_features["first_assessment_score"].fillna(0)
    )

    return assessment_features[
        GROUP_KEYS
        + [
            "assessment_submission_rate",
            "weighted_assessment_score",
            "late_submission_count",
            "total_assessments_completed",
            "assessment_score_trend",
        ]
    ]


def main() -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    student_info = load_csv("studentInfo.csv")
    student_vle = load_csv("studentVle.csv")
    student_assessment = load_csv("studentAssessment.csv")
    assessments = load_csv("assessments.csv")

    base_dataset = build_target(student_info)
    lms_features = build_lms_features(student_vle)
    assessment_features = build_assessment_features(student_assessment, assessments)

    training_dataset = (
        base_dataset.merge(lms_features, on=GROUP_KEYS, how="left")
        .merge(assessment_features, on=GROUP_KEYS, how="left")
        .fillna(
            {
                "lms_clicks_7d": 0,
                "lms_clicks_14d": 0,
                "lms_clicks_30d": 0,
                "lms_unique_resources_7d": 0,
                "days_since_last_lms_activity": 0,
                "lms_7d_vs_14d_percent_change": 0,
                "engagement_acceleration": 0,
                "assessment_submission_rate": 0,
                "weighted_assessment_score": 0,
                "late_submission_count": 0,
                "total_assessments_completed": 0,
                "assessment_score_trend": 0,
            }
        )
    )

    training_dataset.to_csv(OUTPUT_PATH, index=False)

    print(f"Saved training dataset to: {OUTPUT_PATH}")
    print(f"Rows: {len(training_dataset):,}")
    print(f"Columns: {len(training_dataset.columns)}")
    print(f"Columns: {list(training_dataset.columns)}")
    print("\nRisk label distribution:")
    print(training_dataset["risk_label"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
