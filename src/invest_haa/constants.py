from decimal import Decimal

CANARY = "TIP"
OFFENSIVE = ("SPY", "IWM", "VEA", "VWO", "VNQ", "DBC", "IEF", "TLT")
DEFENSIVE = ("IEF", "BIL")
UNIVERSE = tuple(dict.fromkeys((CANARY, *OFFENSIVE, *DEFENSIVE)))
LOOKBACKS = (1, 3, 6, 12)
TOP_N = 4

SLOT_WEIGHT = Decimal("0.25")
MIN_TOLERANCE_USD = Decimal("5")
TOLERANCE_RATE = Decimal("0.0025")
CASH_BUFFER_RATE = Decimal("0.005")
QUANTITY_STEP = Decimal("0.000001")
AMOUNT_STEP = Decimal("0.01")
