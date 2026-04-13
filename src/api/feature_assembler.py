class FeatureAssembler:
    @staticmethod
    def build_prediction_payload(
        demographics: dict,
        lms_summary: dict,
        erp_summary: dict,
    ) -> dict:
        return {
            "gender": demographics["gender"],
            "highest_education": demographics["highest_education"],
            "age_band": demographics["age_band"],
            "disability_status": demographics["disability_status"],
            "num_previous_attempts": demographics["num_previous_attempts"],
            "lms_clicks_7d": lms_summary["lms_clicks_7d"],
            "lms_clicks_14d": lms_summary["lms_clicks_14d"],
            "lms_clicks_30d": lms_summary["lms_clicks_30d"],
            "lms_unique_resources_7d": lms_summary["lms_unique_resources_7d"],
            "days_since_last_lms_activity": lms_summary["days_since_last_lms_activity"],
            "lms_7d_vs_14d_percent_change": lms_summary["lms_7d_vs_14d_percent_change"],
            "engagement_acceleration": lms_summary["engagement_acceleration"],
            "assessment_submission_rate": erp_summary["assessment_submission_rate"],
            "weighted_assessment_score": erp_summary["weighted_assessment_score"],
            "late_submission_count": erp_summary["late_submission_count"],
            "total_assessments_completed": erp_summary["total_assessments_completed"],
            "assessment_score_trend": erp_summary["assessment_score_trend"],
        }
