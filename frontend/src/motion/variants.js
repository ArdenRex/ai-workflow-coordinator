// src/motion/variants.js
//
// Shared framer-motion presets so every screen's "one orchestrated
// entrance" uses the same rhythm instead of ad-hoc animations per page.
// Easing matches the cubic-bezier already used in GLOBAL_STYLES
// (fadeUp/scaleIn/slideIn) so old CSS animations and new framer-motion
// ones feel like the same hand.

export const EASE = [0.16, 1, 0.3, 1]; // matches cubic-bezier(0.16,1,0.3,1)

// Wrap a page/section root with this + `initial="hidden" animate="show"`
// and give each direct child `variants={fadeUpItem}` to get a single
// staggered reveal — the "one orchestrated moment" pattern, not
// per-card scroll-triggered fades.
export const staggerContainer = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.06,
      delayChildren: 0.04,
    },
  },
};

export const fadeUpItem = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: EASE },
  },
};

export const scaleInItem = {
  hidden: { opacity: 0, scale: 0.96 },
  show: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.4, ease: EASE },
  },
};

// For route/tab transitions — a soft cross-fade + rise, applied once at
// the page-container level.
export const pageTransition = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.25, ease: EASE } },
};

// Backdrop fade for any full-screen overlay (modals, drawers). Pair with
// AnimatePresence so the exit plays instead of an instant unmount.
export const overlayFade = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.2, ease: EASE } },
  exit: { opacity: 0, transition: { duration: 0.15, ease: EASE } },
};

// Side-drawer enter/exit — slides in from the right edge.
export const drawerSlide = {
  initial: { opacity: 0, x: 48 },
  animate: { opacity: 1, x: 0, transition: { duration: 0.35, ease: EASE } },
  exit: { opacity: 0, x: 32, transition: { duration: 0.2, ease: EASE } },
};

// Modal/panel enter — scale + rise, tuned to feel weighted rather than
// snappy-generic. Adds a slight 3D rotateX "tilt down into place" pop
// (paired with a perspective on the wrapper) so modals read as part of
// the same dimensional language as the tilt cards and Ignition core,
// not a flat 2D overlay.
export const modalTransition = {
  initial: { opacity: 0, scale: 0.94, y: 12, rotateX: -8, transformPerspective: 1000 },
  animate: {
    opacity: 1,
    scale: 1,
    y: 0,
    rotateX: 0,
    transformPerspective: 1000,
    transition: { duration: 0.35, ease: EASE },
  },
  exit: {
    opacity: 0,
    scale: 0.96,
    y: 8,
    rotateX: -4,
    transformPerspective: 1000,
    transition: { duration: 0.2, ease: EASE },
  },
};
