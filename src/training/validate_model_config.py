from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import MODEL_CONFIG_PATH, MODEL_REPORTS_DIR


MODEL_COMPARISON_PATH = MODEL_REPORTS_DIR / "model_comparison_results.json"
THRESHOLD_ANALYSIS_PATH = MODEL_REPORTS_DIR / "threshold_analysis.json"


def main() -> None:
    model_config = json.loads(MODEL_CONFIG_PATH.read_text())
    model_comparison = json.loads(MODEL_COMPARISON_PATH.read_text())
    threshold_analysis = json.loads(THRESHOLD_ANALYSIS_PATH.read_text())

    expected_champion_model = model_comparison[0]["model_name"]
    expected_threshold = max(threshold_analysis, key=lambda item: item["f1"])["threshold"]

    issues = []

    if model_config["champion_model"] != expected_champion_model:
        issues.append(
            f"champion_model mismatch: config={model_config['champion_model']} expected={expected_champion_model}"
        )

    if float(model_config["threshold"]) != float(expected_threshold):
        issues.append(
            f"threshold mismatch: config={model_config['threshold']} expected={expected_threshold}"
        )

    if model_config["evaluation_type"] != "temporal_split":
        issues.append(
            f"evaluation_type mismatch: config={model_config['evaluation_type']} expected=temporal_split"
        )

    if issues:
        print("Model config validation failed.\n")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("Model config validation passed.")
    print(f"- champion_model: {model_config['champion_model']}")
    print(f"- threshold: {model_config['threshold']}")
    print(f"- evaluation_type: {model_config['evaluation_type']}")


if __name__ == "__main__":
    main()
