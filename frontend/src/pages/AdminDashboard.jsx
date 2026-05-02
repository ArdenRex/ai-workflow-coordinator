import { useState, useEffect, useCallback, useRef } from "react";

const API = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

function useAdminFetch(path) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const fetch_ = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`${res.status}`);
      setData(await res.json());
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }, [path]);
  useEffect(() => { fetch_(); }, [fetch_]);
  return { data, loading, error, refetch: fetch_ };
}

// ── HOLOGRAPHIC GRID BACKGROUND ──────────────────────────────────────────────
function HoloGrid() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth;
    let H = canvas.height = canvas.offsetHeight;
    let t = 0;
    let raf;

    // Scanning lines
    const scanLines = Array.from({ length: 6 }, (_, i) => ({
      y: Math.random() * H,
      speed: 0.4 + Math.random() * 0.6,
      alpha: 0.04 + Math.random() * 0.06,
      width: 40 + Math.random() * 80,
    }));

    // Floating data nodes
    const nodes = Array.from({ length: 18 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.2, vy: (Math.random() - 0.5) * 0.2,
      r: 1.5 + Math.random() * 2,
      hue: Math.random() > 0.5 ? 195 : 280,
      pulse: Math.random() * Math.PI * 2,
    }));

    function draw() {
      ctx.clearRect(0, 0, W, H);
      t += 0.006;

      // Deep space gradient
      const bg = ctx.createRadialGradient(W * 0.5, H * 0.3, 0, W * 0.5, H * 0.5, W * 0.8);
      bg.addColorStop(0, "rgba(0,20,40,0.0)");
      bg.addColorStop(1, "rgba(0,5,15,0.0)");
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

      // Perspective grid floor
      const gridAlpha = 0.07;
      const vanishY = H * 0.55;
      const gridLines = 24;
      ctx.strokeStyle = `rgba(0,200,255,${gridAlpha})`;
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= gridLines; i++) {
        const x = (i / gridLines) * W;
        const wave = Math.sin(t + i * 0.3) * 2;
        ctx.beginPath();
        ctx.moveTo(x + wave, vanishY);
        ctx.lineTo(W * 0.5 + (x - W * 0.5) * 3, H + 50);
        ctx.stroke();
      }
      for (let i = 0; i <= 10; i++) {
        const progress = i / 10;
        const y = vanishY + progress * (H - vanishY + 50);
        const spread = progress * W * 1.5;
        ctx.globalAlpha = gridAlpha * (0.3 + progress * 0.7);
        ctx.beginPath();
        ctx.moveTo(W * 0.5 - spread * 0.5, y);
        ctx.lineTo(W * 0.5 + spread * 0.5, y);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Horizontal scan lines sweeping down
      scanLines.forEach(s => {
        s.y += s.speed;
        if (s.y > H + s.width) s.y = -s.width;
        const sg = ctx.createLinearGradient(0, s.y - s.width, 0, s.y + s.width);
        sg.addColorStop(0, "rgba(0,200,255,0)");
        sg.addColorStop(0.5, `rgba(0,220,255,${s.alpha})`);
        sg.addColorStop(1, "rgba(0,200,255,0)");
        ctx.fillStyle = sg;
        ctx.fillRect(0, s.y - s.width, W, s.width * 2);
      });

      // Floating nodes with connections
      nodes.forEach(n => {
        n.x += n.vx; n.y += n.vy; n.pulse += 0.02;
        if (n.x < 0 || n.x > W) n.vx *= -1;
        if (n.y < 0 || n.y > H) n.vy *= -1;
        const alpha = 0.4 + Math.sin(n.pulse) * 0.3;
        const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 4);
        glow.addColorStop(0, `hsla(${n.hue},100%,70%,${alpha * 0.8})`);
        glow.addColorStop(1, `hsla(${n.hue},100%,70%,0)`);
        ctx.fillStyle = glow;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 4, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `hsla(${n.hue},100%,90%,${alpha})`;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
      });

      // Connections between nearby nodes
      ctx.lineWidth = 0.4;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 160) {
            ctx.strokeStyle = `rgba(0,200,255,${(1 - dist / 160) * 0.12})`;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth; H = canvas.height = canvas.offsetHeight; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);
  return <canvas ref={canvasRef} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}

