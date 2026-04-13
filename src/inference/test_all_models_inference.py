from pathlib import Path
import json
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.predict_service import PredictionService
from src.modeling.common import MODEL_REPORTS_DIR

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "training_dataset.csv"
OUTPUT_PATH = MODEL_REPORTS_DIR / "inference_test_results.json"


def main() -> None:
    MODEL_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATASET_PATH)
    sample_row = df.iloc[[0]].copy()
    prediction_service = PredictionService()
    feature_payload = sample_row[prediction_service.feature_order].iloc[0].to_dict()

    prediction_results = prediction_service.predict_all_models(feature_payload)
    combined_results = [
        prediction_results["champion_prediction"],
        *prediction_results["challenger_predictions"],
    ]

    print("Inference test successful.\n")
    print("Sample student identifiers:")
    print(
        sample_row[
            [
                "code_module",
                "code_presentation",
                "id_student",
                "final_result",
                "risk_label",
            ]
        ].to_string(index=False)
    )

    for result in combined_results:
        print(f"\nModel: {result['model_name']}")
        print(f"- is_champion: {result['is_champion']}")
        print(f"- predicted_class: {result['predicted_class']}")
        print(f"- predicted_risk_probability: {result['predicted_risk_probability']:.4f}")

    OUTPUT_PATH.write_text(json.dumps(combined_results, indent=2))
    print(f"\nSaved inference test results to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
