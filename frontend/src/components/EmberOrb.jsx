// src/components/EmberOrb.jsx
//
// Hero visual for the Auth/Onboarding shell. Pure CSS/SVG — no WebGL,
// no three.js, no Canvas — so what's specified below is exactly what
// renders, with no lighting-engine step in between to lose fidelity.
//
// v3 — "material" pass, aimed at photoreal cues rather than more motion:
//   - real surface grain via an SVG feTurbulence filter (procedural, not
//     an image) blended over the sphere, so it reads as a rough/molten
//     material instead of a flat vector gradient
//   - TWO specular highlights (a broad soft one + a tiny hard glint),
//     which is what actually sells "glossy" — a single highlight always
//     reads as flat, real glass/metal photos almost always show two
//   - a fresnel rim: the edge of the sphere is lit independently of the
//     main light source (cool white-blue) and brighter at grazing angle,
//     which is the single biggest "is this a real render" cue
//   - a faint chromatic fringe at the rim (red/blue channel offset),
//     the same artifact real camera lenses produce at high-contrast edges
//   - contrast/saturation boost on the core so it doesn't sit flat
//     against the vector rings around it
//
// Usage:
//   <EmberOrb size={280} interactive />

import React, { useMemo, useId } from "react";
import useTilt3D from "../motion/useTilt3D";

const PARTICLES = [
  { angle: 18,  dist: 0.64, size: 3,   delay: 0.0, depth: 1,   hot: true  },
  { angle: 55,  dist: 0.80, size: 2,   delay: 0.6, depth: 0.6, hot: false },
  { angle: 96,  dist: 0.58, size: 2.6, delay: 1.2, depth: 1,   hot: true  },
  { angle: 132, dist: 0.88, size: 3.2, delay: 0.3, depth: 0.6, hot: false },
  { angle: 168, dist: 0.66, size: 1.8, delay: 1.6, depth: 0.7, hot: false },
  { angle: 205, dist: 0.78, size: 2.8, delay: 0.9, depth: 1,   hot: true  },
  { angle: 240, dist: 0.60, size: 3,   delay: 2.1, depth: 0.9, hot: false },
  { angle: 278, dist: 0.84, size: 2.2, delay: 0.4, depth: 0.6, hot: true  },
  { angle: 312, dist: 0.70, size: 2.8, delay: 1.4, depth: 1,   hot: false },
  { angle: 345, dist: 0.62, size: 1.8, delay: 1.9, depth: 0.7, hot: false },
  { angle: 70,  dist: 0.94, size: 1.6, delay: 2.4, depth: 0.4, hot: false },
  { angle: 260, dist: 0.96, size: 1.6, delay: 0.8, depth: 0.4, hot: true  },
];

