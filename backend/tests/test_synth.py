import numpy as np

from backend.audio.synth import Synth
from backend.config import SAMPLE_RATE


def _settle(s: Synth, secs: float = 2.0) -> None:
    for _ in range(int(secs * SAMPLE_RATE / 480)):
        s.render(480)


def test_shape_and_level() -> None:
    for step in range(7):
        for e in (0.0, 0.5, 1.0):
            s = Synth(seed=0)
            s.set(step, e)
            for _ in range(60):
                x = s.render(480)
                assert x.dtype == np.float32 and x.shape == (480,)
                assert np.abs(x).max() <= 1.0
            assert np.abs(x).max() > 0.05


def test_band_limit() -> None:
    s = Synth(seed=0)
    s.set(3, 0.0)
    _settle(s)
    x = np.concatenate([s.render(480).copy() for _ in range(100)]).astype(np.float64)
    p = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SAMPLE_RATE)
    assert 10 * np.log10(p[f > 8000].sum() / p.sum()) <= -60


def test_smooth_step_change() -> None:
    s = Synth(seed=0)
    s.set(0, 1.0)
    _settle(s, 0.5)
    first = s.render(480).copy()
    s.set(6, 1.0)
    x = np.concatenate([first] + [s.render(480).copy() for _ in range(40)])
    assert np.abs(np.diff(x)).max() < 0.1
    assert not np.allclose(x[:480], x[-480:], atol=0.05)  # chord really changed


def test_set_playing_fades_out_and_in_without_clicks() -> None:
    import numpy as np
    from backend.audio.synth import FADE_S, Synth
    from backend.config import BLOCK, SAMPLE_RATE
    s = Synth(seed=0)
    s.set(2, 1.0)
    for _ in range(10):
        s.render(BLOCK)
    s.set_playing(False)
    blocks = int(FADE_S * SAMPLE_RATE / BLOCK) + 2
    out = np.concatenate([s.render(BLOCK).copy() for _ in range(blocks)])
    assert np.max(np.abs(np.diff(out))) < 0.1  # no click while fading
    assert np.max(np.abs(s.render(BLOCK))) == 0.0  # silent once faded
    s.set_playing(True)
    out = np.concatenate([s.render(BLOCK).copy() for _ in range(blocks)])
    assert np.max(np.abs(np.diff(out))) < 0.1 and np.max(np.abs(out[-BLOCK:])) > 0.05
