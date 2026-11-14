from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ClockStatus = Literal["conductor", "following", "free"]


@dataclass(frozen=True)
class Bar:
    i: int
    time: datetime
    S: float
    F: float
    eurchf: float
    rS: float
    rF: float
    rho: float


@dataclass(frozen=True)
class Tick:
    bars: list[Bar]
    reset: bool


@dataclass(frozen=True)
class AdviserState:
    channel: int
    dial: float
    step: int
    half_life_bars: float
    h: float
    score: float
    pnl_unhedged_pct: float
    pnl_hedged_pct: float
    leader_channel: int
    heard: int
    in_trial: bool


@dataclass(frozen=True)
class AdviserPacket:
    channel: int
    seq: int
    score: float
    dial: float


@dataclass(frozen=True)
class ClockPacket:
    channel: int
    seq: int
    bar: int
    speed_step: int


@dataclass(frozen=True)
class Heard:
    packet: AdviserPacket | ClockPacket
    snr_db: float
    received_at: float
