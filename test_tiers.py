from src.api.risk_classification import classify_risk_level
# Test with actual data probabilities
probs = [0.5976, 0.5474, 0.5168, 0.4983, 0.45, 0.40, 0.37]
for p in probs:
    print(f"{p:.4f} -> {classify_risk_level(p)}")
