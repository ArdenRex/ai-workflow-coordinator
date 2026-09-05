// src/components/TiltPCard.jsx
//
// A drop-in replacement for `<div className="pcard">` that adds the
// cursor-reactive 3D tilt + glare from useTilt3D. Used for the small
// stat-tile / grid-card patterns repeated across Reports, Compliance,
// Knowledge, and the Dashboard metrics row — one shared component so
// the interaction is consistent everywhere instead of hand-rolled per
// page.
//
// Usage: identical to the old `<div className="pcard" style={...}>`,
// just swap the tag. Accepts the same style/onClick/children props.

import React from "react";
import useTilt3D from "../motion/useTilt3D";

export default function TiltPCard({
  children,
  style = {},
  className = "",
  onClick,
  tiltMax = 5,
  ...rest
}) {
  const { ref, style: tiltStyle, glareStyle, onPointerMove, onPointerLeave } =
    useTilt3D({ max: tiltMax, scale: 1.01 });

  return (
    <div
      ref={ref}
      className={`pcard ${className}`.trim()}
      onClick={onClick}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      style={{ ...style, ...tiltStyle, position: "relative", overflow: "hidden" }}
      {...rest}
    >
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", ...glareStyle }} />
      {children}
    </div>
  );
}
