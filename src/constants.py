"""Constants for Vinayak Procurement Copilot.

Clean-code rule G3: Replace magic values with named constants.
"""

from decimal import Decimal

# Unit conversion constants
SQFT_PER_SQM = Decimal("10.7639")
LITRES_PER_STANDARD_DRUM = Decimal("20.0")
KG_PER_METRIC_TON = Decimal("1000.0")

# Default GST Tax Rates in Indian Construction
GST_PERCENT_STANDARD = Decimal("18.0")
GST_PERCENT_HIGH = Decimal("28.0")
GST_PERCENT_NIL = Decimal("0.0")

# Multi-factor vendor evaluation weights (Must sum to 1.0)
WEIGHT_PRICE = Decimal("0.60")
WEIGHT_DELIVERY = Decimal("0.25")
WEIGHT_QUALITY = Decimal("0.15")

# Performance penalties
DISPUTE_PENALTY_PER_INCIDENT = Decimal("0.05")
MAX_DISPUTE_PENALTY = Decimal("0.25")

# Acceptable variance threshold before flagging anomaly (e.g. 20%)
ANOMALY_PRICE_VARIANCE_RATIO = Decimal("0.20")
