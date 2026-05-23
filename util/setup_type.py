from enum import Enum, auto


class IntradaySetupType(Enum):
    """
        Enum representing different types of breakout trading setups.

        Members:
            ORB  : Opening Range Breakout setup.
            VWAP : Breakout confirmed by VWAP (Volume Weighted Average Price) Reclaim.
            CRB  : Breakout confirmed by price escaping from a compressed range.
            EVB  : Breakout confirmed by sudden, massive volume expansion relative to recent average.
            EMB  : Breakout confirmed by early price movement.
        """
    ORB = auto()
    VWAP = auto()
    CRB = auto()  # Compressed Range Breakout
    EVB = auto()  # Explosive Volume Breakout
    EMB = auto()  # Early Momentum Breakout


class SwingSetupType(Enum):
    """
        Enum representing different types of swing trading setups.

        Members:
            CRB  : Compressed Range Breakout - Price breaking out after a tight consolidation.
    """
    CRB = auto()
    VEB = auto()
