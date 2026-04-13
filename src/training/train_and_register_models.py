from pathlib import Path
import sys
import json

import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import (
    CATEGORICAL_FEATURES,
    FEATURE_ORDER,
    MODEL_ARTIFACTS_DIR,
    MODEL_METADATA_DIR,
    NUMERICAL_FEATURES,
    PROCESSED_DATA_PATH,
    TARGET_COLUMN,
    build_candidate_pipelines,
    load_model_config,
    load_training_data,
)


REGISTRY_OUTPUT_PATH = MODEL_METADATA_DIR / "model_registry.json"


def main() -> None:
    model_config = load_model_config()
    champion_model_name = model_config["champion_model"]
    df = load_training_data()
    X_full = df[FEATURE_ORDER].copy()
    y_full = df[TARGET_COLUMN].copy()

    MODEL_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    model_registry = []

    for model_name, pipeline in build_candidate_pipelines().items():
        pipeline.fit(X_full, y_full)

        artifact = {
            "model_name": model_name,
            "pipeline": pipeline,
            "feature_order": FEATURE_ORDER,
            "categorical_features": CATEGORICAL_FEATURES,
            "numerical_features": NUMERICAL_FEATURES,
            "target_column": TARGET_COLUMN,
            "feature_alignment_verified": True,
            "training_scope": "full_dataset_after_temporal_validation",
        }

        model_output_path = MODEL_ARTIFACTS_DIR / f"{model_name}.joblib"
        metadata_output_path = MODEL_METADATA_DIR / f"{model_name}_metadata.json"

        joblib.dump(artifact, model_output_path)

        metadata = {
            "model_name": model_name,
            "training_dataset": str(PROCESSED_DATA_PATH),
            "feature_order": FEATURE_ORDER,
            "categorical_features": CATEGORICAL_FEATURES,
            "numerical_features": NUMERICAL_FEATURES,
            "target_column": TARGET_COLUMN,
            "training_scope": "full_dataset_after_temporal_validation",
            "full_training_rows": int(len(X_full)),
            "evaluation_type": model_config["evaluation_type"],
        }
        metadata_output_path.write_text(json.dumps(metadata, indent=2))

        model_registry.append(
            {
                "model_name": model_name,
                "artifact_path": str(model_output_path),
                "metadata_path": str(metadata_output_path),
                "is_champion": model_name == champion_model_name,
                "evaluation_type": model_config["evaluation_type"],
                "training_scope": "full_dataset_after_temporal_validation",
            }
        )

        print(f"Saved model artifact to: {model_output_path}")
        print(f"Saved metadata to: {metadata_output_path}")
        print("\nFeature order contract:")
        print(FEATURE_ORDER)
        print("\nTraining scope:")
        print("- full_dataset_after_temporal_validation")
        print(f"- evaluation_type: {model_config['evaluation_type']}")
        print("\n" + "-" * 80 + "\n")

    REGISTRY_OUTPUT_PATH.write_text(json.dumps(model_registry, indent=2))
    print(f"Saved model registry to: {REGISTRY_OUTPUT_PATH}")
    print(f"Champion model: {champion_model_name}")


if __name__ == "__main__":
    main()