const ORB_STYLES = `
  @keyframes emberRotate     { from { transform: rotate(0deg);   } to { transform: rotate(360deg); } }
  @keyframes emberRotateSlow { from { transform: rotate(360deg); } to { transform: rotate(0deg);   } }
  @keyframes emberPulse      { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.035); opacity: 0.92; } }
  @keyframes emberTwinkle    { 0%,100% { opacity: 0.15; transform: scale(0.7); } 50% { opacity: 1; transform: scale(1); } }
  @keyframes emberDrift      { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }

  @keyframes emberFloat3D {
    0%   { transform: translateY(0)    rotateY(-6deg) rotateX(2deg); }
    50%  { transform: translateY(-10px) rotateY(6deg)  rotateX(-2deg); }
    100% { transform: translateY(0)    rotateY(-6deg) rotateX(2deg); }
  }

  @keyframes emberChurn1 { 0% { background-position: 20% 30%; } 50% { background-position: 65% 55%; } 100% { background-position: 20% 30%; } }
  @keyframes emberChurn2 { 0% { background-position: 70% 65%; } 50% { background-position: 30% 35%; } 100% { background-position: 70% 65%; } }

  @keyframes emberFlicker {
    0%   { opacity: 0.75; transform: scale(1); }
    18%  { opacity: 1;    transform: scale(1.08); }
    36%  { opacity: 0.6;  transform: scale(0.94); }
    52%  { opacity: 0.95; transform: scale(1.04); }
    70%  { opacity: 0.7;  transform: scale(0.98); }
    100% { opacity: 0.75; transform: scale(1); }
  }
  /* The tiny hard glint flickers on its own, faster/sharper cadence than
     the broad highlight — two lights never breathe in sync in reality. */
  @keyframes emberGlint2 {
    0%, 100% { opacity: 0.5; }
    30%      { opacity: 1; }
    55%      { opacity: 0.35; }
    80%      { opacity: 0.9; }
  }

  @keyframes emberFlareSweep {
    0%   { transform: translate(-60%, -60%) rotate(24deg); opacity: 0; }
    8%   { opacity: 0.9; }
    22%  { opacity: 0; }
    100% { transform: translate(60%, 60%) rotate(24deg); opacity: 0; }
  }

  /* Fresnel rim brightens/dims slightly out of phase with the core pulse
     — as if catching ambient light independently of the core's own glow. */
  @keyframes emberFresnel { 0%,100% { opacity: 0.55; } 50% { opacity: 0.85; } }

  .ember-orb-scene { perspective: 900px; }
  .ember-orb-wrap {
    position: relative;
    display: flex; align-items: center; justify-content: center;
    transform-style: preserve-3d;
    animation: emberFloat3D 9s ease-in-out infinite;
  }
  .ember-orb-shadow {
    position: absolute;
    left: 50%; bottom: -6%;
    width: 70%; height: 14%;
    transform: translateX(-50%);
    border-radius: 50%;
    background: radial-gradient(ellipse, rgba(0,0,0,0.55) 0%, transparent 75%);
    filter: blur(4px);
    animation: emberPulse 9s ease-in-out infinite;
    pointer-events: none;
  }
  .ember-orb-halo {
    position: absolute; inset: -18%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,106,82,0.30) 0%, rgba(200,31,48,0.14) 40%, transparent 72%);
    filter: blur(14px);
    animation: emberPulse 5s ease-in-out infinite;
    pointer-events: none;
  }

  .ember-orb-ring3d-tilt {
    position: absolute;
    border-radius: 50%;
    transform-style: preserve-3d;
    pointer-events: none;
  }
  .ember-orb-ring3d-spin {
    position: absolute; inset: 0;
    border-radius: 50%;
    -webkit-mask-image: radial-gradient(circle, transparent 61%, black 64%, black 78%, transparent 82%);
    mask-image: radial-gradient(circle, transparent 61%, black 64%, black 78%, transparent 82%);
  }

  .ember-orb-core {
    position: relative;
    border-radius: 50%;
    overflow: hidden;
    background:
      radial-gradient(circle at 34% 28%, #fff3de 0%, #ffcf8a 9%, #ff9a6a 24%, #ff6a52 44%, #c81f30 70%, #6b0f16 90%, #34060a 100%);
    box-shadow:
      inset -22px -22px 60px rgba(0,0,0,0.55),
      inset 14px 14px 46px rgba(255,224,170,0.35),
      inset 0 0 0 1px rgba(255,224,170,0.18),
      0 0 50px rgba(255,106,82,0.5),
      0 0 110px rgba(200,31,48,0.28);
    animation: emberPulse 4.5s ease-in-out infinite;
    filter: contrast(1.08) saturate(1.12);
  }
  .ember-orb-lava {
    position: absolute; inset: -20%;
    border-radius: 50%;
    background-repeat: no-repeat;
    background-size: 70% 70%;
    mix-blend-mode: overlay;
    pointer-events: none;
  }
  /* Procedural grain — real material roughness, not a drawn gradient. */
  .ember-orb-grain {
    position: absolute; inset: 0;
    border-radius: 50%;
    mix-blend-mode: overlay;
    opacity: 0.4;
    pointer-events: none;
  }
  /* Fresnel: bright cool ring at the very edge, independent of the warm
     key light — the edge of a real sphere always picks up ambient/sky
     light differently than its lit face. */
  .ember-orb-fresnel {
    position: absolute; inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle, transparent 74%, rgba(255,240,220,0.55) 88%, rgba(200,225,255,0.35) 94%, transparent 100%);
    mix-blend-mode: screen;
    animation: emberFresnel 6s ease-in-out infinite;
    pointer-events: none;
  }
  /* Chromatic fringe — faint red/blue channel offset right at the rim,
     the artifact a real lens leaves on a high-contrast silhouette. */
  .ember-orb-fringe {
    position: absolute; inset: 0;
    border-radius: 50%;
    box-shadow:
      inset 1.5px 0 0 0 rgba(255,60,60,0.12),
      inset -1.5px 0 0 0 rgba(70,140,255,0.12);
    pointer-events: none;
  }
  .ember-orb-hotspot {
    position: absolute;
    top: 22%; left: 26%;
    width: 22%; height: 22%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.95) 0%, rgba(255,224,170,0.45) 45%, transparent 75%);
    filter: blur(2px);
    animation: emberFlicker 3.4s ease-in-out infinite;
    pointer-events: none;
  }
  /* The second, smaller, sharper glint — this is what makes it read as
     "wet"/glossy rather than a matte painted circle. */
  .ember-orb-hotspot2 {
    position: absolute;
    top: 40%; left: 58%;
    width: 7%; height: 7%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.95) 0%, transparent 70%);
    filter: blur(0.5px);
    animation: emberGlint2 2.2s ease-in-out infinite;
    pointer-events: none;
  }
  .ember-orb-flare {
    position: absolute;
    top: 50%; left: 50%;
    width: 14%; height: 130%;
    background: linear-gradient(to bottom, transparent, rgba(255,255,255,0.85), transparent);
    filter: blur(3px);
    animation: emberFlareSweep 7s ease-in-out infinite;
    animation-delay: 2s;
    pointer-events: none;
  }
  .ember-orb-ao {
    position: absolute; inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle at 68% 74%, rgba(0,0,0,0.5) 0%, transparent 55%);
    mix-blend-mode: multiply;
    pointer-events: none;
  }

  .ember-orb-particle {
    position: absolute;
    border-radius: 50%;
    animation: emberTwinkle 3.2s ease-in-out infinite, emberDrift 6s ease-in-out infinite;
    pointer-events: none;
  }
`;

