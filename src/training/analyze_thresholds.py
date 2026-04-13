from pathlib import Path
import json
import sys

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import (
    FEATURE_ORDER,
    MODEL_REPORTS_DIR,
    build_candidate_pipelines,
    load_model_config,
    load_training_data,
    split_temporal_training_data,
)


OUTPUT_PATH = MODEL_REPORTS_DIR / "threshold_analysis.json"
THRESHOLDS = [round(value, 2) for value in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]]


def main() -> None:
    model_config = load_model_config()
    champion_model_name = model_config["champion_model"]
    df = load_training_data()
    _, _, X_train, X_validation, y_train, y_validation = split_temporal_training_data(df)

    pipeline = build_candidate_pipelines()[champion_model_name]
    pipeline.fit(X_train, y_train)

    features = X_validation[FEATURE_ORDER].copy()
    probabilities = pipeline.predict_proba(features)[:, 1]

    results = []
    for threshold in THRESHOLDS:
        predictions = (probabilities >= threshold).astype(int)
        results.append(
            {
                "threshold": threshold,
                "accuracy": accuracy_score(y_validation, predictions),
                "precision": precision_score(y_validation, predictions, zero_division=0),
                "recall": recall_score(y_validation, predictions, zero_division=0),
                "f1": f1_score(y_validation, predictions, zero_division=0),
            }
        )

    MODEL_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))

    print("Threshold analysis for champion model using temporal validation\n")
    print(f"Champion model: {champion_model_name}")
    print("Validation setup: train on 2013B/2013J, validate on 2014B/2014J\n")
    for result in results:
        print(f"Threshold: {result['threshold']:.2f}")
        print(f"- accuracy: {result['accuracy']:.4f}")
        print(f"- precision: {result['precision']:.4f}")
        print(f"- recall: {result['recall']:.4f}")
        print(f"- f1: {result['f1']:.4f}")
        print()

    best_f1 = max(results, key=lambda item: item["f1"])
    best_recall = max(results, key=lambda item: item["recall"])

    print(f"Best threshold by F1: {best_f1['threshold']:.2f}")
    print(f"Best threshold by Recall: {best_recall['threshold']:.2f}")
    print(f"\nSaved threshold analysis to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
