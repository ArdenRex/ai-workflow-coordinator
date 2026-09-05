// src/components/AuthShell.jsx
//
// Shared split-screen layout for Auth + Onboarding: a fixed left hero
// panel carrying the 3D Ignition Core and page-specific copy, and a
// scrollable right panel that hosts the actual form card (passed as
// children — the card markup/logic in AuthPage/OnboardingPage is
// otherwise untouched).
//
// This is the "first impression" upgrade: instead of a generic centered
// card on a dark background (what every other SaaS auth page looks
// like), the product's signature visual greets you immediately.
//
// Collapses to a single column below 980px — the 3D hero is not worth
// its render cost on small screens, so it's simply not mounted there.

import React from "react";
import { motion } from "framer-motion";
import EmberOrb from "./EmberOrb";
import { fadeUpItem, staggerContainer } from "../motion/variants";

const SHELL_STYLES = `
  .shell-root {
    min-height: 100vh;
    display: flex;
    background: #0a0706;
    font-family: 'Inter', system-ui, sans-serif;
  }

  .shell-hero {
    position: relative;
    flex: 0 0 44%;
    max-width: 620px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 48px 56px;
    overflow: hidden;
    background:
      radial-gradient(circle at 30% 20%, rgba(255,106,82,0.10) 0%, transparent 55%),
      radial-gradient(circle at 70% 85%, rgba(200,31,48,0.09) 0%, transparent 60%),
      linear-gradient(180deg, #0c0908 0%, #060403 100%);
    border-right: 1px solid rgba(255,255,255,0.06);
  }

  .shell-hero::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
    pointer-events: none;
  }

  .shell-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    position: relative;
    z-index: 1;
  }

  .shell-brand-icon {
    width: 34px; height: 34px;
    border-radius: 9px;
    background: linear-gradient(135deg, #ff6a52 0%, #c81f30 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; color: #f5f0eb;
    box-shadow: 0 0 20px rgba(255,106,82,0.4);
    flex-shrink: 0;
  }

  .shell-brand-text {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px; font-weight: 600;
    color: #efe7df;
  }
  .shell-brand-sub { font-size: 10.5px; color: #6b6058; margin-top: 1px; }

  .shell-core-wrap {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 12px 0;
  }

  .shell-copy { position: relative; z-index: 1; }

  .shell-eyebrow {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 12px; font-weight: 600;
    color: #ff9478;
    margin-bottom: 10px;
  }

  .shell-headline {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 27px; font-weight: 600;
    line-height: 1.28;
    letter-spacing: -0.01em;
    color: #f5f0eb;
    max-width: 420px;
    margin-bottom: 14px;
  }

  .shell-subtext {
    font-size: 13.5px;
    line-height: 1.6;
    color: #9a908a;
    max-width: 380px;
  }

  .shell-right {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px 24px 96px;
    position: relative;
  }

  @media (max-width: 980px) {
    .shell-hero { display: none; }
    .shell-right { padding: 32px 16px 90px; }
  }
`;

export default function AuthShell({ eyebrow, headline, subtext, children }) {
  return (
    <>
      <style>{SHELL_STYLES}</style>
      <div className="shell-root">
        <motion.div
          className="shell-hero"
          initial="hidden"
          animate="show"
          variants={staggerContainer}
        >
          <motion.div className="shell-brand" variants={fadeUpItem}>
            <div className="shell-brand-icon">AI</div>
            <div>
              <div className="shell-brand-text">AI Workflow</div>
              <div className="shell-brand-sub">Coordinator</div>
            </div>
          </motion.div>

          <motion.div className="shell-core-wrap" variants={fadeUpItem}>
            <EmberOrb size={280} interactive />
          </motion.div>

          <motion.div className="shell-copy" variants={fadeUpItem}>
            {eyebrow && <div className="shell-eyebrow">{eyebrow}</div>}
            <div className="shell-headline">{headline}</div>
            <div className="shell-subtext">{subtext}</div>
          </motion.div>
        </motion.div>

        <div className="shell-right">{children}</div>
      </div>
    </>
  );
}