export default function EmberOrb({ size = 300, interactive = false, intensity = 1 }) {
  const { ref, style: tiltStyle, onPointerMove, onPointerLeave } = useTilt3D({
    max: interactive ? 10 : 0,
    scale: 1.01,
    glare: false,
  });

  const particles = useMemo(() => PARTICLES, []);
  const filterId = useId().replace(/:/g, "");

  return (
    <div className="ember-orb-scene" style={{ width: size, height: size }}>
      {/* Procedural grain filter — feTurbulence generates the noise, no
          image asset involved. Zero-size SVG, purely a filter def. */}
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <filter id={`emberGrain-${filterId}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch" result="noise" />
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 1  0 0 0 0 0.75  0 0 0 0 0.55  0 0 0 0.5 0" />
        </filter>
      </svg>

      <div
        ref={interactive ? ref : undefined}
        onPointerMove={interactive ? onPointerMove : undefined}
        onPointerLeave={interactive ? onPointerLeave : undefined}
        className="ember-orb-wrap"
        style={{
          width: size,
          height: size,
          ...(interactive ? tiltStyle : {}),
        }}
      >
        <style>{ORB_STYLES}</style>

        <div className="ember-orb-shadow" style={{ opacity: 0.7 * intensity }} />
        <div className="ember-orb-halo" style={{ opacity: 0.85 * intensity }} />

        <div
          className="ember-orb-ring3d-tilt"
          style={{ inset: "-10%", transform: "rotateX(72deg) rotateZ(-8deg)", opacity: 0.85 * intensity }}
        >
          <div
            className="ember-orb-ring3d-spin"
            style={{
              background: `conic-gradient(from 0deg,
                rgba(255,106,82,0.9) 0deg, rgba(255,207,138,0.5) 40deg, transparent 90deg,
                transparent 180deg, rgba(200,31,48,0.85) 230deg, rgba(255,106,82,0.5) 270deg,
                transparent 340deg, transparent 360deg)`,
              filter: "blur(1.5px)",
              animation: "emberRotate 14s linear infinite",
            }}
          />
        </div>
        <div
          className="ember-orb-ring3d-tilt"
          style={{ inset: "2%", transform: "rotateX(68deg) rotateZ(14deg)", opacity: 0.6 * intensity }}
        >
          <div
            className="ember-orb-ring3d-spin"
            style={{
              background: `conic-gradient(from 90deg,
                transparent 0deg, rgba(255,224,170,0.6) 20deg, transparent 50deg,
                transparent 200deg, rgba(255,106,82,0.55) 224deg, transparent 250deg,
                transparent 360deg)`,
              filter: "blur(1px)",
              animation: "emberRotateSlow 20s linear infinite",
            }}
          />
        </div>

        <div className="ember-orb-core" style={{ width: "72%", height: "72%" }}>
          <div
            className="ember-orb-lava"
            style={{ background: "radial-gradient(circle, rgba(255,207,138,0.55) 0%, transparent 70%)", animation: "emberChurn1 11s ease-in-out infinite" }}
          />
          <div
            className="ember-orb-lava"
            style={{ background: "radial-gradient(circle, rgba(200,31,48,0.5) 0%, transparent 65%)", backgroundSize: "55% 55%", animation: "emberChurn2 8s ease-in-out infinite" }}
          />
          <div className="ember-orb-grain" style={{ filter: `url(#emberGrain-${filterId})` }} />
          <div className="ember-orb-ao" />
          <div className="ember-orb-fresnel" />
          <div className="ember-orb-fringe" />
          <div className="ember-orb-hotspot" />
          <div className="ember-orb-hotspot2" />
          <div className="ember-orb-flare" />
        </div>

        {particles.map((p, i) => {
          const rad = (p.angle * Math.PI) / 180;
          const r = size * 0.5 * p.dist;
          const x = size / 2 + Math.cos(rad) * r;
          const y = size / 2 + Math.sin(rad) * r;
          const core = p.hot ? "#fff3de" : "#ffe3b8";
          const mid  = p.hot ? "#ffcf8a" : "#ff6a52";
          return (
            <span
              key={i}
              className="ember-orb-particle"
              style={{
                width: p.size, height: p.size,
                left: x, top: y,
                marginLeft: -p.size / 2, marginTop: -p.size / 2,
                background: `radial-gradient(circle, ${core} 0%, ${mid} 55%, transparent 75%)`,
                boxShadow: p.hot
                  ? "0 0 7px 1.5px rgba(255,224,170,0.9)"
                  : "0 0 6px 1px rgba(255,106,82,0.8)",
                opacity: 0.5 + 0.5 * p.depth,
                filter: p.depth < 0.8 ? `blur(${(1 - p.depth) * 1.5}px)` : "none",
                animationDelay: `${p.delay}s, ${p.delay * 0.7}s`,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
