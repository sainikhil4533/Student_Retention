from pathlib import Path
import json
import sys

import joblib
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import MODEL_METADATA_DIR


MODEL_CONFIG_PATH = MODEL_METADATA_DIR / "model_config.json"
MODEL_REGISTRY_PATH = MODEL_METADATA_DIR / "model_registry.json"


class PredictionService:
    def __init__(self) -> None:
        self.model_config = json.loads(MODEL_CONFIG_PATH.read_text())
        self.model_registry = json.loads(MODEL_REGISTRY_PATH.read_text())

        self.champion_entry = next(
            model for model in self.model_registry if model["is_champion"]
        )
        self.champion_artifact = joblib.load(self.champion_entry["artifact_path"])
        self.champion_pipeline = self.champion_artifact["pipeline"]
        self.feature_order = self.champion_artifact["feature_order"]
        self.threshold = float(self.model_config["threshold"])

    def validate_features(self, feature_payload: dict) -> pd.DataFrame:
        payload_columns = list(feature_payload.keys())
        expected_columns = list(self.feature_order)

        missing_columns = [column for column in expected_columns if column not in payload_columns]
        extra_columns = [column for column in payload_columns if column not in expected_columns]

        if missing_columns or extra_columns:
            raise ValueError(
                {
                    "missing_columns": missing_columns,
                    "extra_columns": extra_columns,
                    "expected_columns": expected_columns,
                }
            )

        features = pd.DataFrame([feature_payload])[expected_columns]
        assert list(features.columns) == expected_columns
        return features

    def predict_champion(self, feature_payload: dict) -> dict:
        features = self.validate_features(feature_payload)
        predicted_probability = float(self.champion_pipeline.predict_proba(features)[0][1])
        predicted_class = int(predicted_probability >= self.threshold)

        return {
            "champion_model": self.champion_entry["model_name"],
            "threshold": self.threshold,
            "predicted_class": predicted_class,
            "predicted_risk_probability": predicted_probability,
        }

    def predict_all_models(self, feature_payload: dict) -> dict:
        features = self.validate_features(feature_payload)

        challenger_predictions = []
        champion_prediction = None

        for model_entry in self.model_registry:
            artifact = joblib.load(model_entry["artifact_path"])
            pipeline = artifact["pipeline"]
            feature_order = artifact["feature_order"]

            model_features = features[feature_order].copy()
            assert list(model_features.columns) == feature_order

            predicted_probability = float(pipeline.predict_proba(model_features)[0][1])
            predicted_class = int(predicted_probability >= self.threshold)

            prediction = {
                "model_name": model_entry["model_name"],
                "is_champion": model_entry["is_champion"],
                "predicted_class": predicted_class,
                "predicted_risk_probability": predicted_probability,
            }

            if model_entry["is_champion"]:
                champion_prediction = prediction
            else:
                challenger_predictions.append(prediction)

        return {
            "champion_prediction": champion_prediction,
            "challenger_predictions": challenger_predictions,
        }

    def apply_finance_modifier(self, base_probability: float, finance_payload: dict | None) -> dict:
        if not finance_payload:
            return {
                "base_probability": base_probability,
                "finance_modifier": 0.0,
                "final_probability": base_probability,
            }

        modifier = float(finance_payload.get("modifier_candidate") or 0.0)
        modifier = max(0.0, min(modifier, 0.20))
        final_probability = min(base_probability + modifier, 1.0)

        return {
            "base_probability": base_probability,
            "finance_modifier": modifier,
            "final_probability": final_probability,
        }
