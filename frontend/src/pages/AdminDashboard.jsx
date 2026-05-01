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
  const [hov, setHov] = useState(null);
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.revenue), 1);
  const base = activeColor || "#00d4ff";
  const colors = [base, base, base, base, base];

  return (
    <div style={{ position: "relative" }}>
      {/* Y-axis labels */}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 28, display: "flex", flexDirection: "column", justifyContent: "space-between", pointerEvents: "none" }}>
        {[1, 0.75, 0.5, 0.25, 0].map(v => (
          <div key={v} style={{ fontSize: 8, color: "rgba(0,212,255,0.3)", fontFamily: "'Share Tech Mono', monospace", textAlign: "right", width: 35 }}>
            ${Math.round(max * v)}
          </div>
        ))}
      </div>

      <div style={{ marginLeft: 42, overflow: "hidden" }}>
        {/* Grid lines */}
        <div style={{ position: "relative" }}>
          {[0.25, 0.5, 0.75, 1].map(v => (
            <div key={v} style={{ position: "absolute", left: 0, right: 0, top: `${(1 - v) * 100}%`, height: 1, background: "rgba(0,212,255,0.06)" }} />
          ))}

          <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 160, padding: "4px 0 0" }}>
            {data.map((d, i) => {
              const isH = hov === i;
              const barH = Math.max(3, (d.revenue / max) * 140);
              const col = colors[i % colors.length];
              return (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2, cursor: "pointer", position: "relative" }}
                  onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)}>
                  {isH && d.revenue > 0 && (
                    <div style={{
                      position: "absolute", bottom: barH + 6, left: "50%", transform: "translateX(-50%)",
                      background: "rgba(0,10,25,0.98)", border: "1px solid rgba(0,212,255,0.4)",
                      borderRadius: 3, padding: "4px 8px", whiteSpace: "nowrap", zIndex: 10,
                      fontSize: 9, color: "#00d4ff", fontFamily: "'Share Tech Mono', monospace",
                    }}>
                      ${d.revenue.toFixed(0)} · {d.new_paid} users
                    </div>
                  )}

                  {/* 3D bar — front face */}
                  <div style={{
                    width: "100%", height: barH,
                    background: `linear-gradient(180deg, ${col}dd 0%, ${col}66 100%)`,
                    boxShadow: isH ? `0 0 20px ${col}55, inset 0 0 10px rgba(255,255,255,0.1)` : `inset 0 0 6px rgba(255,255,255,0.05)`,
                    transition: "all 0.2s",
                    position: "relative",
                    clipPath: "polygon(0 0, 100% 0, 100% 100%, 0 100%)",
                  }}>
                    {/* Shine stripe */}
                    <div style={{ position: "absolute", top: 0, left: "20%", width: "20%", bottom: 0, background: `linear-gradient(180deg, rgba(255,255,255,0.15), rgba(255,255,255,0.03))`, pointerEvents: "none" }} />
                    {/* Top face (3D effect) */}
                    <div style={{ position: "absolute", top: -5, left: 0, right: 0, height: 5, background: `${col}`, opacity: 0.5, transform: "skewX(-45deg) scaleY(0.6)", transformOrigin: "bottom" }} />
                  </div>

                  <div style={{ fontSize: 7, color: "rgba(0,212,255,0.35)", fontFamily: "'Share Tech Mono', monospace", textAlign: "center", marginTop: 4, lineHeight: 1.2, transform: "rotate(-35deg)", transformOrigin: "center" }}>
                    {d.month?.slice(0, 3)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
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
                onClick={() => {
                  localStorage.removeItem("access_token");
                  window.location.href = "/";
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

          {/* ═══════════════ REVENUE TAB ═══════════════ */}
          {tab === "revenue" && (
            <div style={{ position: "relative" }}>
              {/* Full-page aurora layer — covers entire revenue content area */}
              <div style={{
                position: "fixed", inset: 0, pointerEvents: "none", zIndex: 1,
                background: `
                  radial-gradient(ellipse 60% 40% at 70% 20%, rgba(${rc.rgb},0.07) 0%, transparent 60%),
                  radial-gradient(ellipse 50% 50% at 20% 80%, rgba(${rc.rgb},0.05) 0%, transparent 60%),
                  radial-gradient(ellipse 80% 30% at 50% 50%, rgba(${rc.rgb},0.03) 0%, transparent 70%)
                `,
                transition: "background 0.3s",
              }} />
              {/* Animated corner scanner lines */}
              <div style={{
                position: "fixed", top: 0, left: 220, right: 0, height: "100vh",
                pointerEvents: "none", zIndex: 2, overflow: "hidden",
              }}>
                {/* Horizontal sweep line */}
                <div style={{
                  position: "absolute", left: 0, right: 0, height: 1,
                  background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.15), transparent)`,
                  animation: "dataStream 6s linear infinite",
                  boxShadow: `0 0 8px rgba(${rc.rgb},0.2)`,
                }} />
                {/* Corner bracket TL */}
                <div style={{ position: "absolute", top: 80, left: 28, width: 24, height: 24, borderTop: `1px solid rgba(${rc.rgb},0.4)`, borderLeft: `1px solid rgba(${rc.rgb},0.4)` }} />
                {/* Corner bracket BR */}
                <div style={{ position: "absolute", bottom: 40, right: 28, width: 24, height: 24, borderBottom: `1px solid rgba(${rc.rgb},0.4)`, borderRight: `1px solid rgba(${rc.rgb},0.4)` }} />
                {/* Vertical edge glow left */}
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 1, background: `linear-gradient(180deg, transparent, rgba(${rc.rgb},0.25), rgba(${rc.rgb},0.1), transparent)` }} />
              </div>

              {loading ? <HoloLoader /> : m && (
                <>
                  <div className="section-heading" style={{ color: `rgba(${rc.rgb},0.55)` }}>
                    <style>{`
                      .rev-section::before { color: ${rc.hex} !important; }
                      .rev-section::after { background: linear-gradient(90deg, rgba(${rc.rgb},0.3), transparent) !important; }
                    `}</style>
                    Financial Intelligence
                  </div>

                  {/* All four metric cards share the same slowly-cycling color */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
                    <HoloCard label="MRR"      value={`$${m.revenue.mrr}`}                          icon="◎" color={revColor.hex} sub={`${m.users.paid} active accounts`} delay={0}   story="MONTHLY REVENUE STREAM"   accentShape="ring" />
                    <HoloCard label="ARR"      value={`$${(m.revenue.arr||0).toLocaleString()}`}    icon="↑" color={revColor.hex} sub="Annualized run rate"               delay={80}  story="12-MONTH PROJECTION"      accentShape="hex"  />
                    <HoloCard label="QRR"      value={`$${m.revenue.qrr}`}                          icon="◈" color={revColor.hex} sub="This quarter"                      delay={160} story="QUARTERLY VELOCITY"        accentShape="cross"/>
                    <HoloCard label="Per User" value={`$${m.revenue.plan_price}/mo`}                icon="✦" color={revColor.hex} sub="Plan price"                        delay={240} story="UNIT ECONOMICS STABLE"     accentShape="ring" />
                  </div>

                  {/* Revenue timeline panel — border / accents slowly shift color too */}
                  <div style={{
                    marginBottom: 14,
                    background: "linear-gradient(135deg, rgba(0,8,20,0.96) 0%, rgba(0,15,35,0.92) 100%)",
                    border: `1px solid rgba(${revColor.rgb},0.28)`,
                    borderRadius: 4,
                    padding: "20px 22px",
                    backdropFilter: "blur(20px)",
                    boxShadow: `0 8px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(${revColor.rgb},0.06), 0 0 40px rgba(${revColor.rgb},0.05), inset 0 0 30px rgba(${revColor.rgb},0.02)`,
                    position: "relative",
                    overflow: "hidden",
                    clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                    transition: "box-shadow 0.4s, border-color 0.4s",
                  }}>
                    {/* Corner notch */}
                    <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${revColor.rgb},0.35)`, borderLeft: "10px solid transparent", zIndex: 2 }} />
                    <div style={{ position: "absolute", bottom: 0, left: 10, width: 0, height: 0, borderBottom: `10px solid rgba(${revColor.rgb},0.35)`, borderRight: "10px solid transparent", zIndex: 2 }} />
                    {/* Top glow line */}
                    <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${revColor.rgb},0.8), transparent)` }} />
                    {/* Left accent bar */}
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${revColor.rgb},0.9), rgba(${revColor.rgb},0.15))` }} />

                    {/* Panel title */}
                    <div style={{ fontSize: 9, color: `rgba(${revColor.rgb},0.75)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ width: 4, height: 4, background: revColor.hex, borderRadius: "50%", boxShadow: `0 0 8px ${revColor.hex}` }} />
                      Revenue Timeline — 12 Month Arc
                      <div style={{ flex: 1, height: 1, background: `rgba(${revColor.rgb},0.2)` }} />
                    </div>

                    <HoloBarChart data={m.revenue.monthly_breakdown} activeColor={revColor.hex} />

                    <div style={{ marginTop: 24 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "5px 0 10px", borderBottom: "1px solid rgba(0,212,255,0.07)" }}>
                        {["Month", "New Paid", "Revenue"].map(h => (
                          <div key={h} style={{ fontSize: 7, color: "rgba(0,212,255,0.35)", textTransform: "uppercase", letterSpacing: "0.18em" }}>{h}</div>
                        ))}
                      </div>
                      {[...( m.revenue.monthly_breakdown || [])].reverse().slice(0, 8).map((d, i) => (
                        <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "10px 0", borderBottom: "1px solid rgba(0,212,255,0.04)", fontSize: 11 }}>
                          <span style={{ color: "rgba(0,212,255,0.4)", fontFamily: "'Share Tech Mono', monospace" }}>{d.month}</span>
                          <span style={{ color: "rgba(0,212,255,0.3)", fontFamily: "'Share Tech Mono', monospace" }}>{d.new_paid}</span>
                          <span style={{ color: d.revenue > 0 ? revColor.hex : "rgba(0,212,255,0.2)", fontWeight: 700, fontFamily: "'Orbitron', monospace", fontSize: 12, textShadow: d.revenue > 0 ? `0 0 8px rgba(${revColor.rgb},0.5)` : "none" }}>${d.revenue?.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: 16, padding: "10px 14px", background: `rgba(${revColor.rgb},0.03)`, border: `1px solid rgba(${revColor.rgb},0.1)`, borderRadius: 3, fontSize: 9, color: `rgba(${revColor.rgb},0.4)`, lineHeight: 1.8, letterSpacing: "0.05em" }}>
                      ▲ Revenue calculated at ${m.revenue.plan_price}/user/mo. Connect Lemon Squeezy webhook for live payment sync.
                    </div>
                  </div>

                  {/* ── Animated bottom status bar ── */}
                  <div style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "10px 16px",
                    background: `rgba(${rc.rgb},0.03)`,
                    border: `1px solid rgba(${rc.rgb},0.12)`,
                    borderRadius: 3,
                    marginTop: 6,
                    clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: rc.hex, boxShadow: `0 0 12px ${rc.hex}`, animation: "pulse-glow 1.5s infinite" }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.5)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace" }}>FINANCIAL SYSTEMS NOMINAL · REVENUE ENGINE ACTIVE · DATA STREAM LIVE</span>
                    <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg, rgba(${rc.rgb},0.2), transparent)` }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.35)`, fontFamily: "'Orbitron', monospace" }}>{new Date().toISOString().slice(0,19).replace("T"," ")}</span>
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
