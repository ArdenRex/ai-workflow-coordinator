// src/components/EmberOrb.jsx
//
// Hero visual for the Auth/Onboarding shell. Pure CSS/SVG — no WebGL,
// no three.js, no Canvas — so what's specified below is exactly what
// renders, with no lighting-engine step in between to lose fidelity.
//
// v2: layered for real depth rather than a single flat gradient disc —
//   - true perspective + rotateX'd rings (an actual tilted 3D ellipse,
//     not just a flat circle drawn to look like one)
//   - a churning "molten surface": two independent blob layers drifting
//     across the sphere on different cycles, blended with mix-blend-mode
//     so the surface never looks static
//   - a flickering specular highlight (the "wet glass" glint) plus an
//     occasional light-sweep flare across it
//   - a soft grounding shadow so the orb reads as sitting in the scene,
//     not pasted on top of it
//   - idle floating + gentle 3D turntable sway on the whole orb
//
// Usage:
//   <EmberOrb size={280} interactive />

import React, { useMemo } from "react";
import useTilt3D from "../motion/useTilt3D";

// Deterministic ember-particle field — fixed seed so layout is stable
// across renders/reloads rather than reshuffling. `depth` fakes parallax:
// smaller/dimmer/blurrier = "further away".
const PARTICLES = [
  { angle: 18,  dist: 0.64, size: 3,   delay: 0.0, depth: 1   },
  { angle: 55,  dist: 0.80, size: 2,   delay: 0.6, depth: 0.6 },
  { angle: 96,  dist: 0.58, size: 2.6, delay: 1.2, depth: 1   },
  { angle: 132, dist: 0.88, size: 3.2, delay: 0.3, depth: 0.6 },
  { angle: 168, dist: 0.66, size: 1.8, delay: 1.6, depth: 0.7 },
  { angle: 205, dist: 0.78, size: 2.8, delay: 0.9, depth: 1   },
  { angle: 240, dist: 0.60, size: 3,   delay: 2.1, depth: 0.9 },
  { angle: 278, dist: 0.84, size: 2.2, delay: 0.4, depth: 0.6 },
  { angle: 312, dist: 0.70, size: 2.8, delay: 1.4, depth: 1   },
  { angle: 345, dist: 0.62, size: 1.8, delay: 1.9, depth: 0.7 },
  { angle: 70,  dist: 0.94, size: 1.6, delay: 2.4, depth: 0.4 },
  { angle: 260, dist: 0.96, size: 1.6, delay: 0.8, depth: 0.4 },
];

