// src/three/IgnitionPreview.jsx
//
// Temporary, isolated smoke-test screen for Step 1 (foundation). Not
// wired into AppRouter — reached only via ?preview=ignition so it can't
// affect the real app. Safe to delete once Step 1 is approved and we
// move into Step 2 (Auth page).

import React from "react";
import { motion } from "framer-motion";
import IgnitionCore from "./IgnitionCore";
import useTilt3D from "../motion/useTilt3D";
import { staggerContainer, fadeUpItem } from "../motion/variants";

function DemoCard({ title, body }) {
  const { ref, style, glareStyle, onPointerMove, onPointerLeave } = useTilt3D();
  return (
    <motion.div
      variants={fadeUpItem}
      ref={ref}
      style={{
        ...style,
        position: "relative",
        width: 240,
        padding: "20px 18px",
        borderRadius: 16,
        background: "rgba(255,255,255,0.032)",
        border: "1px solid rgba(255,255,255,0.072)",
        overflow: "hidden",
      }}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
    >
      <div
        style={{ position: "absolute", inset: 0, pointerEvents: "none", ...glareStyle }}
      />
      <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 600, fontSize: 15, color: "#f5f0eb", marginBottom: 6 }}>
        {title}
      </div>
      <div style={{ fontFamily: "'Inter', sans-serif", fontSize: 12.5, color: "#9a908a", lineHeight: 1.5 }}>
        {body}
      </div>
    </motion.div>
  );
}

export default function IgnitionPreview() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0706",
        color: "#f5f0eb",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 40,
        padding: 40,
        fontFamily: "'Inter', sans-serif",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 13, letterSpacing: 0.4, color: "#9a908a", marginBottom: 4 }}>
          Step 1 — Foundation smoke test
        </div>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 22, fontWeight: 600 }}>
          Ignition Core + tilt cards + motion system
        </div>
      </div>

      <IgnitionCore size={340} interactive />

      <div style={{ fontSize: 12, color: "#655c56", marginTop: -20 }}>
        drag the core to spin it — it settles back to its own drift
      </div>

      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="show"
        style={{ display: "flex", gap: 20, flexWrap: "wrap", justifyContent: "center", maxWidth: 800 }}
      >
        <DemoCard title="Cursor tilt" body="Move your pointer over this card — real perspective transform tracking cursor position, not a canned hover." />
        <DemoCard title="Orchestrated entrance" body="These three cards staggered in as one sequence on load, using the shared motion variants." />
        <DemoCard title="Shared tokens" body="Same Ignition palette, Space Grotesk / Inter pairing, and easing curve as the rest of the app." />
      </motion.div>
    </div>
  );
}
