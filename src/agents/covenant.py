"""Covenant and financial ratio monitoring.

SME lending and PE due diligence often centers on tracking covenants
(debt/EBITDA, current ratio) over time across multiple reporting periods.
This is a natural extension of the existing term sheet extraction.
"""

from __future__ import annotations


class CovenantMonitor:
    """Monitor financial covenants and detect breaches/warnings."""

    def __init__(self, warning_threshold: float = 0.9):
        """Args:
            warning_threshold: Fraction of threshold that triggers warning (e.g., 0.9 = 90%).
        """
        self.warning_threshold = warning_threshold

    def check_covenants(
        self,
        company: str,
        ratios: dict[str, float],
        covenants: dict[str, dict],
    ) -> dict:
        """Check current ratios against covenant thresholds.

        Args:
            company: Company name.
            ratios: Current ratio values, e.g. {"debt_ebitda": 2.5, "current_ratio": 1.8}.
            covenants: Threshold definitions, e.g. {"debt_ebitda": {"max": 3.0}}.

        Returns:
            Dict with compliant (bool), breaches (list), warnings (list).
        """
        breaches = []
        warnings = []

        for ratio_name, covenant in covenants.items():
            current = ratios.get(ratio_name)
            if current is None:
                continue

            max_val = covenant.get("max")
            min_val = covenant.get("min")

            if max_val is not None:
                if current > max_val:
                    breaches.append({
                        "ratio": ratio_name,
                        "current": current,
                        "threshold": max_val,
                        "type": "exceeded_max",
                        "severity": self._severity(current, max_val, above=True),
                    })
                elif current > max_val * self.warning_threshold:
                    warnings.append({
                        "ratio": ratio_name,
                        "current": current,
                        "threshold": max_val,
                        "type": "approaching_max",
                    })

            if min_val is not None:
                if current < min_val:
                    breaches.append({
                        "ratio": ratio_name,
                        "current": current,
                        "threshold": min_val,
                        "type": "below_min",
                        "severity": self._severity(current, min_val, above=False),
                    })
                elif current < min_val / self.warning_threshold:
                    warnings.append({
                        "ratio": ratio_name,
                        "current": current,
                        "threshold": min_val,
                        "type": "approaching_min",
                    })

        return {
            "company": company,
            "compliant": len(breaches) == 0,
            "breaches": breaches,
            "warnings": warnings,
        }

    def _severity(self, current: float, threshold: float, above: bool) -> str:
        """Determine breach severity based on distance from threshold."""
        if above:
            overshoot = (current - threshold) / threshold
        else:
            overshoot = (threshold - current) / threshold

        if overshoot > 0.5:
            return "critical"
        elif overshoot > 0.2:
            return "high"
        else:
            return "medium"