const ORB_STYLES = `
  @keyframes emberRotate     { from { transform: rotate(0deg);   } to { transform: rotate(360deg); } }
  @keyframes emberRotateSlow { from { transform: rotate(360deg); } to { transform: rotate(0deg);   } }
  @keyframes emberPulse      { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.035); opacity: 0.92; } }
  @keyframes emberTwinkle    { 0%,100% { opacity: 0.15; transform: scale(0.7); } 50% { opacity: 1; transform: scale(1); } }
  @keyframes emberDrift      { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }

  /* Whole orb: gentle float + a slow "turntable" sway so it reads as a
     real object hanging in 3D space rather than a static sticker. */
  @keyframes emberFloat3D {
    0%   { transform: translateY(0)    rotateY(-6deg) rotateX(2deg); }
    50%  { transform: translateY(-10px) rotateY(6deg)  rotateX(-2deg); }
    100% { transform: translateY(0)    rotateY(-6deg) rotateX(2deg); }
  }

  /* Molten surface churn — two independent cycles so the blobs never
     line up into a repeating pattern. */
  @keyframes emberChurn1 { 0% { background-position: 20% 30%; } 50% { background-position: 65% 55%; } 100% { background-position: 20% 30%; } }
  @keyframes emberChurn2 { 0% { background-position: 70% 65%; } 50% { background-position: 30% 35%; } 100% { background-position: 70% 65%; } }

  /* Specular glint flicker — irregular multi-stop so it doesn't read as
     a metronomic pulse. */
  @keyframes emberFlicker {
    0%   { opacity: 0.75; transform: scale(1); }
    18%  { opacity: 1;    transform: scale(1.08); }
    36%  { opacity: 0.6;  transform: scale(0.94); }
    52%  { opacity: 0.95; transform: scale(1.04); }
    70%  { opacity: 0.7;  transform: scale(0.98); }
    100% { opacity: 0.75; transform: scale(1); }
  }

  /* A single bright streak sweeping across the sphere every ~7s, like
     light catching wet glass. */
  @keyframes emberFlareSweep {
    0%   { transform: translate(-60%, -60%) rotate(24deg); opacity: 0; }
    8%   { opacity: 0.9; }
    22%  { opacity: 0; }
    100% { transform: translate(60%, 60%) rotate(24deg); opacity: 0; }
  }

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

  /* 3D ring: outer div sets the fixed tilt (rotateX), inner div is a
     true donut (mask-image cuts real alpha, so it works over ANY
     background) that spins on its own axis inside the tilted plane. */
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
  }
  /* Churning molten texture — sits inside the clipped sphere so it never
     spills past the circular edge. */
  .ember-orb-lava {
    position: absolute; inset: -20%;
    border-radius: 50%;
    background-repeat: no-repeat;
    background-size: 70% 70%;
    mix-blend-mode: overlay;
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
    background: radial-gradient(circle, #ffe3b8 0%, #ff6a52 55%, transparent 75%);
    box-shadow: 0 0 6px 1px rgba(255,154,106,0.8);
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

  return (
    <div className="ember-orb-scene" style={{ width: size, height: size }}>
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

        {/* Grounding shadow */}
        <div className="ember-orb-shadow" style={{ opacity: 0.7 * intensity }} />

        {/* Soft outer bloom */}
        <div className="ember-orb-halo" style={{ opacity: 0.85 * intensity }} />

        {/* Two true 3D rings — tilted via rotateX so they read as
            ellipses in perspective, each spinning on its own axis. */}
        <div
          className="ember-orb-ring3d-tilt"
          style={{
            inset: "-10%",
            transform: "rotateX(72deg) rotateZ(-8deg)",
            opacity: 0.85 * intensity,
          }}
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
          style={{
            inset: "2%",
            transform: "rotateX(68deg) rotateZ(14deg)",
            opacity: 0.6 * intensity,
          }}
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

        {/* The molten core — layered gradient + churn + specular + AO
            stack does the "glossy lit sphere" job a flat emissive
            material was failing at, entirely with real CSS transparency
            (mask-image), not guesswork. */}
        <div className="ember-orb-core" style={{ width: "72%", height: "72%" }}>
          <div
            className="ember-orb-lava"
            style={{
              background: "radial-gradient(circle, rgba(255,207,138,0.55) 0%, transparent 70%)",
              animation: "emberChurn1 11s ease-in-out infinite",
            }}
          />
          <div
            className="ember-orb-lava"
            style={{
              background: "radial-gradient(circle, rgba(200,31,48,0.5) 0%, transparent 65%)",
              backgroundSize: "55% 55%",
              animation: "emberChurn2 8s ease-in-out infinite",
            }}
          />
          <div className="ember-orb-ao" />
          <div className="ember-orb-hotspot" />
          <div className="ember-orb-flare" />
        </div>

        {/* Drifting ember particles, with a bit of parallax depth */}
        {particles.map((p, i) => {
          const rad = (p.angle * Math.PI) / 180;
          const r = size * 0.5 * p.dist;
          const x = size / 2 + Math.cos(rad) * r;
          const y = size / 2 + Math.sin(rad) * r;
          return (
            <span
              key={i}
              className="ember-orb-particle"
              style={{
                width: p.size, height: p.size,
                left: x, top: y,
                marginLeft: -p.size / 2, marginTop: -p.size / 2,
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
