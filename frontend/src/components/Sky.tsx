import { useMemo } from "react";

/** Night sky behind everything: star field, state-tinted light washes, shooting stars and film grain. */
export function Sky({ score, warmth }: { score: number; warmth: number }) {
  const stars = useMemo(() => {
    let sd = 7 >>> 0;
    const r = () => ((sd = (Math.imul(sd, 1664525) + 1013904223) >>> 0) / 4294967296);
    const field = (n: number, a: number, b: number) => {
      let d = "";
      for (let i = 0; i < n; i++) {
        const x = r() * 1440, y = r() * 900, q = a + r() * (b - a);
        d += `M${(x - q).toFixed(1)} ${y.toFixed(1)}a${q.toFixed(2)} ${q.toFixed(2)} 0 1 0 ${(2 * q).toFixed(2)} 0a${q.toFixed(2)} ${q.toFixed(2)} 0 1 0 ${(-2 * q).toFixed(2)} 0`;
      }
      return d;
    };
    return [field(110, 0.4, 0.9), field(70, 0.5, 1.1), field(24, 0.9, 1.6)];
  }, []);

  return (
    <div className="sky" aria-hidden="true">
      <div className="wash wash-calm" style={{ opacity: 0.3 + 0.7 * score * (1 - warmth) }} />
      <div className="wash wash-storm" style={{ opacity: 1 - score }} />
      <div className="wash wash-gold" style={{ opacity: warmth }} />
      <svg className="stars" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
        <path d={stars[0]} fill="#dfe3ff" className="tw-a" />
        <path d={stars[1]} fill="#c9c3ff" className="tw-b" />
        <path d={stars[2]} fill="#ffffff" className="tw-c" />
      </svg>
      <div className="shoot shoot-1" />
      <div className="shoot shoot-2" />
      <svg className="grain" style={{ opacity: 0.05 + 0.1 * (1 - score) }}>
        <filter id="grainFine"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} stitchTiles="stitch" /><feColorMatrix type="saturate" values="0" /></filter>
        <rect width="100%" height="100%" filter="url(#grainFine)" />
      </svg>
    </div>
  );
}
