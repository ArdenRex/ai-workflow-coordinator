// src/motion/useTilt3D.js
//
// A small, dependency-free hook for cursor-reactive 3D tilt — the effect
// used on task cards so the board feels tactile instead of flat. Tracks
// pointer position inside the element and maps it to a perspective
// rotation + a subtle glare highlight, with spring-like return-to-rest.
//
// Usage:
//   const { ref, style, onPointerMove, onPointerLeave, onPointerEnter } = useTilt3D();
//   <div ref={ref} style={style} onPointerMove={onPointerMove}
//        onPointerEnter={onPointerEnter} onPointerLeave={onPointerLeave}>...</div>
//
// Respects prefers-reduced-motion: returns inert handlers/styles when set.

import { useRef, useState, useCallback, useMemo } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function useTilt3D({ max = 9, scale = 1.015, glare = true } = {}) {
  const ref = useRef(null);
  const [transform, setTransform] = useState(
    "perspective(800px) rotateX(0deg) rotateY(0deg) scale(1)"
  );
  const [glareStyle, setGlareStyle] = useState({ opacity: 0 });
  const reduced = useMemo(prefersReducedMotion, []);

  const onPointerMove = useCallback(
    (e) => {
      if (reduced || !ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width; // 0..1
      const py = (e.clientY - rect.top) / rect.height; // 0..1
      const rotY = (px - 0.5) * max * 2;
      const rotX = (0.5 - py) * max * 2;
      setTransform(
        `perspective(800px) rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(
          2
        )}deg) scale(${scale})`
      );
      if (glare) {
        setGlareStyle({
          opacity: 0.14,
          background: `radial-gradient(circle at ${px * 100}% ${
            py * 100
          }%, rgba(255,255,255,0.55), transparent 55%)`,
        });
      }
    },
    [max, scale, glare, reduced]
  );

  const onPointerLeave = useCallback(() => {
    setTransform("perspective(800px) rotateX(0deg) rotateY(0deg) scale(1)");
    setGlareStyle({ opacity: 0 });
  }, []);

  const style = {
    transform,
    transition: "transform 0.35s cubic-bezier(0.16,1,0.3,1)",
    transformStyle: "preserve-3d",
    willChange: "transform",
  };

  return { ref, style, glareStyle, onPointerMove, onPointerLeave };
}

export default useTilt3D;
