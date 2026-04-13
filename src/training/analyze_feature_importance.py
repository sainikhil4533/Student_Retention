from pathlib import Path
import json
import sys

import joblib
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.common import MODEL_METADATA_DIR


REGISTRY_PATH = MODEL_METADATA_DIR / "model_registry.json"
OUTPUT_PATH = PROJECT_ROOT / "models" / "reports" / "feature_importance_report.txt"


def get_champion_artifact_path() -> Path:
    registry = json.loads(REGISTRY_PATH.read_text())
    champion_entry = next(item for item in registry if item["is_champion"])
    return Path(champion_entry["artifact_path"])


def extract_feature_names(artifact: dict) -> list[str]:
    preprocessor = artifact["pipeline"].named_steps["preprocessor"]
    return list(preprocessor.get_feature_names_out())


def main() -> None:
    artifact_path = get_champion_artifact_path()
    artifact = joblib.load(artifact_path)

    pipeline = artifact["pipeline"]
    model = pipeline.named_steps["model"]

    if not hasattr(model, "feature_importances_"):
        raise ValueError("Champion model does not expose feature_importances_.")

    feature_names = extract_feature_names(artifact)
    feature_importances = model.feature_importances_

    importance_df = pd.DataFrame(
        {
            "feature_name": feature_names,
            "importance": feature_importances,
        }
    ).sort_values("importance", ascending=False)

    report_lines = []
    report_lines.append("Feature Importance Report")
    report_lines.append("=" * 80)
    report_lines.append(f"Champion artifact: {artifact_path}")
    report_lines.append(f"Champion model: {artifact['model_name']}")
    report_lines.append("")
    report_lines.append("Top 20 feature importances:")

    for row in importance_df.head(20).itertuples(index=False):
        report_lines.append(f"- {row.feature_name}: {row.importance:.6f}")

    report_text = "\n".join(report_lines)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report_text)

    print(report_text)
    print(f"\nSaved feature importance report to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
