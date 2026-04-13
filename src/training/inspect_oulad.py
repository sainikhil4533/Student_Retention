from pathlib import Path

import pandas as pd


RAW_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

FILES_TO_INSPECT = {
    "studentInfo.csv": [
        "id_student",
        "code_module",
        "code_presentation",
        "gender",
        "highest_education",
        "age_band",
        "num_of_prev_attempts",
        "disability",
        "final_result",
    ],
    "studentVle.csv": [
        "id_student",
        "code_module",
        "code_presentation",
        "id_site",
        "date",
        "sum_click",
    ],
    "vle.csv": [
        "id_site",
        "code_module",
        "code_presentation",
        "activity_type",
        "week_from",
        "week_to",
    ],
    "studentAssessment.csv": [
        "id_assessment",
        "id_student",
        "date_submitted",
        "is_banked",
        "score",
    ],
    "assessments.csv": [
        "code_module",
        "code_presentation",
        "id_assessment",
        "assessment_type",
        "date",
        "weight",
    ],
    "studentRegistration.csv": [
        "id_student",
        "code_module",
        "code_presentation",
        "date_registration",
        "date_unregistration",
    ],
    "courses.csv": [
        "code_module",
        "code_presentation",
        "module_presentation_length",
    ],
}


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def inspect_file(file_name: str, important_columns: list[str]) -> None:
    file_path = RAW_DATA_DIR / file_name
    df = pd.read_csv(file_path)

    print_section(f"Inspecting {file_name}")
    print(f"Path: {file_path}")
    print(f"Rows: {len(df):,}")
    print(f"Columns: {len(df.columns)}")
    print(f"Column names: {list(df.columns)}")

    available_columns = [column for column in important_columns if column in df.columns]
    if available_columns:
        print("\nMissing value summary for important columns:")
        print(df[available_columns].isna().sum().sort_values(ascending=False))

        print("\nSample values from important columns:")
        for column in available_columns:
            unique_values = df[column].dropna().astype(str).unique()[:5]
            print(f"- {column}: {list(unique_values)}")

    print("\nFirst 3 rows:")
    print(df.head(3).to_string(index=False))


def main() -> None:
    print_section("OULAD Dataset Inspection")
    print(f"Raw data directory: {RAW_DATA_DIR}")

    for file_name, important_columns in FILES_TO_INSPECT.items():
        inspect_file(file_name, important_columns)


if __name__ == "__main__":
    main()