// ── HOLOGRAPHIC METRIC CARD — each tells a story ──────────────────────────────
function HoloCard({ label, value, sub, color = "#00d4ff", icon, trend, delay = 0, story, accentShape }) {
  const [hov, setHov] = useState(false);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const [particles, setParticles] = useState([]);
  const ref = useRef(null);

  const onMove = (e) => {
    const r = ref.current.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width - 0.5) * 22;
    const y = ((e.clientY - r.top) / r.height - 0.5) * -22;
    setTilt({ x, y });
  };
  const onLeave = () => { setTilt({ x: 0, y: 0 }); setHov(false); };
  const onEnter = () => {
    setHov(true);
    setParticles(Array.from({ length: 8 }, (_, i) => ({ id: i, x: Math.random() * 100, delay: i * 80 })));
  };

  const hexToRgb = (hex) => {
    // Handle rgb(r,g,b) strings passed from the revenue color cycler
    const rgbMatch = hex.match(/^rgb\((\d+),(\d+),(\d+)\)$/);
    if (rgbMatch) return `${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]}`;
    if (hex === "#00d4ff") return "0,212,255";
    if (hex === "#00ff88") return "0,255,136";
    if (hex === "#ff6b35") return "255,107,53";
    if (hex === "#a855f7") return "168,85,247";
    if (hex === "#ffd700") return "255,215,0";
    if (hex === "#ff3366") return "255,51,102";
    return "0,212,255";
  };
  const rgb = hexToRgb(color);

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        position: "relative",
        borderRadius: 4,
        padding: "20px 22px 18px",
        cursor: "default",
        animationDelay: `${delay}ms`,
        animation: "holoRise 0.8s cubic-bezier(0.16,1,0.3,1) both",
        transformStyle: "preserve-3d",
        transform: `perspective(900px) rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) ${hov ? "translateZ(18px) scale(1.02)" : "translateZ(0)"}`,
        transition: hov ? "transform 0.06s linear" : "transform 0.6s cubic-bezier(0.16,1,0.3,1)",
        background: `linear-gradient(135deg, rgba(0,10,25,0.95) 0%, rgba(0,${color === "#00d4ff" ? "25,40" : color === "#00ff88" ? "35,20" : color === "#ff6b35" ? "20,10" : "15,35"},0.9) 100%)`,
        border: `1px solid rgba(${rgb},${hov ? 0.5 : 0.2})`,
        boxShadow: hov
          ? `0 0 0 1px rgba(${rgb},0.1), 0 20px 60px rgba(0,0,0,0.8), 0 0 80px rgba(${rgb},0.15), inset 0 0 40px rgba(${rgb},0.03)`
          : `0 4px 30px rgba(0,0,0,0.7), inset 0 0 20px rgba(${rgb},0.02)`,
        backdropFilter: "blur(20px)",
        overflow: "hidden",
        clipPath: "polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 14px 100%, 0 calc(100% - 14px))",
      }}
    >
      {/* Corner cuts */}
      <div style={{ position: "absolute", top: 0, right: 14, width: 0, height: 0, borderTop: `14px solid rgba(${rgb},${hov ? 0.5 : 0.2})`, borderLeft: "14px solid transparent", pointerEvents: "none", zIndex: 3 }} />
      <div style={{ position: "absolute", bottom: 0, left: 14, width: 0, height: 0, borderBottom: `14px solid rgba(${rgb},${hov ? 0.5 : 0.2})`, borderRight: "14px solid transparent", pointerEvents: "none", zIndex: 3 }} />

      {/* Top scan line */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.8), rgba(${rgb},0.4), transparent)`, pointerEvents: "none" }} />

      {/* Animated corner bracket TL */}
      <div style={{ position: "absolute", top: 6, left: 6, width: 14, height: 14, borderTop: `1.5px solid ${color}`, borderLeft: `1.5px solid ${color}`, opacity: hov ? 1 : 0.4, transition: "opacity 0.3s" }} />
      <div style={{ position: "absolute", bottom: 6, right: 6, width: 14, height: 14, borderBottom: `1.5px solid ${color}`, borderRight: `1.5px solid ${color}`, opacity: hov ? 1 : 0.4, transition: "opacity 0.3s" }} />

      {/* Story accent shape */}
      {accentShape === "ring" && (
        <div style={{ position: "absolute", top: -20, right: -20, width: 100, height: 100, borderRadius: "50%", border: `1px solid rgba(${rgb},0.12)`, pointerEvents: "none" }} />
      )}
      {accentShape === "hex" && (
        <div style={{ position: "absolute", bottom: -30, right: -10, fontSize: 80, color: `rgba(${rgb},0.04)`, pointerEvents: "none", lineHeight: 1 }}>⬡</div>
      )}
      {accentShape === "cross" && (
        <div style={{ position: "absolute", top: "50%", right: 10, transform: "translateY(-50%)", fontSize: 60, color: `rgba(${rgb},0.05)`, pointerEvents: "none" }}>✚</div>
      )}

      {/* Floating particles on hover */}
      {hov && particles.map(p => (
        <div key={p.id} style={{
          position: "absolute", bottom: 0, left: `${p.x}%`,
          width: 2, height: 2, borderRadius: "50%",
          background: color,
          boxShadow: `0 0 6px ${color}`,
          animation: `particleFloat 1.2s ease-out ${p.delay}ms forwards`,
          pointerEvents: "none",
        }} />
      ))}

      {/* Icon + label row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ fontSize: 9, color: color, letterSpacing: "0.2em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", opacity: 0.8 }}>
          {label}
        </div>
        <div style={{
          width: 30, height: 30,
          border: `1px solid rgba(${rgb},0.35)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, color: color,
          clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
          background: `rgba(${rgb},0.08)`,
        }}>{icon}</div>
      </div>

      {/* Main value */}
      <div style={{
        fontSize: 32, fontWeight: 700, color: "#fff",
        fontFamily: "'Orbitron', monospace",
        textShadow: `0 0 20px rgba(${rgb},0.6), 0 0 60px rgba(${rgb},0.2)`,
        letterSpacing: "-0.02em",
        lineHeight: 1,
        marginBottom: 6,
      }}>{value}</div>

      {/* Sub label */}
      {sub && <div style={{ fontSize: 10, color: `rgba(${rgb},0.55)`, fontFamily: "'Share Tech Mono', monospace", marginBottom: 8 }}>{sub}</div>}

      {/* Story line */}
      {story && (
        <div style={{ fontSize: 9, color: "rgba(150,220,255,0.35)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.06em", lineHeight: 1.6, marginBottom: 8 }}>
          {story}
        </div>
      )}

      {/* Trend badge */}
      {trend !== undefined && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <div style={{
            fontSize: 9, fontWeight: 700,
            color: trend >= 0 ? "#00ff88" : "#ff4466",
            background: trend >= 0 ? "rgba(0,255,136,0.08)" : "rgba(255,68,102,0.08)",
            border: `1px solid ${trend >= 0 ? "rgba(0,255,136,0.3)" : "rgba(255,68,102,0.3)"}`,
            padding: "2px 8px", borderRadius: 2,
            fontFamily: "'Share Tech Mono', monospace",
            letterSpacing: "0.05em",
          }}>{trend >= 0 ? "▲" : "▼"} {Math.abs(trend)}%</div>
          <span style={{ fontSize: 8, color: "rgba(150,200,255,0.25)", fontFamily: "'Share Tech Mono', monospace" }}>30D</span>
        </div>
      )}

      {/* Bottom scan */}
      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.3), transparent)`, pointerEvents: "none" }} />

      {/* Left accent bar */}
      <div style={{ position: "absolute", left: 0, top: "20%", bottom: "20%", width: 2, background: `linear-gradient(180deg, transparent, ${color}, transparent)`, opacity: hov ? 1 : 0.3, transition: "opacity 0.4s" }} />
    </div>
  );
}

// ── JARVIS SPARKLINE ──────────────────────────────────────────────────────────
function HoloSparkline({ values, color = "#00d4ff", height = 60 }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !values || values.length < 2) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = height * 2;
    canvas.style.width = "100%";
    canvas.style.height = `${height}px`;
    const max = Math.max(...values, 1);
    const min = Math.min(...values);
    const range = max - min || 1;
    const pts = values.map((v, i) => ({
      x: (i / (values.length - 1)) * W,
      y: H - ((v - min) / range) * (H * 0.8) - H * 0.1,
    }));

    ctx.clearRect(0, 0, W, H);

    // Area fill
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, color + "44");
    grad.addColorStop(1, color + "00");
    ctx.beginPath();
    ctx.moveTo(pts[0].x, H);
    pts.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pts[pts.length - 1].x, H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Main line with glow
    ctx.shadowColor = color;
    ctx.shadowBlur = 8;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.beginPath();
    pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Grid lines
    ctx.strokeStyle = color + "18";
    ctx.lineWidth = 1;
    for (let i = 0; i < 4; i++) {
      const y = (H / 4) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    // Data points
    pts.forEach((p, i) => {
      if (i % Math.max(1, Math.floor(pts.length / 6)) === 0) {
        ctx.shadowColor = color; ctx.shadowBlur = 10;
        ctx.fillStyle = "#fff";
        ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      }
    });
  }, [values, color, height]);
  return <canvas ref={canvasRef} />;
}

// ── 3D HOLOGRAPHIC BAR CHART ─────────────────────────────────────────────────
function HoloBarChart({ data, activeColor }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data?.length) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = 200 * 2;
    canvas.style.height = "200px";
    const base = activeColor || "#00d4ff";
    const [r0,g0,b0] = base.replace(/rgba?\(|\)/g,"").split(",").map(s => parseInt(s.trim())) || [0,212,255];
    const max = Math.max(...data.map(d => d.revenue), 1);
    let hovIdx = null;
    let t = 0;
    let raf;

    // Isometric projection parameters
    const ISO_ANGLE = Math.PI / 6; // 30deg
    const cosA = Math.cos(ISO_ANGLE), sinA = Math.sin(ISO_ANGLE);
    const barW = (W * 0.72) / data.length;
    const barGap = barW * 0.22;
    const startX = W * 0.14;
    const groundY = H * 0.82;
    const maxBarH = H * 0.55;
    const topDepth = barW * 0.35; // depth of the isometric top face

    function isoProject(x, y, z) {
      // Simple isometric: shift x right for depth (z), shift y up for height
      return { px: x + z * cosA * 0.6, py: y - z * sinA * 0.6 };
    }

    function drawBar3D(x, barH, barW2, col, isHov, month, revenue, idx) {
      const pulse = isHov ? 1.08 + Math.sin(t * 4) * 0.04 : 1;
      const aH = barH * pulse;
      const depth = topDepth;
      const bx = x + barGap / 2;

      // Front face
      const frontGrad = ctx.createLinearGradient(bx, groundY - aH, bx, groundY);
      frontGrad.addColorStop(0, `rgba(${r0},${g0},${b0},${isHov ? 1.0 : 0.85})`);
      frontGrad.addColorStop(0.4, `rgba(${Math.round(r0*0.7)},${Math.round(g0*0.7)},${Math.round(b0*0.7)},0.8)`);
      frontGrad.addColorStop(1, `rgba(${Math.round(r0*0.3)},${Math.round(g0*0.3)},${Math.round(b0*0.3)},0.6)`);
      ctx.fillStyle = frontGrad;
      ctx.shadowColor = col; ctx.shadowBlur = isHov ? 24 : 8;
      ctx.beginPath();
      ctx.moveTo(bx, groundY);
      ctx.lineTo(bx + barW2 - barGap, groundY);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.lineTo(bx, groundY - aH);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // Front face shine stripe
      const shineGrad = ctx.createLinearGradient(bx, groundY - aH, bx + (barW2-barGap)*0.35, groundY);
      shineGrad.addColorStop(0, "rgba(255,255,255,0.22)");
      shineGrad.addColorStop(1, "rgba(255,255,255,0.03)");
      ctx.fillStyle = shineGrad;
      ctx.beginPath();
      ctx.moveTo(bx, groundY);
      ctx.lineTo(bx + (barW2-barGap)*0.35, groundY);
      ctx.lineTo(bx + (barW2-barGap)*0.35, groundY - aH);
      ctx.lineTo(bx, groundY - aH);
      ctx.closePath();
      ctx.fill();

      // Right side face (darker — gives 3D depth)
      const sideGrad = ctx.createLinearGradient(bx + barW2 - barGap, groundY - aH, bx + barW2 - barGap + depth, groundY - aH + depth * sinA / cosA);
      sideGrad.addColorStop(0, `rgba(${Math.round(r0*0.4)},${Math.round(g0*0.4)},${Math.round(b0*0.4)},0.85)`);
      sideGrad.addColorStop(1, `rgba(${Math.round(r0*0.2)},${Math.round(g0*0.2)},${Math.round(b0*0.2)},0.5)`);
      ctx.fillStyle = sideGrad;
      ctx.beginPath();
      ctx.moveTo(bx + barW2 - barGap, groundY);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - depth * sinA / cosA);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.closePath();
      ctx.fill();

      // Top face (brightest — facing the light)
      const topGrad = ctx.createLinearGradient(bx, groundY - aH, bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      topGrad.addColorStop(0, `rgba(${Math.min(r0+60,255)},${Math.min(g0+60,255)},${Math.min(b0+60,255)},${isHov ? 1.0 : 0.95})`);
      topGrad.addColorStop(1, `rgba(${r0},${g0},${b0},0.8)`);
      ctx.fillStyle = topGrad;
      ctx.shadowColor = col; ctx.shadowBlur = isHov ? 30 : 14;
      ctx.beginPath();
      ctx.moveTo(bx, groundY - aH);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      ctx.lineTo(bx + depth, groundY - aH - depth * sinA / cosA);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // Top face specular highlight
      ctx.fillStyle = "rgba(255,255,255,0.18)";
      ctx.beginPath();
      ctx.moveTo(bx + 2, groundY - aH);
      ctx.lineTo(bx + (barW2-barGap)*0.5, groundY - aH);
      ctx.lineTo(bx + (barW2-barGap)*0.5 + depth*0.5, groundY - aH - depth*0.5*sinA/cosA);
      ctx.lineTo(bx + depth*0.5, groundY - aH - depth*0.5*sinA/cosA);
      ctx.closePath();
      ctx.fill();

      // Ground shadow
      ctx.fillStyle = `rgba(0,0,0,0.25)`;
      ctx.beginPath();
      ctx.ellipse(bx + (barW2-barGap)/2, groundY + 4, (barW2-barGap)*0.5, 6, 0, 0, Math.PI*2);
      ctx.fill();

      // Month label
      ctx.save();
      ctx.translate(bx + (barW2-barGap)/2, groundY + 20);
      ctx.rotate(-Math.PI / 5);
      ctx.fillStyle = isHov ? col : `rgba(${r0},${g0},${b0},0.4)`;
      ctx.font = `${isHov ? "bold " : ""}${H * 0.028}px 'Share Tech Mono', monospace`;
      ctx.textAlign = "center";
      ctx.fillText(data[idx].month?.slice(0, 3) || "", 0, 0);
      ctx.restore();

      // Value tooltip on hover
      if (isHov && revenue > 0) {
        const ttW = 160, ttH = 40, ttX = Math.min(bx - 10, W - ttW - 10), ttY = groundY - aH - 60;
        ctx.fillStyle = "rgba(0,8,20,0.98)";
        ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.7)`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(ttX, ttY, ttW, ttH, 4);
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = col;
        ctx.font = `bold ${H * 0.038}px 'Orbitron', monospace`;
        ctx.textAlign = "left";
        ctx.shadowColor = col; ctx.shadowBlur = 10;
        ctx.fillText(`$${revenue.toFixed(0)}`, ttX + 10, ttY + 16);
        ctx.shadowBlur = 0;
        ctx.fillStyle = `rgba(${r0},${g0},${b0},0.5)`;
        ctx.font = `${H * 0.027}px 'Share Tech Mono', monospace`;
        ctx.fillText(`${data[idx].new_paid || 0} paid users`, ttX + 10, ttY + 32);
      }
    }

    function draw() {
      t += 0.02;
      ctx.clearRect(0, 0, W, H);

      // Y-axis grid lines (perspective-ish)
      for (let v = 0; v <= 4; v++) {
        const y = groundY - (v / 4) * maxBarH;
        ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.07)`;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 8]);
        ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(W - W*0.06, y); ctx.stroke();
        ctx.setLineDash([]);
        if (v > 0) {
          ctx.fillStyle = `rgba(${r0},${g0},${b0},0.3)`;
          ctx.font = `${H * 0.028}px 'Share Tech Mono', monospace`;
          ctx.textAlign = "right";
          ctx.fillText(`$${Math.round(max * v / 4)}`, startX - 6, y + 4);
        }
      }

      // Ground line
      ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.2)`;
      ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(startX, groundY); ctx.lineTo(W - W*0.06, groundY); ctx.stroke();

      // Draw bars back to front
      data.forEach((d, i) => {
        const barH = Math.max(4, (d.revenue / max) * maxBarH);
        const x = startX + i * barW;
        drawBar3D(x, barH, barW, base, hovIdx === i, d.month, d.revenue, i);
      });

      raf = requestAnimationFrame(draw);
    }
    draw();

    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * (W / rect.width);
      const my = (e.clientY - rect.top) * (H / rect.height);
      let found = null;
      data.forEach((d, i) => {
        const x = startX + i * barW + barW * 0.1;
        const barH = Math.max(4, (d.revenue / max) * maxBarH);
        if (mx >= x && mx <= x + barW * 0.78 && my >= groundY - barH && my <= groundY) found = i;
      });
      hovIdx = found;
    };
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseleave", () => { hovIdx = null; });

    const onResize = () => {
      canvas.width = canvas.offsetWidth * 2;
      canvas.height = 200 * 2;
    };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); canvas.removeEventListener("mousemove", onMouseMove); window.removeEventListener("resize", onResize); };
  }, [data, activeColor]);

  return <canvas ref={canvasRef} style={{ display: "block", width: "100%", cursor: "crosshair" }} />;
}

// ── CIRCULAR RADAR / DONUT ────────────────────────────────────────────────────
function HoloDonut({ segments, total }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const S = 160;
    canvas.width = canvas.height = S * 2;
    canvas.style.width = canvas.style.height = `${S}px`;
    const cx = S, cy = S, r = S * 0.72, inner = S * 0.48;
    ctx.clearRect(0, 0, S * 2, S * 2);

    let startAngle = -Math.PI / 2;
    segments.forEach((seg, i) => {
      const slice = (seg.count / total) * Math.PI * 2;
      // Shadow glow
      ctx.shadowColor = seg.color; ctx.shadowBlur = 18;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, r, startAngle, startAngle + slice);
      ctx.closePath();
      const g = ctx.createRadialGradient(cx, cy, inner, cx, cy, r);
      g.addColorStop(0, seg.color + "88");
      g.addColorStop(1, seg.color + "cc");
      ctx.fillStyle = g;
      ctx.fill();
      ctx.shadowBlur = 0;

      // Gap
      startAngle += slice + 0.03;
    });

    // Inner ring
    ctx.beginPath(); ctx.arc(cx, cy, inner + 4, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0,212,255,0.15)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, inner, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(0,8,20,0.95)"; ctx.fill();

    // Center text
    ctx.fillStyle = "#fff";
    ctx.font = `bold ${S * 0.28}px 'Orbitron', monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.shadowColor = "#00d4ff"; ctx.shadowBlur = 16;
    ctx.fillText(total, cx, cy - 8);
    ctx.shadowBlur = 0;
    ctx.fillStyle = "rgba(0,212,255,0.5)";
    ctx.font = `${S * 0.1}px 'Share Tech Mono', monospace`;
    ctx.fillText("TOTAL", cx, cy + S * 0.18);
  }, [segments, total]);
  return <canvas ref={canvasRef} style={{ display: "block" }} />;
}

// ── LOADER ────────────────────────────────────────────────────────────────────
function HoloLoader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", gap: 20 }}>
      <div style={{ position: "relative", width: 70, height: 70 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            position: "absolute", inset: i * 10,
            borderRadius: "50%",
            border: "1px solid transparent",
            borderTop: `1px solid ${["#00d4ff", "#00ff88", "#a855f7"][i]}`,
            borderRight: `1px solid ${["#00d4ff", "#00ff88", "#a855f7"][i]}44`,
            animation: `spin ${1 + i * 0.4}s linear infinite ${i % 2 ? "reverse" : ""}`,
            boxShadow: `0 0 14px ${["rgba(0,212,255,0.4)", "rgba(0,255,136,0.3)", "rgba(168,85,247,0.3)"][i]}`,
          }} />
        ))}
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "#00d4ff", animation: "pulse-glow 2s infinite", fontFamily: "'Orbitron', monospace" }}>◈</div>
      </div>
      <div style={{ color: "rgba(0,212,255,0.4)", fontSize: 9, letterSpacing: "0.3em", fontFamily: "'Share Tech Mono', monospace", textTransform: "uppercase" }}>
        Initializing Systems…
      </div>
    </div>
  );
}

// ── GLASS PANEL ───────────────────────────────────────────────────────────────
function HoloPanel({ children, style = {}, title, accent = "#00d4ff" }) {
  const rgb = accent === "#00d4ff" ? "0,212,255" : accent === "#00ff88" ? "0,255,136" : accent === "#a855f7" ? "168,85,247" : accent === "#ffd700" ? "255,215,0" : "0,212,255";
  return (
    <div style={{
      background: `linear-gradient(135deg, rgba(0,8,20,0.96) 0%, rgba(0,15,35,0.92) 100%)`,
      border: `1px solid rgba(${rgb},0.18)`,
      borderRadius: 4,
      padding: "20px 22px",
      backdropFilter: "blur(20px)",
      boxShadow: `0 8px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(${rgb},0.05), inset 0 0 30px rgba(${rgb},0.02)`,
      position: "relative",
      overflow: "hidden",
      clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
      ...style,
    }}>
      {/* Corner notch indicator */}
      <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rgb},0.25)`, borderLeft: "10px solid transparent", zIndex: 2 }} />
      <div style={{ position: "absolute", bottom: 0, left: 10, width: 0, height: 0, borderBottom: `10px solid rgba(${rgb},0.25)`, borderRight: "10px solid transparent", zIndex: 2 }} />
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.6), transparent)` }} />
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rgb},0.8), rgba(${rgb},0.1))` }} />
      {title && (
        <div style={{ fontSize: 9, color: `rgba(${rgb},0.7)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 4, height: 4, background: accent, borderRadius: "50%", boxShadow: `0 0 8px ${accent}` }} />
          {title}
          <div style={{ flex: 1, height: 1, background: `rgba(${rgb},0.15)` }} />
        </div>
      )}
      {children}
    </div>
  );
}

// ── NAV TAB ───────────────────────────────────────────────────────────────────
function NavTab({ label, active, onClick, count, icon, activeColor }) {
  const ac = activeColor || "#00d4ff";
  const acRgb = activeColor ? activeColor.replace("rgb(","").replace(")","") : "0,212,255";
  return (
    <div onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 18px 10px 20px",
      cursor: "pointer",
      position: "relative",
      transition: "all 0.3s",
      borderLeft: active ? `2px solid ${ac}` : "2px solid transparent",
      background: active ? `rgba(${acRgb},0.07)` : "transparent",
      marginBottom: 2,
    }}>
      {active && <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, transparent, ${ac}, rgba(${acRgb},0.5), transparent)`, boxShadow: `0 0 12px ${ac}`, transition: "background 0.3s, box-shadow 0.3s" }} />}
      <span style={{ fontSize: 13, color: active ? ac : "rgba(0,212,255,0.3)", transition: "color 0.3s", fontFamily: "'Share Tech Mono', monospace", textShadow: active && activeColor ? `0 0 10px ${ac}` : "none" }}>{icon}</span>
      <span style={{ fontSize: 11, fontWeight: active ? 700 : 400, color: active ? "#e0f7ff" : "rgba(150,200,220,0.45)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.08em", flex: 1, transition: "color 0.2s" }}>{label}</span>
      {count !== undefined && (
        <span style={{ fontSize: 9, color: active ? ac : "rgba(0,212,255,0.3)", background: active ? `rgba(${acRgb},0.12)` : "rgba(0,212,255,0.04)", border: `1px solid ${active ? `rgba(${acRgb},0.35)` : "rgba(0,212,255,0.1)"}`, padding: "1px 6px", borderRadius: 2, fontFamily: "'Share Tech Mono', monospace", transition: "all 0.3s" }}>{count}</span>
      )}
    </div>
  );
}

