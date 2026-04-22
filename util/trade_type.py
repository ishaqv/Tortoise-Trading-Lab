from enum import Enum, auto


class TradeType(Enum):
    INTRADAY = auto()
    SWING = auto()
    POSITIONAL = auto()
