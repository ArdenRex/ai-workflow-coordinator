// src/three/IgnitionCore.jsx
//
// The signature 3D visual for the "Ignition" brand: a slow-turning,
// molten core made of a distorted icosahedron with an emissive
// ember/crimson gradient, a soft rim-light glow shell (fresnel trick,
// no postprocessing needed), and a light drift of ember particles.
//
// Usage:
//   <IgnitionCore size={360} />                 // default, gently auto-rotating
//   <IgnitionCore size={480} interactive />      // drag to rotate with pointer
//   <IgnitionCore size={220} intensity={0.6} />  // smaller / calmer, for headers
//
// Kept intentionally self-contained (own <Canvas>) so it can be dropped
// into any page — auth hero, dashboard ambient corner, empty states —
// without the host page needing to know anything about three.js.

import React, { Suspense, useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { MeshDistortMaterial, Float, Sparkles } from "@react-three/drei";
import * as THREE from "three";

// -- Palette pulled straight from GLOBAL_STYLES --------------------------
const EMBER = "#ff6a52";
const CRIMSON = "#c81f30";
const BLOOD = "#4a0e13";
const AMBER = "#d99a3f";

function MoltenCore({ interactive, intensity }) {
  const meshRef = useRef();
  const dragState = useRef({ dragging: false, lastX: 0, lastY: 0 });
  const velocity = useRef({ x: 0.002, y: 0.0032 });

  useFrame(() => {
    if (!meshRef.current) return;
    meshRef.current.rotation.x += velocity.current.x;
    meshRef.current.rotation.y += velocity.current.y;
    // gentle damping back to resting drift speed after a drag flick
    velocity.current.x += (0.002 - velocity.current.x) * 0.02;
    velocity.current.y += (0.0032 - velocity.current.y) * 0.02;
  });

  const handlers = interactive
    ? {
        onPointerDown: (e) => {
          dragState.current.dragging = true;
          dragState.current.lastX = e.clientX;
          dragState.current.lastY = e.clientY;
        },
        onPointerUp: () => (dragState.current.dragging = false),
        onPointerOut: () => (dragState.current.dragging = false),
        onPointerMove: (e) => {
          if (!dragState.current.dragging) return;
          const dx = e.clientX - dragState.current.lastX;
          const dy = e.clientY - dragState.current.lastY;
          dragState.current.lastX = e.clientX;
          dragState.current.lastY = e.clientY;
          velocity.current.y = dx * 0.004;
          velocity.current.x = dy * 0.004;
        },
      }
    : {};

  return (
    <group>
      {/* Core molten shard */}
      <mesh ref={meshRef} {...handlers}>
        <icosahedronGeometry args={[1, 6]} />
        <MeshDistortMaterial
          color={CRIMSON}
          emissive={BLOOD}
          emissiveIntensity={0.6 * intensity}
          distort={0.42}
          speed={1.6}
          roughness={0.15}
          metalness={0.35}
        />
      </mesh>

      {/* Rim-light glow shell — backside-rendered, additive, gives a
          fresnel-style outer glow without needing a postprocessing pass */}
      <mesh scale={1.18}>
        <icosahedronGeometry args={[1, 4]} />
        <meshBasicMaterial
          color={EMBER}
          transparent
          opacity={0.18 * intensity}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      <mesh scale={1.34}>
        <icosahedronGeometry args={[1, 3]} />
        <meshBasicMaterial
          color={AMBER}
          transparent
          opacity={0.06 * intensity}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

function Scene({ interactive, intensity }) {
  const emberColor = useMemo(() => new THREE.Color(EMBER), []);
  return (
    <>
      <ambientLight intensity={0.35} />
      <pointLight position={[3, 2, 4]} intensity={1.4} color={EMBER} />
      <pointLight position={[-3, -2, -3]} intensity={0.5} color={CRIMSON} />

      <Float speed={1.4} rotationIntensity={0.25} floatIntensity={0.6}>
        <MoltenCore interactive={interactive} intensity={intensity} />
      </Float>

      <Sparkles
        count={40}
        scale={3.4}
        size={2.4}
        speed={0.25}
        opacity={0.55}
        color={emberColor}
      />
    </>
  );
}

export default function IgnitionCore({
  size = 360,
  interactive = false,
  intensity = 1,
  style = {},
  className = "",
}) {
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        cursor: interactive ? "grab" : "default",
        ...style,
      }}
      aria-hidden="true"
    >
      <Canvas
        camera={{ position: [0, 0, 4.2], fov: 40 }}
        dpr={[1, 1.75]}
        gl={{ alpha: true, antialias: true }}
      >
        <Suspense fallback={null}>
          <Scene interactive={interactive} intensity={intensity} />
        </Suspense>
      </Canvas>
    </div>
  );
}