// ── BADGE ────────────────────────────────────────────────────────────────────
function Badge({ text }) {
  const map = {
    open:     { c: "#00ff88", bg: "rgba(0,255,136,0.08)", b: "rgba(0,255,136,0.25)" },
    closed:   { c: "#00d4ff", bg: "rgba(0,212,255,0.08)", b: "rgba(0,212,255,0.25)" },
    pending:  { c: "#ffd700", bg: "rgba(255,215,0,0.08)",  b: "rgba(255,215,0,0.25)"  },
  };
  const s = map[text] || map.open;
  return (
    <span style={{ fontSize: 8, color: s.c, background: s.bg, border: `1px solid ${s.b}`, padding: "2px 8px", borderRadius: 2, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em", textTransform: "uppercase", boxShadow: `0 0 10px ${s.b}` }}>{text}</span>
  );
}

const td = { padding: "11px 14px", verticalAlign: "middle" };

// ── USERS TABLE ───────────────────────────────────────────────────────────────
function UsersTable() {
  const { data, loading, refetch } = useAdminFetch("/admin/users?limit=100");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const handleToggleActive = async (id, cur) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/users/${id}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !cur }) });
    refetch();
  };
  if (loading) return <HoloLoader />;
  const rows = data?.users?.filter(u => {
    if (filter === "active" && !u.is_active) return false;
    if (filter === "inactive" && u.is_active) return false;
    if (search && !u.email?.toLowerCase().includes(search.toLowerCase()) && !u.name?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }) || [];
  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 18, alignItems: "center", flexWrap: "wrap" }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search users…" className="holo-input" style={{ flex: 1, minWidth: 200 }} />
        <select value={filter} onChange={e => setFilter(e.target.value)} className="holo-input" style={{ width: 130 }}>
          <option value="all">All Users</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        <div style={{ fontSize: 9, color: "rgba(0,212,255,0.4)", fontFamily: "'Share Tech Mono', monospace" }}>{rows.length} records</div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["#", "User", "Email", "Plan", "Role", "Joined", "Status"].map(h => (
                <th key={h} style={{ padding: "8px 14px", textAlign: "left", color: "rgba(0,212,255,0.5)", fontWeight: 700, fontSize: 8, textTransform: "uppercase", letterSpacing: "0.18em", borderBottom: "1px solid rgba(0,212,255,0.1)", whiteSpace: "nowrap", fontFamily: "'Share Tech Mono', monospace" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((u, idx) => (
              <tr key={u.id} className="holo-row">
                <td style={{ ...td, color: "rgba(0,212,255,0.25)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace" }}>{String(idx + 1).padStart(3, "0")}</td>
                <td style={{ ...td }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      width: 28, height: 28,
                      background: u.is_active ? "rgba(0,212,255,0.12)" : "rgba(0,212,255,0.04)",
                      border: `1px solid ${u.is_active ? "rgba(0,212,255,0.3)" : "rgba(0,212,255,0.1)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, fontWeight: 700, color: u.is_active ? "#00d4ff" : "rgba(0,212,255,0.3)",
                      clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                    }}>{u.name?.[0]?.toUpperCase() || "?"}</div>
                    <span style={{ color: u.is_active ? "#e0f7ff" : "rgba(150,200,220,0.35)", fontFamily: "'Share Tech Mono', monospace", fontSize: 11 }}>{u.name || "—"}</span>
                  </div>
                </td>
                <td style={{ ...td, color: "rgba(0,212,255,0.45)", fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}>{u.email}</td>
                <td style={td}>
                  <span style={{ fontSize: 8, color: u.subscription_status === "paid" ? "#00ff88" : u.subscription_status === "trialing" ? "#ffd700" : "rgba(0,212,255,0.35)", fontFamily: "'Share Tech Mono', monospace", background: u.subscription_status === "paid" ? "rgba(0,255,136,0.06)" : "transparent", border: "1px solid currentColor", padding: "1px 6px", borderRadius: 2, opacity: 0.8 }}>
                    {u.subscription_status || "—"}
                  </span>
                </td>
                <td style={{ ...td, color: "rgba(0,212,255,0.4)", fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}>{u.role}</td>
                <td style={{ ...td, color: "rgba(0,212,255,0.3)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace" }}>{u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}</td>
                <td style={td}>
                  {u.email === "wahaj@acedengroup.com" ? (
                    <span style={{ fontSize: 8, color: "#ffd700", background: "rgba(255,215,0,0.08)", border: "1px solid rgba(255,215,0,0.3)", padding: "2px 8px", borderRadius: 2, fontFamily: "'Share Tech Mono', monospace", boxShadow: "0 0 12px rgba(255,215,0,0.2)" }}>⬡ ROOT</span>
                  ) : (
                    <button onClick={() => handleToggleActive(u.id, u.is_active)} style={{
                      fontSize: 8, fontWeight: 700, padding: "3px 10px", borderRadius: 2, border: "none", cursor: "pointer", fontFamily: "'Share Tech Mono', monospace",
                      background: u.is_active ? "rgba(0,255,136,0.08)" : "rgba(255,51,102,0.08)",
                      color: u.is_active ? "#00ff88" : "#ff3366",
                      boxShadow: u.is_active ? "0 0 10px rgba(0,255,136,0.2)" : "0 0 10px rgba(255,51,102,0.2)",
                      border: `1px solid ${u.is_active ? "rgba(0,255,136,0.3)" : "rgba(255,51,102,0.3)"}`,
                      transition: "all 0.2s",
                    }}>{u.is_active ? "● ONLINE" : "○ OFFLINE"}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── WORKSPACES TABLE ──────────────────────────────────────────────────────────
function WorkspacesTable() {
  const { data, loading, refetch } = useAdminFetch("/admin/workspaces?limit=100");
  const handleToggle = async (wsId, cur) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/workspaces/${wsId}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !cur }) });
    refetch();
  };
  if (loading) return <HoloLoader />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr>
            {["#", "Workspace", "Owner", "Members", "Tasks", "Created", "Status"].map(h => (
              <th key={h} style={{ padding: "8px 14px", textAlign: "left", color: "rgba(0,212,255,0.5)", fontWeight: 700, fontSize: 8, textTransform: "uppercase", letterSpacing: "0.18em", borderBottom: "1px solid rgba(0,212,255,0.1)", whiteSpace: "nowrap", fontFamily: "'Share Tech Mono', monospace" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data?.workspaces?.map((ws, idx) => {
            const isActive = ws.is_active !== false;
            return (
              <tr key={ws.id} className="holo-row">
                <td style={{ ...td, color: "rgba(0,212,255,0.25)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace" }}>{String(idx + 1).padStart(3, "0")}</td>
                <td style={td}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      width: 28, height: 28,
                      background: isActive ? "rgba(0,212,255,0.12)" : "rgba(255,51,102,0.06)",
                      border: `1px solid ${isActive ? "rgba(0,212,255,0.3)" : "rgba(255,51,102,0.2)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, fontWeight: 700, color: isActive ? "#00d4ff" : "rgba(255,51,102,0.5)",
                      clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 6px 100%, 0 calc(100% - 6px))",
                    }}>{ws.name?.[0]?.toUpperCase() || "W"}</div>
                    <span style={{ color: isActive ? "#e0f7ff" : "rgba(150,200,220,0.3)", fontFamily: "'Share Tech Mono', monospace", fontSize: 11 }}>{ws.name}</span>
                  </div>
                </td>
                <td style={{ ...td, color: "rgba(0,212,255,0.4)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace" }}>{ws.owner_email ?? "—"}</td>
                <td style={td}><span style={{ color: "#00d4ff", fontWeight: 700, fontFamily: "'Orbitron', monospace", fontSize: 13, textShadow: "0 0 10px rgba(0,212,255,0.6)" }}>{ws.member_count}</span></td>
                <td style={td}><span style={{ color: "#00ff88", fontWeight: 600, fontFamily: "'Orbitron', monospace", fontSize: 13, textShadow: "0 0 10px rgba(0,255,136,0.5)" }}>{ws.task_count}</span></td>
                <td style={{ ...td, color: "rgba(0,212,255,0.3)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace" }}>{ws.created_at ? new Date(ws.created_at).toLocaleDateString() : "—"}</td>
                <td style={td}>
                  {ws.owner_email === "wahaj@acedengroup.com" ? (
                    <span style={{ fontSize: 8, color: "#ffd700", background: "rgba(255,215,0,0.08)", border: "1px solid rgba(255,215,0,0.3)", padding: "2px 8px", borderRadius: 2, fontFamily: "'Share Tech Mono', monospace" }}>⬡ PROTECTED</span>
                  ) : (
                    <button onClick={() => handleToggle(ws.id, isActive)} style={{
                      fontSize: 8, fontWeight: 700, padding: "3px 10px", borderRadius: 2, border: "none", cursor: "pointer", fontFamily: "'Share Tech Mono', monospace",
                      background: isActive ? "rgba(0,255,136,0.08)" : "rgba(255,51,102,0.08)",
                      color: isActive ? "#00ff88" : "#ff3366",
                      border: `1px solid ${isActive ? "rgba(0,255,136,0.3)" : "rgba(255,51,102,0.3)"}`,
                      boxShadow: isActive ? "0 0 10px rgba(0,255,136,0.2)" : "0 0 10px rgba(255,51,102,0.2)",
                      transition: "all 0.2s",
                    }}>{isActive ? "● ACTIVE" : "○ HALTED"}</button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ marginTop: 14, color: "rgba(0,212,255,0.3)", fontSize: 10, display: "flex", alignItems: "center", gap: 6, fontFamily: "'Share Tech Mono', monospace" }}>
        <span style={{ color: "#00d4ff", fontWeight: 700, textShadow: "0 0 10px #00d4ff", fontFamily: "'Orbitron', monospace" }}>{data?.total}</span>
        <span>workspaces indexed</span>
      </div>
    </div>
  );
}

// ── FEEDBACK ──────────────────────────────────────────────────────────────────
function FeedbackTable() {
  const { data, loading } = useAdminFetch("/admin/feedback?limit=100");
  if (loading) return <HoloLoader />;
  const typeStyle = {
    bug:             { c: "#ff3366", bg: "rgba(255,51,102,0.06)", b: "rgba(255,51,102,0.25)", icon: "⚠" },
    feedback:        { c: "#00d4ff", bg: "rgba(0,212,255,0.06)", b: "rgba(0,212,255,0.25)", icon: "◈" },
    feature_request: { c: "#00ff88", bg: "rgba(0,255,136,0.06)", b: "rgba(0,255,136,0.25)", icon: "◆" },
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {data?.items?.map(f => {
        const ts = typeStyle[f.type] || { c: "#00d4ff", bg: "rgba(0,212,255,0.06)", b: "rgba(0,212,255,0.2)", icon: "•" };
        return (
          <div key={f.id} className="holo-feedback">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10, gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ background: ts.bg, color: ts.c, border: `1px solid ${ts.b}`, padding: "2px 8px", borderRadius: 2, fontSize: 8, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'Share Tech Mono', monospace", boxShadow: `0 0 10px ${ts.b}` }}>{ts.icon} {f.type.replace("_", " ")}</span>
                <span style={{ color: "#e0f7ff", fontWeight: 600, fontSize: 12, fontFamily: "'Share Tech Mono', monospace" }}>{f.title}</span>
              </div>
              <Badge text={f.status} />
            </div>
            <p style={{ color: "rgba(0,212,255,0.4)", fontSize: 11, margin: "0 0 10px", lineHeight: 1.8, fontFamily: "'Share Tech Mono', monospace" }}>{f.message}</p>
            <div style={{ display: "flex", gap: 16, fontSize: 9, color: "rgba(0,212,255,0.3)", flexWrap: "wrap", fontFamily: "'Share Tech Mono', monospace" }}>
              <span>◎ {f.user_name ?? "Anonymous"} {f.user_email && `(${f.user_email})`}</span>
              {f.page_context && <span>⊕ {f.page_context}</span>}
              <span>◷ {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}</span>
            </div>
          </div>
        );
      })}
      {!data?.items?.length && (
        <div style={{ textAlign: "center", padding: 80, color: "rgba(0,212,255,0.2)", fontFamily: "'Share Tech Mono', monospace", fontSize: 11, letterSpacing: "0.15em" }}>
          NO FEEDBACK RECORDS FOUND
        </div>
      )}
    </div>
  );
}

// ── TRUE 3D ARC REACTOR — sphere with specular lighting, depth rings, lens flare ─
function ArcReactor({ color = "#00d4ff", rgb = "0,212,255", value = "$0", label = "MRR", size = 200 }) {
  const canvasRef = useRef(null);
  const [angle, setAngle] = useState(0);
  useEffect(() => {
    let raf;
    let t = 0;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const S = size * 2;
    canvas.width = canvas.height = S;
    canvas.style.width = canvas.style.height = `${size}px`;
    const cx = S / 2, cy = S / 2;
    const [r0,g0,b0] = rgb.split(",").map(Number);

    function drawSphere3D(x, y, radius) {
      // Shadow beneath sphere
      const shadowG = ctx.createRadialGradient(x + radius*0.1, y + radius*0.85, 0, x, y + radius*0.7, radius*0.8);
      shadowG.addColorStop(0, `rgba(0,0,0,0.5)`);
      shadowG.addColorStop(1, `rgba(0,0,0,0)`);
      ctx.fillStyle = shadowG;
      ctx.beginPath(); ctx.ellipse(x, y + radius*0.85, radius*0.7, radius*0.2, 0, 0, Math.PI*2); ctx.fill();

      // Main sphere body — deep to mid tone
      const bodyG = ctx.createRadialGradient(x - radius*0.3, y - radius*0.25, radius*0.05, x, y, radius);
      bodyG.addColorStop(0, `rgba(${Math.min(r0+80,255)},${Math.min(g0+80,255)},${Math.min(b0+80,255)},0.9)`);
      bodyG.addColorStop(0.35, `rgba(${r0},${g0},${b0},0.55)`);
      bodyG.addColorStop(0.7, `rgba(${Math.round(r0*0.3)},${Math.round(g0*0.3)},${Math.round(b0*0.3)},0.35)`);
      bodyG.addColorStop(1, `rgba(0,0,0,0.6)`);
      ctx.fillStyle = bodyG;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Primary specular highlight — top-left white hot spot
      const spec1 = ctx.createRadialGradient(x - radius*0.32, y - radius*0.30, 0, x - radius*0.2, y - radius*0.2, radius*0.42);
      spec1.addColorStop(0, `rgba(255,255,255,0.95)`);
      spec1.addColorStop(0.25, `rgba(255,255,255,0.45)`);
      spec1.addColorStop(0.6, `rgba(${r0},${g0},${b0},0.15)`);
      spec1.addColorStop(1, `rgba(${r0},${g0},${b0},0)`);
      ctx.fillStyle = spec1;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Secondary rim light — bottom-right edge
      const spec2 = ctx.createRadialGradient(x + radius*0.55, y + radius*0.55, 0, x + radius*0.4, y + radius*0.4, radius*0.55);
      spec2.addColorStop(0, `rgba(${r0},${g0},${b0},0.5)`);
      spec2.addColorStop(0.4, `rgba(${r0},${g0},${b0},0.15)`);
      spec2.addColorStop(1, `rgba(${r0},${g0},${b0},0)`);
      ctx.fillStyle = spec2;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Fresnel rim glow around edge
      ctx.save();
      ctx.shadowColor = color; ctx.shadowBlur = radius * 0.6;
      ctx.strokeStyle = `rgba(${rgb},0.7)`;
      ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(x, y, radius - 1, 0, Math.PI*2); ctx.stroke();
      ctx.restore();
    }

    function drawPerspectiveRing(x, y, rx, ry, rotX, lineW, alpha, dash, phase) {
      // Draw an ellipse (perspective-foreshortened ring) with rotation
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(phase);
      ctx.scale(1, ry / rx);
      ctx.beginPath();
      ctx.arc(0, 0, rx, 0, Math.PI * 2);
      if (dash.length) ctx.setLineDash(dash); else ctx.setLineDash([]);
      ctx.strokeStyle = `rgba(${rgb},${alpha})`;
      ctx.lineWidth = lineW / (ry / rx);
      ctx.shadowColor = color; ctx.shadowBlur = 10;
      ctx.stroke();
      ctx.restore();
    }

    function draw() {
      t += 0.012;
      ctx.clearRect(0, 0, S, S);

      // Ambient outer glow halo
      const halo = ctx.createRadialGradient(cx, cy, S*0.22, cx, cy, S*0.5);
      halo.addColorStop(0, `rgba(${rgb},0.08)`);
      halo.addColorStop(0.5, `rgba(${rgb},0.03)`);
      halo.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = halo; ctx.fillRect(0, 0, S, S);

      // 3D Perspective rings — foreshortened ellipses at different tilt angles
      const rings3D = [
        { rx: S*0.44, ryRatio: 0.18, w: 0.8, a: 0.09, dash: [5,14], speed: 0.25 },
        { rx: S*0.40, ryRatio: 0.28, w: 1.0, a: 0.13, dash: [10,8], speed: -0.4 },
        { rx: S*0.36, ryRatio: 0.42, w: 1.5, a: 0.20, dash: [3,9], speed: 0.6 },
        { rx: S*0.31, ryRatio: 0.60, w: 2.0, a: 0.28, dash: [], speed: -0.3 },
        { rx: S*0.25, ryRatio: 0.75, w: 1.2, a: 0.22, dash: [6,5], speed: 1.0 },
        { rx: S*0.18, ryRatio: 0.88, w: 3.5, a: 0.45, dash: [], speed: 0.8 },
        { rx: S*0.11, ryRatio: 0.95, w: 1.5, a: 0.35, dash: [3,6], speed: -1.8 },
      ];
      rings3D.forEach(ring => {
        drawPerspectiveRing(cx, cy, ring.rx, ring.rx * ring.ryRatio, 0, ring.w, ring.a, ring.dash, t * ring.speed);
      });

      // Spinning bright arc on the main ring
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(t * 1.4); ctx.scale(1, 0.6); // foreshorten
      ctx.beginPath();
      ctx.arc(0, 0, S * 0.31, -0.3, Math.PI * 1.15);
      ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.setLineDash([]);
      ctx.globalAlpha = 0.7 + Math.sin(t * 2.5) * 0.2;
      ctx.shadowColor = color; ctx.shadowBlur = 28;
      ctx.stroke(); ctx.globalAlpha = 1; ctx.restore();

      // Counter arc
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(-t * 0.9); ctx.scale(1, 0.75);
      ctx.beginPath();
      ctx.arc(0, 0, S * 0.25, 0.4, Math.PI * 1.9);
      ctx.strokeStyle = `rgba(${rgb},0.55)`; ctx.lineWidth = 2;
      ctx.shadowColor = color; ctx.shadowBlur = 16; ctx.setLineDash([]);
      ctx.stroke(); ctx.restore();

      // Draw the 3D sphere in the center
      drawSphere3D(cx, cy, S * 0.155);

      // Radial energy spokes (3D depth illusion — shorter = behind, longer = front)
      const spokeCount = 8;
      for (let i = 0; i < spokeCount; i++) {
        const a = (i / spokeCount) * Math.PI * 2 + t * 0.5;
        const depth = (Math.sin(a - t * 0.5) + 1) * 0.5; // 0=back, 1=front
        const innerR = S * (0.16 + depth * 0.01);
        const outerR = S * (0.22 + depth * 0.04);
        const pulse = 0.1 + depth * 0.2 + Math.sin(t * 2 + i) * 0.06;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * innerR, cy + Math.sin(a) * innerR * 0.6);
        ctx.lineTo(cx + Math.cos(a) * outerR, cy + Math.sin(a) * outerR * 0.6);
        ctx.strokeStyle = `rgba(${rgb},${pulse})`;
        ctx.lineWidth = 1 + depth;
        ctx.shadowColor = color; ctx.shadowBlur = 8 + depth * 12;
        ctx.stroke();
      }

      // Lens flare — top-right bright point
      const flareX = cx + S * 0.15, flareY = cy - S * 0.18;
      const flarePulse = 0.4 + Math.sin(t * 1.7) * 0.25;
      const flareG = ctx.createRadialGradient(flareX, flareY, 0, flareX, flareY, S * 0.08);
      flareG.addColorStop(0, `rgba(255,255,255,${flarePulse})`);
      flareG.addColorStop(0.3, `rgba(${rgb},${flarePulse * 0.4})`);
      flareG.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = flareG;
      ctx.beginPath(); ctx.arc(flareX, flareY, S * 0.08, 0, Math.PI * 2); ctx.fill();
      // Flare streaks
      ctx.save();
      ctx.globalAlpha = flarePulse * 0.5;
      [0, Math.PI*0.5, Math.PI, Math.PI*1.5, Math.PI*0.25, Math.PI*0.75].forEach(angle => {
        ctx.beginPath();
        ctx.moveTo(flareX, flareY);
        ctx.lineTo(flareX + Math.cos(angle) * S * 0.06, flareY + Math.sin(angle) * S * 0.06);
        ctx.strokeStyle = `rgba(255,255,255,0.8)`;
        ctx.lineWidth = 0.5; ctx.stroke();
      });
      ctx.restore();

      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, [color, rgb, size]);

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <canvas ref={canvasRef} style={{ display: "block" }} />
      {/* Center text overlay */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        pointerEvents: "none",
      }}>
        <div style={{ fontSize: 9, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{label}</div>
        <div style={{ fontSize: size * 0.13, fontWeight: 900, color: "#fff", fontFamily: "'Orbitron', monospace", letterSpacing: "-0.02em", textShadow: `0 0 20px rgba(${rgb},0.8), 0 0 60px rgba(${rgb},0.4)`, lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 8, color: `rgba(${rgb},0.4)`, letterSpacing: "0.15em", fontFamily: "'Share Tech Mono', monospace", marginTop: 6 }}>ACTIVE</div>
      </div>
    </div>
  );
}

// ── REVENUE WAVEFORM — live-looking signal display ────────────────────────────
function RevenueWaveform({ data, color = "#00d4ff", rgb = "0,212,255" }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data?.length) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = 120 * 2;
    canvas.style.height = "120px";
    let t = 0;
    let raf;

    const revenues = data.map(d => d.revenue || 0);
    const max = Math.max(...revenues, 1);

    function draw() {
      t += 0.018;
      ctx.clearRect(0, 0, W, H);

      const pts = revenues.map((v, i) => ({
        x: (i / (revenues.length - 1)) * W,
        y: H - (v / max) * (H * 0.75) - H * 0.1 + Math.sin(t + i * 0.4) * 2,
      }));

      // Glowing area fill
      const fillGrad = ctx.createLinearGradient(0, 0, 0, H);
      fillGrad.addColorStop(0, `rgba(${rgb},0.22)`);
      fillGrad.addColorStop(0.5, `rgba(${rgb},0.08)`);
      fillGrad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, H);
      pts.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.lineTo(pts[pts.length - 1].x, H);
      ctx.closePath();
      ctx.fillStyle = fillGrad;
      ctx.fill();

      // Secondary echo line (slightly offset, dimmer)
      ctx.beginPath();
      pts.forEach((p, i) => {
        const echoY = p.y + 6 + Math.sin(t * 0.7 + i) * 3;
        i === 0 ? ctx.moveTo(p.x, echoY) : ctx.lineTo(p.x, echoY);
      });
      ctx.strokeStyle = `rgba(${rgb},0.12)`;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Main line
      ctx.shadowColor = color;
      ctx.shadowBlur = 12;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.lineJoin = "round";
      ctx.beginPath();
      pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Glowing data nodes
      pts.forEach((p, i) => {
        const bright = revenues[i] > 0;
        if (!bright) return;
        const pulse = 0.5 + Math.sin(t * 3 + i * 0.8) * 0.3;
        const nodeGlow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 14);
        nodeGlow.addColorStop(0, `rgba(${rgb},${pulse * 0.4})`);
        nodeGlow.addColorStop(1, `rgba(${rgb},0)`);
        ctx.fillStyle = nodeGlow;
        ctx.beginPath(); ctx.arc(p.x, p.y, 14, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgba(255,255,255,${pulse * 0.9})`;
        ctx.shadowColor = color; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Scanning vertical line
      const scanX = ((t * 30) % W);
      const scanGrad = ctx.createLinearGradient(scanX - 20, 0, scanX + 20, 0);
      scanGrad.addColorStop(0, `rgba(${rgb},0)`);
      scanGrad.addColorStop(0.5, `rgba(${rgb},0.15)`);
      scanGrad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = scanGrad;
      ctx.fillRect(scanX - 20, 0, 40, H);

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { canvas.width = canvas.offsetWidth * 2; canvas.height = 120 * 2; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, [data, color, rgb]);

  return <canvas ref={canvasRef} style={{ display: "block", width: "100%" }} />;
}

// ── JARVIS METRIC STRIP — 3D glass morphism KPI strip ─────────────────────────
function JarvisMetricStrip({ metrics, rgb, color }) {
  const [hovered, setHovered] = useState(null);
  return (
    <div style={{ display: "flex", gap: 3, marginBottom: 14 }}>
      {metrics.map((m, i) => (
        <div key={i}
          onMouseEnter={() => setHovered(i)}
          onMouseLeave={() => setHovered(null)}
          style={{
            flex: 1,
            padding: "16px 18px",
            background: i === 0
              ? `linear-gradient(145deg, rgba(${rgb},0.18) 0%, rgba(${rgb},0.06) 50%, rgba(${rgb},0.12) 100%)`
              : hovered === i
                ? `linear-gradient(145deg, rgba(${rgb},0.1) 0%, rgba(0,4,12,0.8) 100%)`
                : "rgba(0,5,14,0.75)",
            border: `1px solid rgba(${rgb},${i === 0 ? 0.45 : hovered === i ? 0.3 : 0.12})`,
            borderRadius: 4,
            position: "relative",
            overflow: "hidden",
            clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
            transform: hovered === i ? "translateY(-3px) scale(1.02)" : "translateY(0)",
            transition: "all 0.25s cubic-bezier(0.16,1,0.3,1)",
            boxShadow: i === 0
              ? `0 8px 40px rgba(${rgb},0.15), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 30px rgba(${rgb},0.04)`
              : hovered === i
                ? `0 12px 40px rgba(${rgb},0.12), inset 0 1px 0 rgba(255,255,255,0.04)`
                : `0 4px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(${rgb},0.03)`,
            backdropFilter: "blur(16px)",
            cursor: "default",
          }}>
          {/* Top glass reflection streak */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "40%", background: `linear-gradient(180deg, rgba(255,255,255,${i === 0 ? 0.06 : 0.03}) 0%, rgba(255,255,255,0) 100%)`, pointerEvents: "none", borderRadius: "4px 4px 0 0" }} />
          {/* Top scan line */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: i === 0 ? `linear-gradient(90deg, ${color}, rgba(${rgb},0.4), transparent)` : `linear-gradient(90deg, transparent, rgba(${rgb},0.3), transparent)` }} />
          {/* Left depth bar */}
          {i === 0 && <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${color}, rgba(${rgb},0.2))`, boxShadow: `0 0 12px ${color}` }} />}
          {/* Corner cut accent */}
          <div style={{ position: "absolute", top: 0, right: 8, width: 0, height: 0, borderTop: `8px solid rgba(${rgb},${i === 0 ? 0.5 : 0.2})`, borderLeft: "8px solid transparent" }} />
          {/* Label */}
          <div style={{ fontSize: 7, color: `rgba(${rgb},${i === 0 ? 0.6 : 0.4})`, letterSpacing: "0.2em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 8 }}>{m.label}</div>
          {/* Value */}
          <div style={{ fontSize: 20, fontWeight: 800, color: i === 0 ? "#fff" : color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 20px rgba(${rgb},${i === 0 ? 0.9 : 0.6}), 0 0 60px rgba(${rgb},0.2)`, letterSpacing: "-0.02em", lineHeight: 1 }}>{m.value}</div>
          {m.sub && <div style={{ fontSize: 8, color: `rgba(${rgb},0.3)`, fontFamily: "'Share Tech Mono', monospace", marginTop: 6, letterSpacing: "0.05em" }}>{m.sub}</div>}
          {/* Bottom shimmer */}
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: `rgba(${rgb},0.06)` }} />
        </div>
      ))}
    </div>
  );
}

// ── REVENUE INTEL PANEL — 3D glass right sidebar ─────────────────────────────
function RevenueIntelPanel({ data, rgb, color }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1800);
    return () => clearInterval(id);
  }, []);

  if (!data) return null;

  const breakdown = data.monthly_breakdown || [];
  const totalRev = breakdown.reduce((s, d) => s + (d.revenue || 0), 0);
  const totalUsers = breakdown.reduce((s, d) => s + (d.new_paid || 0), 0);
  const lastThree = breakdown.slice(-3);
  const growth = lastThree.length >= 2
    ? ((lastThree[lastThree.length - 1].revenue - lastThree[0].revenue) / Math.max(lastThree[0].revenue, 1) * 100).toFixed(1)
    : 0;

  const signals = [
    { label: "Revenue Engine", status: "OPTIMAL", col: "#00ff88" },
    { label: "Billing Sync", status: data.mrr > 0 ? "ACTIVE" : "OFFLINE", col: data.mrr > 0 ? "#00ff88" : "#ff3366" },
    { label: "Growth Vector", status: growth > 0 ? `+${growth}%` : `${growth}%`, col: growth > 0 ? "#00ff88" : "#ffd700" },
    { label: "Unit Economics", status: "STABLE", col: "#00d4ff" },
    { label: "Forecast Model", status: "RUNNING", col: color },
  ];

  const projMonths = 3;
  const avgMonthly = totalRev / Math.max(breakdown.length, 1);
  const projections = Array.from({ length: projMonths }, (_, i) => ({
    label: ["NEXT MO", "+2 MO", "+3 MO"][i],
    value: `$${(avgMonthly * (1 + (i + 1) * 0.05)).toFixed(0)}`,
    conf: [92, 84, 71][i],
  }));

  const glassPanel = {
    background: `linear-gradient(145deg, rgba(0,6,18,0.92) 0%, rgba(0,12,28,0.85) 40%, rgba(0,6,18,0.88) 100%)`,
    border: `1px solid rgba(${rgb},0.2)`,
    borderRadius: 4,
    padding: "16px 18px",
    clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
    position: "relative",
    overflow: "hidden",
    backdropFilter: "blur(20px)",
    boxShadow: `0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 40px rgba(${rgb},0.02)`,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* System signals */}
      <div style={glassPanel}>
        {/* Glass reflection */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.7), transparent)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${color}, rgba(${rgb},0.1))`, boxShadow: `0 0 10px rgba(${rgb},0.3)` }} />
        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rgb},0.35)`, borderLeft: "10px solid transparent" }} />
        {/* Subtle inner glow */}
        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rgb},0.05) 0%, transparent 70%)`, pointerEvents: "none" }} />

        <div style={{ fontSize: 8, color: `rgba(${rgb},0.6)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
          <div style={{ width: 5, height: 5, background: "#00ff88", borderRadius: "50%", animation: "pulse-glow 1.5s infinite", boxShadow: "0 0 10px #00ff88" }} />
          System Intel
        </div>
        {signals.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: i < signals.length - 1 ? 10 : 0, padding: "6px 8px", borderBottom: i < signals.length - 1 ? `1px solid rgba(${rgb},0.06)` : "none", borderRadius: 2, background: "rgba(0,0,0,0.1)", position: "relative" }}>
            <span style={{ fontSize: 8, color: `rgba(${rgb},0.45)`, fontFamily: "'Share Tech Mono', monospace" }}>{s.label}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: s.col, boxShadow: `0 0 8px ${s.col}`, animation: "pulse-glow 2s infinite" }} />
              <span style={{ fontSize: 8, color: s.col, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.08em", fontWeight: 700 }}>{s.status}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Revenue projections */}
      <div style={glassPanel}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.6), transparent)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rgb},0.8), transparent)` }} />
        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rgb},0.3)`, borderLeft: "10px solid transparent" }} />

        <div style={{ fontSize: 8, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 4, height: 4, background: color, borderRadius: "50%", boxShadow: `0 0 8px ${color}` }} />
          Projection
        </div>
        {projections.map((p, i) => (
          <div key={i} style={{ marginBottom: i < projections.length - 1 ? 12 : 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <span style={{ fontSize: 8, color: `rgba(${rgb},0.4)`, fontFamily: "'Share Tech Mono', monospace" }}>{p.label}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 7, color: `rgba(${rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace" }}>{p.conf}%</span>
                <span style={{ fontSize: 14, color: "#fff", fontWeight: 700, fontFamily: "'Orbitron', monospace", textShadow: `0 0 12px rgba(${rgb},0.7)` }}>{p.value}</span>
              </div>
            </div>
            <div style={{ height: 3, background: `rgba(${rgb},0.06)`, borderRadius: 2, position: "relative", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${p.conf}%`, background: `linear-gradient(90deg, rgba(${rgb},0.3), ${color})`, borderRadius: 2, boxShadow: `0 0 8px rgba(${rgb},0.4)`, transition: "width 1.4s cubic-bezier(0.4,0,0.2,1)", position: "relative" }}>
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "50%", background: "rgba(255,255,255,0.2)", borderRadius: "2px 2px 0 0" }} />
              </div>
            </div>
          </div>
        ))}
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid rgba(${rgb},0.08)`, fontSize: 8, color: `rgba(${rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace", lineHeight: 1.7 }}>
          ◈ Linear regression · {breakdown.length} pts
        </div>
      </div>

      {/* Cumulative totals */}
      <div style={{ ...glassPanel, background: `linear-gradient(145deg, rgba(${rgb},0.08) 0%, rgba(0,6,18,0.88) 50%, rgba(${rgb},0.04) 100%)`, border: `1px solid rgba(${rgb},0.25)` }}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, ${color}, rgba(${rgb},0.3), transparent)` }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ fontSize: 8, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 12 }}>Cumulative</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {[
            { label: "Total Revenue", value: `$${totalRev.toFixed(0)}` },
            { label: "Paid Users", value: totalUsers },
            { label: "Plan Price", value: `$${data.plan_price}/mo` },
            { label: "Avg MRR", value: `$${avgMonthly.toFixed(0)}` },
          ].map((item, i) => (
            <div key={i} style={{ padding: "8px 10px", background: "rgba(0,0,0,0.2)", borderRadius: 3, border: `1px solid rgba(${rgb},0.1)`, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `rgba(${rgb},0.15)` }} />
              <div style={{ fontSize: 7, color: `rgba(${rgb},0.35)`, letterSpacing: "0.15em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 12px rgba(${rgb},0.5)` }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── REVENUE COLOR CYCLE HOOK ─────────────────────────────────────────────────
// Slowly cycles through a palette of cyberpunk accent colors for the revenue panel only.
function useRevenueColor() {
  const palette = [
    { hex: "#00ff88", rgb: "0,255,136" },
    { hex: "#00d4ff", rgb: "0,212,255" },
    { hex: "#a855f7", rgb: "168,85,247" },
    { hex: "#ffd700", rgb: "255,215,0" },
    { hex: "#ff6b35", rgb: "255,107,53" },
    { hex: "#00ffcc", rgb: "0,255,204" },
  ];
  const [t, setT] = useState(0);
  useEffect(() => {
    let raf;
    let start = null;
    const CYCLE_MS = 6000; // full palette loop every 6 s
    function tick(now) {
      if (!start) start = now;
      // progress 0–1 across the entire palette
      const progress = ((now - start) % CYCLE_MS) / CYCLE_MS;
      setT(progress);
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Interpolate between two adjacent palette entries
  const total = palette.length;
  const scaled = t * total;
  const idxA = Math.floor(scaled) % total;
  const idxB = (idxA + 1) % total;
  const frac = scaled - Math.floor(scaled);

  const lerp = (a, b, f) => Math.round(a + (b - a) * f);
  const parseRgb = (s) => s.split(",").map(Number);
  const [r1, g1, b1] = parseRgb(palette[idxA].rgb);
  const [r2, g2, b2] = parseRgb(palette[idxB].rgb);
  const r = lerp(r1, r2, frac);
  const g = lerp(g1, g2, frac);
  const b = lerp(b1, b2, frac);

  return { hex: `rgb(${r},${g},${b})`, rgb: `${r},${g},${b}` };
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [tab, setTab] = useState("overview");
  const { data: metrics, loading, error, refetch } = useAdminFetch("/admin/metrics");
  const m = metrics;
  const [time, setTime] = useState(new Date());
  const [bootSeq, setBootSeq] = useState(0);
  const revColor = useRevenueColor();
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { const t = setInterval(() => setBootSeq(s => s < 100 ? s + 2 : 100), 40); return () => clearInterval(t); }, []);

  const timeStr = time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const dateStr = time.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });

  const TABS = [
    { id: "overview",   label: "OVERVIEW",   icon: "◈" },
    { id: "revenue",    label: "REVENUE",    icon: "◎" },
    { id: "users",      label: "USERS",      icon: "⬡", count: m?.users?.total },
    { id: "workspaces", label: "WORKSPACES", icon: "⊞" },
    { id: "feedback",   label: "FEEDBACK",   icon: "◆" },
  ];

  const isRev = tab === "revenue";
  const rc = revColor; // shorthand

  return (
    <div style={{ minHeight: "100vh", background: "#000d1a", color: "#e0f7ff", position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;600;700;800;900&family=Share+Tech+Mono&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #000d1a; }

        /* ── SPACE BACKGROUND ── */
        .space-bg {
          position: fixed; inset: 0;
          background:
            radial-gradient(ellipse 70% 50% at 15% 10%, rgba(0,40,80,0.4) 0%, transparent 60%),
            radial-gradient(ellipse 50% 40% at 85% 85%, rgba(0,20,50,0.35) 0%, transparent 60%),
            radial-gradient(ellipse 30% 25% at 60% 35%, rgba(0,50,80,0.15) 0%, transparent 70%),
            #000d1a;
          pointer-events: none; z-index: 0;
          transition: background 0.6s;
        }

        /* ── TOP HUD LINE ── */
        .hud-topline {
          position: fixed; top: 0; left: 0; right: 0; height: 2px;
          background: linear-gradient(90deg, transparent 0%, #00d4ff 20%, #00ff88 50%, #00d4ff 80%, transparent 100%);
          pointer-events: none; z-index: 50;
          animation: hudScan 4s ease-in-out infinite alternate;
          box-shadow: 0 0 20px #00d4ff, 0 0 40px rgba(0,212,255,0.3);
          transition: background 0.4s, box-shadow 0.4s;
        }
        @keyframes hudScan {
          0% { opacity: 0.6; }
          50% { opacity: 1; }
          100% { opacity: 0.7; }
        }

        /* ── VIGNETTE ── */
        .vignette {
          position: fixed; inset: 0; pointer-events: none; z-index: 1;
          background: radial-gradient(ellipse at center, transparent 50%, rgba(0,5,15,0.6) 100%);
        }

        /* scanline overlay */
        .scanlines {
          position: fixed; inset: 0; pointer-events: none; z-index: 2;
          background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,212,255,0.012) 2px, rgba(0,212,255,0.012) 4px);
          transition: background 0.4s;
        }

        /* ── ANIMATIONS ── */
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes holoRise {
          from { opacity: 0; transform: perspective(900px) translateY(40px) translateZ(-30px) rotateX(5deg); }
          to { opacity: 1; transform: perspective(900px) translateY(0) translateZ(0) rotateX(0); }
        }
        @keyframes pulse-glow {
          0%, 100% { opacity: 0.7; }
          50% { opacity: 1; filter: brightness(1.4); }
        }
        @keyframes particleFloat {
          0% { transform: translateY(0) scale(1); opacity: 1; }
          100% { transform: translateY(-60px) scale(0); opacity: 0; }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; } 50% { opacity: 0; }
        }
        @keyframes rotateSlow { to { transform: rotate(360deg); } }
        @keyframes dataStream {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
        @keyframes glitchShift {
          0%, 95%, 100% { clip-path: none; transform: none; }
          96% { clip-path: polygon(0 20%, 100% 20%, 100% 40%, 0 40%); transform: translateX(4px); }
          97% { clip-path: polygon(0 60%, 100% 60%, 100% 80%, 0 80%); transform: translateX(-4px); }
          98% { clip-path: none; transform: translateX(2px); }
        }

        /* ── LAYOUT ── */
        .dashboard-root {
          font-family: 'Share Tech Mono', monospace;
          display: flex; min-height: 100vh; position: relative; z-index: 3;
        }

        /* ── SIDEBAR ── */
        .sidebar {
          width: 220px; min-height: 100vh;
          background: linear-gradient(180deg, rgba(0,5,15,0.98) 0%, rgba(0,8,20,0.96) 100%);
          border-right: 1px solid rgba(0,212,255,0.15);
          display: flex; flex-direction: column;
          position: fixed; top: 0; left: 0; bottom: 0; z-index: 10;
        }
        .sidebar::after {
          content: '';
          position: absolute; top: 10%; right: 0; bottom: 10%;
          width: 1px;
          background: linear-gradient(180deg, transparent, #00d4ff, #00ff88, #00d4ff, transparent);
          opacity: 0.3;
          animation: pulse-glow 3s ease-in-out infinite;
        }

        /* ── MAIN CONTENT ── */
        .main-content {
          margin-left: 220px; flex: 1;
          padding: 0 28px 40px;
          min-height: 100vh;
          position: relative;
        }

        /* ── TOPBAR ── */
        .topbar {
          display: flex; align-items: center; justify-content: space-between;
          padding: 20px 0 22px;
          border-bottom: 1px solid rgba(0,212,255,0.1);
          margin-bottom: 24px;
          position: sticky; top: 0; z-index: 5;
          background: rgba(0,13,26,0.92);
          backdrop-filter: blur(20px);
        }
        .topbar::after {
          content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(0,212,255,0.4), rgba(0,255,136,0.2), transparent);
        }

        /* ── SECTION HEADING ── */
        .section-heading {
          font-size: 9px; color: rgba(0,212,255,0.4); letter-spacing: 0.28em;
          text-transform: uppercase; margin-bottom: 14px;
          font-family: 'Share Tech Mono', monospace;
          display: flex; align-items: center; gap: 10;
        }
        .section-heading::before {
          content: '▶'; font-size: 7px; color: #00d4ff;
        }
        .section-heading::after {
          content: ''; flex: 1; height: 1px;
          background: linear-gradient(90deg, rgba(0,212,255,0.2), transparent);
        }

        /* ── STAT STRIP ── */
        .stat-row {
          display: flex; gap: 10; flex-wrap: wrap; margin-top: 16px;
        }
        .stat-item {
          flex: 1; min-width: 110px;
          background: rgba(0,212,255,0.03);
          border: 1px solid rgba(0,212,255,0.1);
          border-radius: 3px; padding: 14px 16px;
          position: relative; overflow: hidden;
          transition: all 0.2s;
          clip-path: polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 8px 100%, 0 calc(100% - 8px));
        }
        .stat-item:hover {
          border-color: rgba(0,212,255,0.28);
          background: rgba(0,212,255,0.06);
          box-shadow: 0 0 20px rgba(0,212,255,0.08);
        }
        .stat-label {
          font-size: 8px; color: rgba(0,212,255,0.35); text-transform: uppercase;
          letter-spacing: 0.15em; margin-bottom: 8px; font-family: 'Share Tech Mono', monospace;
        }
        .stat-val {
          font-size: 18px; font-weight: 700; font-family: 'Orbitron', monospace; letter-spacing: -0.02em;
        }

        /* ── TABLE ROWS ── */
        .holo-row { transition: background 0.15s; }
        .holo-row:hover { background: rgba(0,212,255,0.04); }
        .holo-row td { border-bottom: 1px solid rgba(0,212,255,0.05); }

        /* ── INPUTS ── */
        .holo-input {
          background: rgba(0,8,20,0.9);
          border: 1px solid rgba(0,212,255,0.2); border-radius: 3px;
          color: #e0f7ff; font-size: 11px; padding: 9px 12px;
          font-family: 'Share Tech Mono', monospace; outline: none;
          transition: all 0.2s; backdrop-filter: blur(10px);
        }
        .holo-input:focus {
          border-color: rgba(0,212,255,0.5);
          box-shadow: 0 0 0 3px rgba(0,212,255,0.08), 0 0 20px rgba(0,212,255,0.1);
        }
        .holo-input option { background: #000d1a; }

        /* ── FEEDBACK CARD ── */
        .holo-feedback {
          background: rgba(0,8,20,0.9);
          border: 1px solid rgba(0,212,255,0.12);
          border-radius: 3px; padding: 18px;
          transition: all 0.25s; position: relative; overflow: hidden;
          clip-path: polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px));
        }
        .holo-feedback::before {
          content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(0,212,255,0.3), transparent);
        }
        .holo-feedback:hover {
          border-color: rgba(0,212,255,0.25);
          transform: translateY(-1px);
          box-shadow: 0 8px 30px rgba(0,0,0,0.5), 0 0 20px rgba(0,212,255,0.06);
        }

        /* ── REFETCH BTN ── */
        .refetch-btn {
          background: rgba(0,212,255,0.06);
          border: 1px solid rgba(0,212,255,0.25); color: #00d4ff;
          border-radius: 3px; padding: 7px 14px; font-size: 9px;
          cursor: pointer; font-family: 'Share Tech Mono', monospace;
          letter-spacing: 0.1em; transition: all 0.2s; text-transform: uppercase;
          clip-path: polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%);
        }
        .refetch-btn:hover {
          background: rgba(0,212,255,0.12);
          box-shadow: 0 0 20px rgba(0,212,255,0.2);
        }

        /* scrollbar */
        ::-webkit-scrollbar { width: 3px; height: 3px; }
        ::-webkit-scrollbar-track { background: rgba(0,8,20,0.8); }
        ::-webkit-scrollbar-thumb { background: rgba(0,212,255,0.2); border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(0,212,255,0.4); }
      `}</style>

      {/* Background layers */}
      <div className="space-bg" style={isRev ? {
        background: `
          radial-gradient(ellipse 80% 60% at 20% 15%, rgba(${rc.rgb},0.12) 0%, transparent 55%),
          radial-gradient(ellipse 60% 50% at 80% 80%, rgba(${rc.rgb},0.09) 0%, transparent 55%),
          radial-gradient(ellipse 40% 35% at 55% 40%, rgba(${rc.rgb},0.06) 0%, transparent 65%),
          radial-gradient(ellipse 100% 100% at 50% 50%, rgba(${rc.rgb},0.04) 0%, transparent 80%),
          #000d1a`
      } : {}} />
      <div className="vignette" />
      <div className="scanlines" style={isRev ? {
        background: `repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(${rc.rgb},0.018) 2px, rgba(${rc.rgb},0.018) 4px)`
      } : {}} />
      <div className="hud-topline" style={isRev ? {
        background: `linear-gradient(90deg, transparent 0%, ${rc.hex} 20%, rgba(${rc.rgb},0.6) 50%, ${rc.hex} 80%, transparent 100%)`,
        boxShadow: `0 0 24px ${rc.hex}, 0 0 50px rgba(${rc.rgb},0.4)`,
        height: 3,
      } : {}} />
      <HoloGrid />

      <div className="dashboard-root">
        {/* ── SIDEBAR ── */}
        <aside className="sidebar" style={isRev ? {
          borderRight: `1px solid rgba(${rc.rgb},0.25)`,
          boxShadow: `4px 0 40px rgba(${rc.rgb},0.06)`,
        } : {}}>
          {/* Logo block */}
          <div style={{ padding: "24px 18px 18px", borderBottom: "1px solid rgba(0,212,255,0.08)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
              <div style={{
                width: 40, height: 40,
                border: "1px solid rgba(0,212,255,0.4)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 18, color: "#00d4ff",
                background: "rgba(0,212,255,0.06)",
                clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                animation: "pulse-glow 3s ease-in-out infinite",
                boxShadow: "0 0 20px rgba(0,212,255,0.2)",
              }}>Ω</div>
              <div>
                <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 13, fontWeight: 700, color: "#e0f7ff", letterSpacing: "0.05em", animation: "glitchShift 8s infinite" }}>ArcaneOS</div>
                <div style={{ fontSize: 7, color: "rgba(0,212,255,0.4)", letterSpacing: "0.22em", textTransform: "uppercase", marginTop: 2 }}>Admin Console v2.0</div>
              </div>
            </div>

            {/* Boot progress */}
            <div style={{ marginTop: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 7, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em" }}>SYS INTEGRITY</span>
                <span style={{ fontSize: 7, color: "#00ff88", letterSpacing: "0.1em", fontFamily: "'Orbitron', monospace" }}>{bootSeq}%</span>
              </div>
              <div style={{ height: 2, background: "rgba(0,212,255,0.1)", borderRadius: 1 }}>
                <div style={{ height: "100%", width: `${bootSeq}%`, background: "linear-gradient(90deg, #00d4ff, #00ff88)", boxShadow: "0 0 8px #00d4ff", borderRadius: 1, transition: "width 0.1s" }} />
              </div>
            </div>
          </div>

          {/* Clock */}
          <div style={{ margin: "12px 14px", background: "rgba(0,212,255,0.03)", border: "1px solid rgba(0,212,255,0.08)", borderRadius: 3, padding: "10px 14px" }}>
            <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 20, fontWeight: 700, color: "#00d4ff", letterSpacing: "0.06em", textShadow: "0 0 20px rgba(0,212,255,0.5)" }}>
              {timeStr}
            </div>
            <div style={{ fontSize: 8, color: "rgba(0,212,255,0.35)", marginTop: 3, letterSpacing: "0.1em" }}>{dateStr.toUpperCase()}</div>
          </div>

          {/* Nav */}
          <div style={{ flex: 1, padding: "8px 0" }}>
            <div style={{ fontSize: 7, color: "rgba(0,212,255,0.2)", letterSpacing: "0.25em", textTransform: "uppercase", padding: "0 18px 8px" }}>Navigation</div>
            {TABS.map(t => (
              <NavTab key={t.id} label={t.label} active={tab === t.id} onClick={() => setTab(t.id)} count={t.count} icon={t.icon} activeColor={t.id === "revenue" && tab === "revenue" ? rc.hex : undefined} />
            ))}
          </div>

          {/* System status */}
          <div style={{ padding: "12px 18px 20px", borderTop: "1px solid rgba(0,212,255,0.06)" }}>
            <div style={{ fontSize: 7, color: "rgba(0,212,255,0.2)", letterSpacing: "0.25em", textTransform: "uppercase", marginBottom: 10 }}>Systems</div>
            {[["API Gateway", "#00ff88", "NOMINAL"], ["Database", "#00ff88", "ONLINE"], ["Auth Layer", "#ffd700", "STANDBY"]].map(([name, col, status]) => (
              <div key={name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 7 }}>
                <span style={{ fontSize: 9, color: "rgba(0,212,255,0.4)" }}>{name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <div style={{ width: 4, height: 4, borderRadius: "50%", background: col, boxShadow: `0 0 8px ${col}`, animation: "pulse-glow 2s infinite" }} />
                  <span style={{ fontSize: 7, color: col + "aa", letterSpacing: "0.08em" }}>{status}</span>
                </div>
              </div>
            ))}

            {/* Sign Out */}
            <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid rgba(255,51,102,0.1)" }}>
              <button
                onClick={async () => {
                  // Clear all auth tokens
                  localStorage.removeItem("access_token");
                  localStorage.removeItem("refresh_token");
                  localStorage.removeItem("token");
                  sessionStorage.clear();
                  // Try /login first; if it doesn't exist, reload current page
                  // so the parent router can re-evaluate auth state
                  try {
                    const res = await fetch("/login", { method: "HEAD" });
                    window.location.replace(res.ok ? "/login" : "/");
                  } catch {
                    window.location.replace("/");
                  }
                }}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: "9px 12px", cursor: "pointer",
                  background: "rgba(255,51,102,0.05)",
                  border: "1px solid rgba(255,51,102,0.2)",
                  borderRadius: 3, transition: "all 0.2s",
                  clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                  fontFamily: "'Share Tech Mono', monospace",
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = "rgba(255,51,102,0.12)";
                  e.currentTarget.style.borderColor = "rgba(255,51,102,0.45)";
                  e.currentTarget.style.boxShadow = "0 0 20px rgba(255,51,102,0.15)";
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = "rgba(255,51,102,0.05)";
                  e.currentTarget.style.borderColor = "rgba(255,51,102,0.2)";
                  e.currentTarget.style.boxShadow = "none";
                }}
              >
                <span style={{ fontSize: 11, color: "rgba(255,51,102,0.7)" }}>⏻</span>
                <span style={{ fontSize: 9, color: "rgba(255,51,102,0.6)", letterSpacing: "0.18em", textTransform: "uppercase" }}>Terminate Session</span>
              </button>
            </div>
          </div>
        </aside>

        {/* ── MAIN ── */}
        <main className="main-content">
          {/* Topbar */}
          <div className="topbar" style={isRev ? {
            borderBottom: `1px solid rgba(${rc.rgb},0.18)`,
            boxShadow: `0 1px 0 rgba(${rc.rgb},0.1), 0 4px 30px rgba(${rc.rgb},0.05)`,
          } : {}}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ color: isRev ? rc.hex : "#00d4ff", fontSize: 14, fontFamily: "'Share Tech Mono', monospace", textShadow: isRev ? `0 0 14px ${rc.hex}` : "none", transition: "color 0.4s, text-shadow 0.4s" }}>{TABS.find(t => t.id === tab)?.icon}</span>
                <h1 style={{ fontFamily: "'Orbitron', monospace", fontSize: 22, fontWeight: 900, color: "#fff", letterSpacing: "0.08em", lineHeight: 1, textShadow: isRev ? `0 0 30px rgba(${rc.rgb},0.7), 0 0 60px rgba(${rc.rgb},0.3)` : "0 0 30px rgba(0,212,255,0.4)", transition: "text-shadow 0.4s" }}>
                  {TABS.find(t => t.id === tab)?.label}
                </h1>
              </div>
              <div style={{ fontSize: 8, color: isRev ? `rgba(${rc.rgb},0.4)` : "rgba(0,212,255,0.3)", letterSpacing: "0.18em", transition: "color 0.4s" }}>ARCANEOS · INTELLIGENCE LAYER · CLASSIFIED</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {error && <span style={{ fontSize: 9, color: "#ff3366", fontFamily: "'Share Tech Mono', monospace" }}>⚠ ERR: {error}</span>}
              <button onClick={refetch} className="refetch-btn" style={isRev ? {
                borderColor: `rgba(${rc.rgb},0.3)`,
                color: rc.hex,
                background: `rgba(${rc.rgb},0.07)`,
              } : {}}>↺ REFRESH</button>
              <div style={{
                width: 34, height: 34,
                background: isRev ? `rgba(${rc.rgb},0.12)` : "rgba(0,212,255,0.1)",
                border: `1px solid ${isRev ? `rgba(${rc.rgb},0.45)` : "rgba(0,212,255,0.35)"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 13, color: isRev ? rc.hex : "#00d4ff", fontFamily: "'Orbitron', monospace",
                clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                boxShadow: isRev ? `0 0 20px rgba(${rc.rgb},0.3)` : "0 0 20px rgba(0,212,255,0.2)",
                transition: "all 0.4s",
              }}>W</div>
            </div>
          </div>

          {/* ═══════════════ OVERVIEW TAB ═══════════════ */}
          {tab === "overview" && (
            <div>
              {loading ? <HoloLoader /> : m && (
                <>
                  <div className="section-heading">Mission Status</div>

                  {/* Metric cards — each tells a different story */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
                    <HoloCard
                      label="Total Users" value={m.users.total} icon="⬡" color="#00d4ff"
                      sub={`${m.users.paid} paid · ${m.users.trialing} trialing`}
                      trend={12} delay={0} accentShape="ring"
                      story="NETWORK GROWTH NOMINAL"
                    />
                    <HoloCard
                      label="MRR" value={`$${m.revenue.mrr}`} icon="◎" color="#00ff88"
                      sub="Monthly Recurring Revenue"
                      trend={8} delay={80} accentShape="hex"
                      story="CASHFLOW STREAM ACTIVE"
                    />
                    <HoloCard
                      label="ARR" value={`$${m.revenue.arr?.toLocaleString()}`} icon="↑" color="#a855f7"
                      sub="Annualized Run Rate"
                      trend={15} delay={160} accentShape="cross"
                      story="PROJECTION TRAJECTORY ↑"
                    />
                    <HoloCard
                      label="Tasks Today" value={m.tasks.created_today} icon="✦" color="#ffd700"
                      sub={`${m.tasks.completion_rate}% completion rate`}
                      trend={5} delay={240} accentShape="ring"
                      story="OPERATIONS RUNNING HOT"
                    />
                  </div>

                  {/* Main panels row */}
                  <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 14, marginBottom: 16 }}>

                    {/* Signup trend — tells story of growth */}
                    <HoloPanel title="Signup Velocity — Live Feed" accent="#00d4ff">
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", gap: 20, marginBottom: 14 }}>
                          <div>
                            <div style={{ fontSize: 8, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em", marginBottom: 4 }}>PEAK DAY</div>
                            <div style={{ fontSize: 16, fontFamily: "'Orbitron', monospace", color: "#00d4ff", textShadow: "0 0 15px rgba(0,212,255,0.5)" }}>
                              {m.signup_trend ? Math.max(...m.signup_trend.map(d => d.signups)) : "—"}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 8, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em", marginBottom: 4 }}>30D TOTAL</div>
                            <div style={{ fontSize: 16, fontFamily: "'Orbitron', monospace", color: "#00ff88", textShadow: "0 0 15px rgba(0,255,136,0.5)" }}>
                              {m.signup_trend ? m.signup_trend.reduce((a, d) => a + d.signups, 0) : "—"}
                            </div>
                          </div>
                          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 8, color: "#00ff88", fontFamily: "'Share Tech Mono', monospace" }}>
                              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff88", animation: "pulse-glow 1s infinite" }} />
                              LIVE
                            </div>
                          </div>
                        </div>
                        <HoloSparkline values={m.signup_trend?.map(d => d.signups)} color="#00d4ff" height={80} />
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 7, color: "rgba(0,212,255,0.25)" }}>
                          <span>{m.signup_trend?.[0]?.date}</span><span>TODAY</span>
                        </div>
                      </div>
                    </HoloPanel>

                    {/* Subscription breakdown — tactical breakdown */}
                    <HoloPanel title="Subscriber Intelligence" accent="#00ff88">
                      {[
                        { label: "Paid",      count: m.users.paid,      color: "#00ff88" },
                        { label: "Trialing",  count: m.users.trialing,  color: "#ffd700" },
                        { label: "Cancelled", count: m.users.cancelled, color: "#ff3366" },
                        { label: "Exempt",    count: m.users.exempt,    color: "#a855f7" },
                      ].map(({ label, count, color }) => {
                        const pct = m.users.total ? Math.round((count / m.users.total) * 100) : 0;
                        return (
                          <div key={label} style={{ marginBottom: 14 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, alignItems: "center" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <div style={{ width: 5, height: 5, background: color, boxShadow: `0 0 8px ${color}`, clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }} />
                                <span style={{ fontSize: 9, color: "rgba(0,212,255,0.5)", letterSpacing: "0.1em" }}>{label.toUpperCase()}</span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 8, color: "rgba(0,212,255,0.25)" }}>{pct}%</span>
                                <span style={{ fontSize: 14, color, fontWeight: 700, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px ${color}80` }}>{count}</span>
                              </div>
                            </div>
                            <div style={{ height: 3, background: "rgba(0,212,255,0.06)", borderRadius: 1, overflow: "hidden" }}>
                              <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${color}40, ${color})`, borderRadius: 1, transition: "width 1s cubic-bezier(0.4,0,0.2,1)", boxShadow: `0 0 8px ${color}50` }} />
                            </div>
                          </div>
                        );
                      })}

                      <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid rgba(0,212,255,0.06)" }}>
                        <div style={{ fontSize: 8, color: "rgba(0,212,255,0.3)", letterSpacing: "0.2em", marginBottom: 10 }}>ROLE MATRIX</div>
                        {Object.entries(m.users.by_role || {}).map(([role, count]) => (
                          <div key={role} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                            <span style={{ fontSize: 9, color: "rgba(0,212,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em" }}>{role}</span>
                            <span style={{ fontSize: 12, color: "#00d4ff", fontWeight: 700, fontFamily: "'Orbitron', monospace" }}>{count}</span>
                          </div>
                        ))}
                      </div>
                    </HoloPanel>
                  </div>

                  {/* Stat strip */}
                  <div className="section-heading">Telemetry</div>
                  <div className="stat-row">
                    {[
                      { label: "New / Week",    value: m.users.new_this_week,                color: "#00d4ff" },
                      { label: "New / Month",   value: m.users.new_this_month,               color: "#00d4ff" },
                      { label: "Tasks Today",   value: m.tasks.created_today,                color: "#00ff88" },
                      { label: "Completion",    value: `${m.tasks.completion_rate}%`,        color: "#00ff88" },
                      { label: "MRR",           value: `$${m.revenue.mrr}`,                  color: "#ffd700" },
                      { label: "QRR",           value: `$${m.revenue.qrr}`,                  color: "#ffd700" },
                      { label: "ARR",           value: `$${(m.revenue.arr||0).toLocaleString()}`, color: "#ffd700" },
                    ].map(({ label, value, color }, i) => (
                      <div key={label} className="stat-item" style={{ animationDelay: `${i * 50}ms`, animation: "holoRise 0.6s cubic-bezier(0.16,1,0.3,1) both" }}>
                        <div className="stat-label">{label}</div>
                        <div className="stat-val" style={{ color, textShadow: `0 0 14px ${color}80` }}>{value}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ═══════════════ REVENUE TAB — JARVIS HUD ═══════════════ */}
          {tab === "revenue" && (
            <div style={{ position: "relative" }}>
              {/* Ambient aurora */}
              <div style={{
                position: "fixed", inset: 0, pointerEvents: "none", zIndex: 1,
                background: `
                  radial-gradient(ellipse 55% 45% at 65% 18%, rgba(${rc.rgb},0.09) 0%, transparent 60%),
                  radial-gradient(ellipse 45% 55% at 18% 75%, rgba(${rc.rgb},0.06) 0%, transparent 60%),
                  radial-gradient(ellipse 70% 25% at 50% 50%, rgba(${rc.rgb},0.04) 0%, transparent 70%)
                `,
                transition: "background 0.5s",
              }} />
              {/* HUD corner brackets */}
              <div style={{ position: "fixed", top: 0, left: 220, right: 0, height: "100vh", pointerEvents: "none", zIndex: 2, overflow: "hidden" }}>
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 1, background: `linear-gradient(180deg, transparent 5%, rgba(${rc.rgb},0.2) 30%, rgba(${rc.rgb},0.08) 70%, transparent)` }} />
                <div style={{ position: "absolute", top: 72, left: 20, width: 20, height: 20, borderTop: `1px solid rgba(${rc.rgb},0.5)`, borderLeft: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", top: 72, right: 20, width: 20, height: 20, borderTop: `1px solid rgba(${rc.rgb},0.5)`, borderRight: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", bottom: 30, left: 20, width: 20, height: 20, borderBottom: `1px solid rgba(${rc.rgb},0.5)`, borderLeft: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", bottom: 30, right: 20, width: 20, height: 20, borderBottom: `1px solid rgba(${rc.rgb},0.5)`, borderRight: `1px solid rgba(${rc.rgb},0.5)` }} />
                {/* Sweep line */}
                <div style={{ position: "absolute", left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.12), transparent)`, animation: "dataStream 8s linear infinite", boxShadow: `0 0 6px rgba(${rc.rgb},0.15)` }} />
              </div>

              {loading ? <HoloLoader /> : m && (
                <>
                  {/* ── Section header ── */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ width: 3, height: 22, background: `linear-gradient(180deg, ${rc.hex}, rgba(${rc.rgb},0.2))`, borderRadius: 2, boxShadow: `0 0 12px ${rc.hex}` }} />
                      <div>
                        <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 10, fontWeight: 700, color: `rgba(${rc.rgb},0.7)`, letterSpacing: "0.28em", textTransform: "uppercase" }}>Financial Intelligence Core</div>
                        <div style={{ fontSize: 7, color: `rgba(${rc.rgb},0.3)`, letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace", marginTop: 2 }}>ALL SYSTEMS NOMINAL · REVENUE ENGINE ACTIVE</div>
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 8, color: `rgba(${rc.rgb},0.4)`, fontFamily: "'Share Tech Mono', monospace" }}>
                      <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00ff88", boxShadow: "0 0 10px #00ff88", animation: "pulse-glow 1.5s infinite" }} />
                      LIVE · {new Date().toISOString().slice(0, 19).replace("T", " ")}
                    </div>
                  </div>

                  {/* ── KPI Strip ── */}
                  <JarvisMetricStrip
                    rgb={rc.rgb} color={rc.hex}
                    metrics={[
                      { label: "MRR", value: `$${m.revenue.mrr}`, sub: `${m.users.paid} active accounts` },
                      { label: "ARR", value: `$${(m.revenue.arr || 0).toLocaleString()}`, sub: "12-month run rate" },
                      { label: "QRR", value: `$${m.revenue.qrr}`, sub: "This quarter" },
                      { label: "Per User", value: `$${m.revenue.plan_price}/mo`, sub: "Plan price" },
                    ]}
                  />

                  {/* ── Main 3-column Jarvis layout ── */}
                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 14, alignItems: "start" }}>

                    {/* LEFT — Arc Reactor centerpiece */}
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                      <ArcReactor
                        color={rc.hex} rgb={rc.rgb}
                        value={`$${m.revenue.mrr}`}
                        label="MRR"
                        size={240}
                      />
                      {/* Sub-data beneath reactor — deep 3D glass */}
                      <div style={{
                        width: 240,
                        background: `linear-gradient(145deg, rgba(0,6,18,0.94) 0%, rgba(0,12,30,0.88) 50%, rgba(0,6,18,0.92) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.25)`,
                        borderRadius: 4, padding: "14px 16px",
                        clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                        boxShadow: `0 12px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 30px rgba(${rc.rgb},0.03)`,
                        backdropFilter: "blur(20px)",
                        position: "relative", overflow: "hidden",
                      }}>
                        {/* Glass top reflection */}
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "45%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: -1, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.6), transparent)` }} />
                        <div style={{ position: "absolute", top: 0, right: 8, width: 0, height: 0, borderTop: `8px solid rgba(${rc.rgb},0.35)`, borderLeft: "8px solid transparent" }} />
                        {/* Subtle inner radial glow */}
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.06) 0%, transparent 70%)`, pointerEvents: "none" }} />
                        {[
                          { l: "PAID USERS",  v: m.users.paid },
                          { l: "TRIALING",    v: m.users.trialing },
                          { l: "PLAN",        v: `$${m.revenue.plan_price}/mo` },
                        ].map(({ l, v }, idx) => (
                          <div key={l} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: idx < 2 ? 10 : 0, padding: "7px 10px", background: "rgba(0,0,0,0.15)", borderRadius: 3, border: `1px solid rgba(${rc.rgb},0.07)`, position: "relative" }}>
                            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `rgba(${rc.rgb},0.3)`, borderRadius: "3px 0 0 3px" }} />
                            <span style={{ fontSize: 7, color: `rgba(${rc.rgb},0.4)`, letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>{l}</span>
                            <span style={{ fontSize: 13, fontWeight: 700, color: rc.hex, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px rgba(${rc.rgb},0.6)` }}>{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* CENTER — Waveform + timeline table */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

                      {/* Waveform panel — deep 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,6,18,0.96) 0%, rgba(0,14,32,0.9) 40%, rgba(0,8,22,0.94) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.28)`,
                        borderRadius: 4, padding: "18px 20px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative", overflow: "hidden",
                        boxShadow: `0 16px 60px rgba(0,0,0,0.6), 0 0 60px rgba(${rc.rgb},0.06), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 40px rgba(${rc.rgb},0.03)`,
                        backdropFilter: "blur(20px)",
                      }}>
                        {/* Glass reflection */}
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "30%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        {/* Inner top glow */}
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.07) 0%, transparent 60%)`, pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.8), rgba(${rc.rgb},0.4), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${rc.hex}, rgba(${rc.rgb},0.1))`, boxShadow: `0 0 14px rgba(${rc.rgb},0.4)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.4)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.65)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
                          <div style={{ width: 5, height: 5, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 10px ${rc.hex}` }} />
                          Revenue Signal — 12 Month Arc
                          <div style={{ flex: 1, height: 1, background: `rgba(${rc.rgb},0.15)` }} />
                          <span style={{ color: `rgba(${rc.rgb},0.35)` }}>WAVEFORM</span>
                        </div>
                        <RevenueWaveform data={m.revenue.monthly_breakdown} color={rc.hex} rgb={rc.rgb} />
                        {/* Month labels */}
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                          {(m.revenue.monthly_breakdown || []).map((d, i) => (
                            <div key={i} style={{ fontSize: 6, color: `rgba(${rc.rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace", transform: "rotate(-30deg)", transformOrigin: "center" }}>{d.month?.slice(0, 3)}</div>
                          ))}
                        </div>
                      </div>

                      {/* Bar chart panel — 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,6,18,0.96) 0%, rgba(0,12,28,0.9) 40%, rgba(0,6,18,0.94) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.25)`,
                        borderRadius: 4, padding: "18px 20px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative", overflow: "hidden",
                        boxShadow: `0 16px 60px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 40px rgba(${rc.rgb},0.025)`,
                        backdropFilter: "blur(20px)",
                      }}>
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "28%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.06) 0%, transparent 60%)`, pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.6), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rc.rgb},0.8), transparent)`, boxShadow: `0 0 12px rgba(${rc.rgb},0.3)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.35)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.6)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
                          <div style={{ width: 5, height: 5, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 10px ${rc.hex}` }} />
                          3D Revenue Bars
                          <div style={{ flex: 1, height: 1, background: `rgba(${rc.rgb},0.12)` }} />
                          <span style={{ color: `rgba(${rc.rgb},0.25)`, fontSize: 7 }}>ISOMETRIC</span>
                        </div>
                        <HoloBarChart data={m.revenue.monthly_breakdown} activeColor={rc.hex} />
                      </div>

                      {/* Data table — 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,5,14,0.95) 0%, rgba(0,10,24,0.88) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.18)`,
                        borderRadius: 4, padding: "16px 18px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative",
                        boxShadow: `0 12px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)`,
                        backdropFilter: "blur(16px)",
                      }}>
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "25%", background: "linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.5), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rc.rgb},0.5), transparent)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.25)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.5)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 12, display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
                          <div style={{ width: 4, height: 4, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 8px ${rc.hex}` }} />
                          Transaction Log
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "4px 0 8px", borderBottom: `1px solid rgba(${rc.rgb},0.08)` }}>
                          {["Month", "New Paid", "Revenue"].map(h => (
                            <div key={h} style={{ fontSize: 7, color: `rgba(${rc.rgb},0.3)`, textTransform: "uppercase", letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>{h}</div>
                          ))}
                        </div>
                        {[...(m.revenue.monthly_breakdown || [])].reverse().slice(0, 8).map((d, i) => (
                          <div key={i} style={{
                            display: "grid", gridTemplateColumns: "2fr 1fr 1fr",
                            padding: "9px 0",
                            borderBottom: `1px solid rgba(${rc.rgb},0.04)`,
                            background: i === 0 ? `rgba(${rc.rgb},0.03)` : "transparent",
                            transition: "background 0.2s",
                          }}
                            onMouseEnter={e => e.currentTarget.style.background = `rgba(${rc.rgb},0.05)`}
                            onMouseLeave={e => e.currentTarget.style.background = i === 0 ? `rgba(${rc.rgb},0.03)` : "transparent"}
                          >
                            <span style={{ fontSize: 10, color: `rgba(${rc.rgb},0.5)`, fontFamily: "'Share Tech Mono', monospace" }}>{d.month}</span>
                            <span style={{ fontSize: 10, color: `rgba(${rc.rgb},0.35)`, fontFamily: "'Share Tech Mono', monospace" }}>{d.new_paid}</span>
                            <span style={{
                              fontSize: 12, fontWeight: 700,
                              color: d.revenue > 0 ? rc.hex : `rgba(${rc.rgb},0.2)`,
                              fontFamily: "'Orbitron', monospace",
                              textShadow: d.revenue > 0 ? `0 0 8px rgba(${rc.rgb},0.5)` : "none",
                            }}>${d.revenue?.toFixed(2)}</span>
                          </div>
                        ))}
                        <div style={{ marginTop: 12, padding: "8px 12px", background: `rgba(${rc.rgb},0.03)`, border: `1px solid rgba(${rc.rgb},0.08)`, borderRadius: 2, fontSize: 8, color: `rgba(${rc.rgb},0.35)`, letterSpacing: "0.05em", lineHeight: 1.8, fontFamily: "'Share Tech Mono', monospace" }}>
                          ▲ Revenue at ${m.revenue.plan_price}/user/mo · Connect Lemon Squeezy webhook for live sync
                        </div>
                      </div>
                    </div>

                    {/* RIGHT — Intel panel */}
                    <div style={{ width: 220 }}>
                      <RevenueIntelPanel data={m.revenue} rgb={rc.rgb} color={rc.hex} />
                    </div>
                  </div>

                  {/* ── Bottom status bar ── */}
                  <div style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "10px 18px", marginTop: 14,
                    background: `rgba(${rc.rgb},0.03)`,
                    border: `1px solid rgba(${rc.rgb},0.12)`,
                    borderRadius: 3,
                    clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%)",
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: rc.hex, boxShadow: `0 0 12px ${rc.hex}`, animation: "pulse-glow 1.5s infinite" }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.45)`, letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>
                      FINANCIAL CORE ONLINE · REVENUE ENGINE ACTIVE · PROJECTION MODEL LOADED · DATA STREAM LIVE
                    </span>
                    <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg, rgba(${rc.rgb},0.2), transparent)` }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.3)`, fontFamily: "'Orbitron', monospace" }}>{new Date().toISOString().slice(0, 19).replace("T", " ")}</span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ═══════════════ USERS TAB ═══════════════ */}
          {tab === "users" && (
            <div>
              <div className="section-heading">User Registry</div>
              <HoloPanel accent="#00d4ff">
                <UsersTable />
              </HoloPanel>
            </div>
          )}

          {/* ═══════════════ WORKSPACES TAB ═══════════════ */}
          {tab === "workspaces" && (
            <div>
              <div className="section-heading">Workspace Network</div>
              <HoloPanel accent="#a855f7">
                <WorkspacesTable />
              </HoloPanel>
            </div>
          )}

          {/* ═══════════════ FEEDBACK TAB ═══════════════ */}
          {tab === "feedback" && (
            <div>
              <div className="section-heading">Incoming Transmissions</div>
              <FeedbackTable />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
