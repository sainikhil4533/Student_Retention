from pathlib import Path
import json

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "training_dataset.csv"
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_ARTIFACTS_DIR = MODELS_DIR / "artifacts"
MODEL_METADATA_DIR = MODELS_DIR / "metadata"
MODEL_REPORTS_DIR = MODELS_DIR / "reports"
MODEL_CONFIG_PATH = MODEL_METADATA_DIR / "model_config.json"

CATEGORICAL_FEATURES = [
    "gender",
    "highest_education",
    "age_band",
    "disability_status",
]

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

FEATURE_ORDER = CATEGORICAL_FEATURES + NUMERICAL_FEATURES
TARGET_COLUMN = "risk_label"
RANDOM_STATE = 42
PRESENTATION_ORDER = {
    "2013B": 1,
    "2013J": 2,
    "2014B": 3,
    "2014J": 4,
}


def load_training_data() -> pd.DataFrame:
    return pd.read_csv(PROCESSED_DATA_PATH)


def load_model_config() -> dict:
    return json.loads(MODEL_CONFIG_PATH.read_text())


def build_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    numerical_steps = [("imputer", SimpleImputer(strategy="constant", fill_value=0))]
    if scale_numeric:
        numerical_steps.append(("scaler", StandardScaler()))

    numerical_pipeline = Pipeline(steps=numerical_steps)

    return ColumnTransformer(
        transformers=[
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
            ("numerical", numerical_pipeline, NUMERICAL_FEATURES),
        ]
    )


def build_candidate_pipelines() -> dict[str, Pipeline]:
    return {
        "logistic_regression": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=True)),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=200,
                        random_state=RANDOM_STATE,
                        class_weight="balanced",
                        n_jobs=1,
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    GradientBoostingClassifier(
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
    }
def split_temporal_training_data(df: pd.DataFrame):
    temporal_df = df.copy()
    temporal_df["presentation_rank"] = temporal_df["code_presentation"].map(PRESENTATION_ORDER)
    temporal_df = temporal_df.dropna(subset=["presentation_rank"]).sort_values(
        ["presentation_rank", "code_module", "id_student"]
    )

    train_df = temporal_df[temporal_df["presentation_rank"] <= 2].copy()
    validation_df = temporal_df[temporal_df["presentation_rank"] >= 3].copy()

    X_train = train_df[FEATURE_ORDER].copy()
    y_train = train_df[TARGET_COLUMN].copy()
    X_validation = validation_df[FEATURE_ORDER].copy()
    y_validation = validation_df[TARGET_COLUMN].copy()

    return train_df, validation_df, X_train, X_validation, y_train, y_validation
