from datetime import datetime, timedelta, timezone

from backend import config
from backend.contracts import Bar
from backend.replay import Clock

COUNT_S = (config.COUNT_IN_CLICKS - 1) * config.COUNT_IN_INTERVAL_S
RATE = config.SPEED_BARS_PER_S[config.DEFAULT_SPEED_STEP]


def make_bars() -> list[Bar]:
    t0 = datetime(2015, 1, 12, tzinfo=timezone.utc) - timedelta(minutes=15 * 10)  # 10 warm-up bars
    return [Bar(k, t0 + timedelta(minutes=15 * k), 1.0, 1.0, 1.0, 0.0, 0.0, 0.0) for k in range(1200)]


def counted_in(c: Clock) -> Clock:
    c.start()
    assert c.take_count_in()
    c.tick(0.0)  # the reset
    return c


def test_starts_at_replay_start_paused() -> None:
    c = Clock(make_bars())
    assert c.position == 10 and c.status == "free"
    assert c.tick(1.0).bars == []


def test_start_counts_in_then_runs_at_default_speed() -> None:
    c = Clock(make_bars())
    c.set_speed(7)
    c.start()
    assert c.speed_step == config.DEFAULT_SPEED_STEP  # the count-in fixes the speed
    assert c.take_count_in() and not c.take_count_in()  # the clicks are handed over once
    assert c.tick(0.05).reset
    n = 0
    for _ in range(round((COUNT_S - 0.1) * 20)):  # silent until beat 4
        n += len(c.tick(0.05).bars)
    assert n == 0 and c.position == 10
    c.tick(0.1)  # beat 4
    assert len(c.tick(1.0).bars) == RATE


def test_count_in_waits_for_queued_audio() -> None:
    c = Clock(make_bars())
    c.start()
    assert c.take_count_in(lead=1.0)
    c.tick(0.0)
    assert c.tick(COUNT_S).bars == [] and c.tick(1.0).bars == []  # still counting
    assert len(c.tick(1.0).bars) == RATE


def test_new_start_restarts_from_replay_start() -> None:
    c = counted_in(Clock(make_bars()))
    c.tick(COUNT_S + 1.0)
    c.tick(0.0)
    assert c.position > 10
    c.start()
    assert c.take_count_in()
    assert c.tick(0.0).reset and c.position == 10


def test_pause_cancels_count_in() -> None:
    c = Clock(make_bars())
    c.start()
    c.pause()
    assert not c.take_count_in()
    assert c.tick(0.0).reset and c.tick(5.0).bars == []


def test_heard_count_in_starts_on_beat_4_at_replay_start() -> None:
    c = Clock(make_bars())
    c.set_speed(2)
    assert c.status == "free" and c.tick(5.0).bars == []  # waits for the count-in
    c.tick(30.0)
    c.on_count_in()
    assert c.tick(0.0).reset and c.position == 10 and c.speed_step == config.DEFAULT_SPEED_STEP
    assert len(c.tick(1.0).bars) == RATE and c.status == "free"  # free-runs, no clock packets


def test_heard_count_in_catches_up_the_detection_lag() -> None:
    c = Clock(make_bars())
    c.on_count_in(lag=0.25)
    c.tick(0.0)
    assert len(c.tick(0.0).bars) == RATE // 4


def test_ignores_own_count_in() -> None:
    c = Clock(make_bars())
    c.start()
    c.take_count_in()
    c.tick(0.0)
    assert not c.on_count_in()  # our own beat 4 coming back through the mic
    c.tick(COUNT_S + config.COUNT_IN_DEAF_S + 0.1)
    assert not c.on_count_in()  # running: a stray count-in must not restart us
    c.reset()
    c.tick(0.0)
    assert c.on_count_in()  # idle: a later one from another Mac starts us



# ----- late join (§9.4a) -------------------------------------------------------------------


def test_paused_clock_joins_the_room_and_catches_up() -> None:
    c = Clock(make_bars())
    assert c.on_heard_bar(0, 40, config.DEFAULT_SPEED_STEP, 0.0)  # the room is 30 bars into the replay
    out = c.tick(0.05).bars
    assert out[0].i == 10 and c.position >= 40  # every bar from the start, in order, in one catch-up tick


def test_running_clock_holds_when_ahead_of_the_room() -> None:
    c = counted_in(Clock(make_bars()))
    c.tick(COUNT_S + 0.01)
    c.tick(20 / RATE)
    pos = c.position
    assert not c.on_heard_bar(1, pos - 10, config.DEFAULT_SPEED_STEP, 0.0)
    assert c.tick(1 / RATE).bars == []  # 10 bars ahead: wait for the room
    for _ in range(20):
        c.tick(1 / RATE)
    assert c.position - (pos - 10 + 21) <= config.RESYNC_BARS + 1  # moving again once back within reach


def test_running_clock_catches_up_when_behind_the_room() -> None:
    c = counted_in(Clock(make_bars()))
    c.tick(COUNT_S + 0.01)
    pos = c.position
    c.on_heard_bar(1, pos + 15, config.DEFAULT_SPEED_STEP, 0.0)
    assert len(c.tick(0.05).bars) >= 15


def test_small_offsets_are_left_alone() -> None:
    c = counted_in(Clock(make_bars()))
    c.tick(COUNT_S + 0.01)
    c.tick(5 / RATE)
    pos = c.position
    c.on_heard_bar(1, pos + config.RESYNC_BARS - 1, config.DEFAULT_SPEED_STEP, 0.0)  # within reach after this tick
    assert len(c.tick(1 / RATE).bars) == 1  # normal pace


def test_held_clock_does_not_join() -> None:
    c = Clock(make_bars())
    c.hold()
    assert not c.on_heard_bar(0, 40, config.DEFAULT_SPEED_STEP, 0.0)
    assert c.tick(1.0).bars == []
    c.reset()  # Reset (or Start) releases the hold
    assert c.on_heard_bar(0, 40, config.DEFAULT_SPEED_STEP, 0.0)


def test_no_join_while_counting_in() -> None:
    c = Clock(make_bars())
    c.start()
    assert not c.on_heard_bar(0, 40, config.DEFAULT_SPEED_STEP, 0.0)


def test_finished_clock_ignores_count_ins_until_reset() -> None:
    c = counted_in(Clock(make_bars()))
    c.tick(COUNT_S + 0.01)
    while c.tick(1.0).bars:  # play to the end
        pass
    assert not c.on_count_in(0.0)  # a stray count-in (room noise) mustn't restart a finished replay
    assert c.tick(1.0).bars == []
    c.reset()
    assert c.on_count_in(0.0)  # after Reset it takes a count-in again
