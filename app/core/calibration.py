"""
Model calibration for scoring.
"""
import numpy as np
from typing import Dict, List, Tuple


class CalibrationEngine:
    """
    Calibrate model scores based on historical data.
    """

    def __init__(self):
        self.score_bins = [0, 20, 40, 60, 80, 100]
        self.calibration_cache: Dict[str, Dict] = {}

    def compute_calibration_curve(
        self,
        predicted_scores: List[float],
        actual_outcomes: List[float]
    ) -> Dict[str, List[float]]:
        """
        Compute calibration curve (reliability diagram).

        Args:
            predicted_scores: Model predicted scores (0-100)
            actual_outcomes: Actual outcomes (0 or 1 for binary)

        Returns:
            Dict with 'bin_centers', 'predicted', 'actual'
        """
        # Bin predictions
        bin_indices = np.digitize(predicted_scores, self.score_bins) - 1
        bin_indices = np.clip(bin_indices, 0, len(self.score_bins) - 2)

        bin_centers = []
        actual_probs = []
        predicted_probs = []

        for i in range(len(self.score_bins) - 1):
            mask = bin_indices == i
            if mask.sum() > 0:
                bin_centers.append((self.score_bins[i] + self.score_bins[i + 1]) / 2)
                actual_probs.append(np.mean([actual_outcomes[j] for j in range(len(actual_outcomes)) if mask[j]]))
                predicted_probs.append(np.mean([predicted_scores[j] for j in range(len(predicted_scores)) if mask[j]]))

        return {
            "bin_centers": bin_centers,
            "predicted": predicted_probs,
            "actual": actual_probs
        }

    def apply_calibration(
        self,
        score: float,
        calibration_params: Dict[str, float]
    ) -> float:
        """
        Apply calibration to a score.

        Args:
            score: Raw model score
            calibration_params: Dict with 'scale' and 'offset'

        Returns:
            Calibrated score
        """
        scale = calibration_params.get("scale", 1.0)
        offset = calibration_params.get("offset", 0.0)

        calibrated = score * scale + offset
        return max(0, min(100, calibrated))

    def compute_isotonic_calibration(
        self,
        predicted_scores: List[float],
        actual_outcomes: List[float]
    ) -> Tuple[Dict[str, float], callable]:
        """
        Compute isotonic regression calibration.

        Returns:
            (params, calibration_fn)
        """
        from sklearn.isotonic import IsotonicRegression

        # Prepare data
        X = np.array(predicted_scores).reshape(-1, 1)
        y = np.array(actual_outcomes)

        # Fit isotonic regression
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(X, y)

        # Get calibration function
        def calibrate(score: float) -> float:
            return float(ir.predict([[score]])[0])

        # Get parameters for caching
        params = {
            "type": "isotonic",
            "x_min": float(X.min()),
            "x_max": float(X.max())
        }

        return params, calibrate

    def compute_platt_calibration(
        self,
        predicted_scores: List[float],
        actual_outcomes: List[float]
    ) -> Tuple[Dict[str, float], callable]:
        """
        Compute Platt scaling (logistic regression) calibration.

        Returns:
            (params, calibration_fn)
        """
        from sklearn.linear_model import LogisticRegression
        import numpy as np

        X = np.array(predicted_scores).reshape(-1, 1)
        y = np.array(actual_outcomes)

        lr = LogisticRegression()
        lr.fit(X, y)

        # Get parameters
        params = {
            "type": "platt",
            "scale": float(lr.coef_[0][0]),
            "offset": float(lr.intercept_[0])
        }

        def calibrate(score: float) -> float:
            prob = lr.predict_proba([[score]])[0][1]
            return prob * 100

        return params, calibrate


# Global calibration engine
calibration_engine = CalibrationEngine()


# ==============================
# SIMPLE LINEAR CALIBRATION
# ==============================

class CalibrationLayer:
    """
    Simple linear calibration: calibrated = raw_score * alpha + bias
    Alpha и bias настраиваются по историческим данным.
    """

    def __init__(self, alpha: float = 0.92, bias: float = 3.4):
        self.alpha = alpha
        self.bias = bias

    def apply(self, raw_score: float) -> float:
        """Apply linear calibration to raw score."""
        calibrated = raw_score * self.alpha + self.bias
        return max(0, min(100, calibrated))

    def apply_batch(self, raw_scores: list[float]) -> list[float]:
        """Apply calibration to batch of scores."""
        return [self.apply(s) for s in raw_scores]

    def update_params(self, alpha: float, bias: float):
        """Update calibration parameters."""
        self.alpha = alpha
        self.bias = bias

    def fit(self, predicted: list[float], actual: list[float]):
        """
        Fit alpha and bias using linear regression.
        predicted = raw scores, actual = ground truth outcomes (0-100)
        """
        import numpy as np

        X = np.array(predicted)
        y = np.array(actual)

        # Linear regression: y = alpha * x + bias
        # Using least squares
        n = len(X)
        sum_x = X.sum()
        sum_y = y.sum()
        sum_xy = (X * y).sum()
        sum_xx = (X * X).sum()

        denominator = n * sum_xx - sum_x * sum_x
        if abs(denominator) < 1e-10:
            return  # Avoid division by zero

        self.alpha = (n * sum_xy - sum_x * sum_y) / denominator
        self.bias = (sum_y - self.alpha * sum_x) / n

        # Clamp to reasonable ranges
        self.alpha = max(0.5, min(1.5, self.alpha))
        self.bias = max(-20, min(20, self.bias))


# Global simple calibrator
simple_calibrator = CalibrationLayer()

# Alias for backward compatibility
CalibrationEngine = CalibrationLayer
