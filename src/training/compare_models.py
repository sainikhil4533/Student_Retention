from pathlib import Path
import sys
import json

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import (
    MODEL_REPORTS_DIR,
    build_candidate_pipelines,
    load_training_data,
    split_temporal_training_data,
)


RESULTS_OUTPUT_PATH = MODEL_REPORTS_DIR / "model_comparison_results.json"


def evaluate_models() -> list[dict]:
    df = load_training_data()
    train_df, test_df, X_train, X_test, y_train, y_test = split_temporal_training_data(df)

    results = []
    candidate_pipelines = build_candidate_pipelines()

    for model_name, pipeline in candidate_pipelines.items():
        pipeline.fit(X_train, y_train)
        predictions = pipeline.predict(X_test)

        result = {
            "model_name": model_name,
            "accuracy": accuracy_score(y_test, predictions),
            "precision": precision_score(y_test, predictions, zero_division=0),
            "recall": recall_score(y_test, predictions, zero_division=0),
            "f1": f1_score(y_test, predictions, zero_division=0),
            "evaluation_type": "temporal_split",
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
        }
        results.append(result)

    results.sort(key=lambda item: item["f1"], reverse=True)
    return results


def main() -> None:
    MODEL_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    results = evaluate_models()
    RESULTS_OUTPUT_PATH.write_text(json.dumps(results, indent=2))

    print("Model comparison complete using temporal split.\n")
    print("Train presentations: 2013B, 2013J")
    print("Test presentations: 2014B, 2014J\n")
    for result in results:
        print(f"Model: {result['model_name']}")
        print(f"- accuracy: {result['accuracy']:.4f}")
        print(f"- precision: {result['precision']:.4f}")
        print(f"- recall: {result['recall']:.4f}")
        print(f"- f1: {result['f1']:.4f}")
        print()

    print(f"Saved comparison results to: {RESULTS_OUTPUT_PATH}")
    print(f"Best model by F1: {results[0]['model_name']}")


if __name__ == "__main__":
    main()
