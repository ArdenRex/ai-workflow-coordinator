// src/components/EmberOrb.jsx
//
// Replacement for IgnitionCore on the Auth/Onboarding hero (AuthShell).
//
// Why this exists: IgnitionCore is a three.js/WebGL scene, so how it
// actually looks depends on real-time lighting/material math running in
// the browser — something that can't be screenshotted or verified from
// here. Two rounds of "make it look better" tuning on that component
// still rendered as a flat, dark disc for you, which means the fix has
// to stop being "adjust the lighting rig again" and become "stop
// depending on lighting math we can't see." Everything below is plain
// CSS gradients, box-shadows and keyframe animations — what you see is
// exactly what's specified, no renderer in between. No WebGL, no
// three.js, no Canvas — just a div tree, so it can't silently fail to
// mount either.
//
// Usage:
//   <EmberOrb size={280} interactive />

import React, { useMemo } from "react";
import useTilt3D from "../motion/useTilt3D";

// Deterministic ember-particle field around the orb — fixed seed so the
// layout is stable across renders/reloads rather than reshuffling.
const PARTICLES = [
  { angle: 18,  dist: 0.62, size: 3,   delay: 0.0  },
  { angle: 55,  dist: 0.74, size: 2,   delay: 0.6  },
  { angle: 96,  dist: 0.58, size: 2.4, delay: 1.2  },
  { angle: 132, dist: 0.80, size: 3.2, delay: 0.3  },
  { angle: 168, dist: 0.66, size: 2,   delay: 1.6  },
  { angle: 205, dist: 0.72, size: 2.6, delay: 0.9  },
  { angle: 240, dist: 0.60, size: 3,   delay: 2.1  },
  { angle: 278, dist: 0.78, size: 2.2, delay: 0.4  },
  { angle: 312, dist: 0.68, size: 2.8, delay: 1.4  },
  { angle: 345, dist: 0.60, size: 2,   delay: 1.9  },
];

const ORB_STYLES = `
  @keyframes emberRotate      { from { transform: rotate(0deg);   } to { transform: rotate(360deg); } }
  @keyframes emberRotateSlow  { from { transform: rotate(360deg); } to { transform: rotate(0deg);   } }
  @keyframes emberPulse       { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.035); opacity: 0.92; } }
  @keyframes emberTwinkle     { 0%,100% { opacity: 0.15; transform: scale(0.7); } 50% { opacity: 1; transform: scale(1); } }
  @keyframes emberDrift       { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }

  .ember-orb-wrap {
    position: relative;
    display: flex; align-items: center; justify-content: center;
    transform-style: preserve-3d;
  }
  .ember-orb-halo {
    position: absolute; inset: -18%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,106,82,0.30) 0%, rgba(200,31,48,0.14) 40%, transparent 72%);
    filter: blur(14px);
    animation: emberPulse 5s ease-in-out infinite;
    pointer-events: none;
  }
  .ember-orb-ring {
    position: absolute;
    border-radius: 50%;
    pointer-events: none;
  }
  .ember-orb-core {
    position: relative;
    border-radius: 50%;
    background:
      radial-gradient(circle at 34% 28%, #fff3de 0%, #ffcf8a 9%, #ff9a6a 24%, #ff6a52 44%, #c81f30 70%, #6b0f16 90%, #34060a 100%);
    box-shadow:
      inset -22px -22px 60px rgba(0,0,0,0.55),
      inset 14px 14px 46px rgba(255,224,170,0.35),
      0 0 50px rgba(255,106,82,0.5),
      0 0 110px rgba(200,31,48,0.28);
    animation: emberPulse 4.5s ease-in-out infinite;
  }
  .ember-orb-hotspot {
    position: absolute;
    top: 22%; left: 26%;
    width: 22%; height: 22%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.9) 0%, rgba(255,224,170,0.4) 45%, transparent 75%);
    filter: blur(2px);
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

      {/* Soft outer bloom */}
      <div className="ember-orb-halo" style={{ opacity: 0.85 * intensity }} />

      {/* Two counter-rotating facet rings for depth, like orbiting bands */}
      <div
        className="ember-orb-ring"
        style={{
          inset: "-6%",
          background: `conic-gradient(from 0deg,
            transparent 0deg, rgba(255,106,82,0.55) 14deg, transparent 30deg,
            transparent 120deg, rgba(217,154,63,0.45) 138deg, transparent 154deg,
            transparent 240deg, rgba(200,31,48,0.5) 256deg, transparent 272deg,
            transparent 360deg)`,
          filter: "blur(3px)",
          opacity: 0.8 * intensity,
          animation: "emberRotate 18s linear infinite",
        }}
      />
      <div
        className="ember-orb-ring"
        style={{
          inset: "4%",
          background: `conic-gradient(from 90deg,
            transparent 0deg, rgba(255,207,138,0.4) 10deg, transparent 24deg,
            transparent 180deg, rgba(255,106,82,0.4) 194deg, transparent 208deg,
            transparent 360deg)`,
          filter: "blur(2px)",
          opacity: 0.6 * intensity,
          animation: "emberRotateSlow 24s linear infinite",
        }}
      />

      {/* The molten core itself — radial gradient + inset shadow does the
          "glossy lit sphere" job a flat emissive material was failing at */}
      <div className="ember-orb-core" style={{ width: "72%", height: "72%" }}>
        <div className="ember-orb-hotspot" />
      </div>

      {/* Drifting ember particles around the rim */}
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
              animationDelay: `${p.delay}s, ${p.delay * 0.7}s`,
            }}
          />
        );
      })}
    </div>
  );
}
