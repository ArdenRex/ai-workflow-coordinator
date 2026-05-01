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

// ── 3D Crystal Scene Background ────────────────────────────────────────────────
function CrystalField() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth;
    let H = canvas.height = canvas.offsetHeight;
    let t = 0;

    const crystals = Array.from({ length: 40 }, (_, i) => ({
      x: Math.random() * W, y: Math.random() * H,
      size: Math.random() * 18 + 6,
      speed: Math.random() * 0.3 + 0.05,
      hue: Math.random() > 0.5 ? 270 + Math.random() * 40 : 170 + Math.random() * 40,
      phase: Math.random() * Math.PI * 2,
      rotSpeed: (Math.random() - 0.5) * 0.01,
      rot: Math.random() * Math.PI * 2,
      depth: Math.random() * 3 + 1,
    }));

    const stars = Array.from({ length: 200 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      r: Math.random() * 1.2,
      twinkle: Math.random() * Math.PI * 2,
      speed: Math.random() * 0.02 + 0.005,
    }));

    let raf;
    function drawCrystal(x, y, size, rot, hue, alpha, depth) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(rot);
      const s = size / depth;
      // 3D diamond shape
      ctx.beginPath();
      ctx.moveTo(0, -s * 1.6);
      ctx.lineTo(s * 0.7, -s * 0.3);
      ctx.lineTo(s * 0.5, s * 1.2);
      ctx.lineTo(0, s * 0.7);
      ctx.lineTo(-s * 0.5, s * 1.2);
      ctx.lineTo(-s * 0.7, -s * 0.3);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, -s * 1.6, 0, s * 1.2);
      grad.addColorStop(0, `hsla(${hue}, 100%, 90%, ${alpha * 0.9})`);
      grad.addColorStop(0.3, `hsla(${hue - 20}, 80%, 60%, ${alpha * 0.6})`);
      grad.addColorStop(0.7, `hsla(${hue + 30}, 90%, 40%, ${alpha * 0.4})`);
      grad.addColorStop(1, `hsla(${hue}, 70%, 20%, ${alpha * 0.2})`);
      ctx.fillStyle = grad;
      ctx.fill();
      // highlight facet
      ctx.beginPath();
      ctx.moveTo(0, -s * 1.6);
      ctx.lineTo(s * 0.3, -s * 0.5);
      ctx.lineTo(0, s * 0.2);
      ctx.lineTo(-s * 0.2, -s * 0.5);
      ctx.closePath();
      ctx.fillStyle = `hsla(${hue - 10}, 100%, 95%, ${alpha * 0.35})`;
      ctx.fill();
      // inner glow
      ctx.beginPath();
      ctx.arc(0, 0, s * 0.4, 0, Math.PI * 2);
      const innerGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, s * 0.4);
      innerGrad.addColorStop(0, `hsla(${hue}, 100%, 100%, ${alpha * 0.5})`);
      innerGrad.addColorStop(1, `hsla(${hue}, 100%, 80%, 0)`);
      ctx.fillStyle = innerGrad;
      ctx.fill();
      ctx.restore();
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      t += 0.008;
      // stars
      stars.forEach(s => {
        s.twinkle += s.speed;
        const alpha = 0.3 + Math.sin(s.twinkle) * 0.25;
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,255,255,${alpha})`; ctx.fill();
      });
      // nebula glow blobs
      [[W * 0.15, H * 0.25, 280, 0.03], [W * 0.85, H * 0.7, 200, 0.04], [W * 0.5, H * 0.5, 230, 0.025]].forEach(([cx, cy, r, a]) => {
        const g = ctx.createRadialGradient(cx + Math.sin(t) * 30, cy + Math.cos(t * 0.7) * 20, 0, cx, cy, r);
        g.addColorStop(0, `rgba(140,80,255,${a})`);
        g.addColorStop(0.5, `rgba(80,200,180,${a * 0.4})`);
        g.addColorStop(1, `rgba(0,0,0,0)`);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
      });
      // crystals
      crystals.forEach(c => {
        c.y -= c.speed; c.rot += c.rotSpeed; c.phase += 0.01;
        if (c.y < -50) { c.y = H + 50; c.x = Math.random() * W; }
        const bob = Math.sin(c.phase) * 3;
        const alpha = (0.4 + Math.sin(c.phase * 0.5) * 0.2) / c.depth;
        drawCrystal(c.x, c.y + bob, c.size, c.rot, c.hue, alpha, c.depth);
        // glow halo
        const haloG = ctx.createRadialGradient(c.x, c.y + bob, 0, c.x, c.y + bob, c.size * 2.5 / c.depth);
        haloG.addColorStop(0, `hsla(${c.hue}, 100%, 80%, ${0.12 / c.depth})`);
        haloG.addColorStop(1, `hsla(${c.hue}, 100%, 80%, 0)`);
        ctx.fillStyle = haloG; ctx.beginPath(); ctx.arc(c.x, c.y + bob, c.size * 2.5 / c.depth, 0, Math.PI * 2); ctx.fill();
      });
      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth; H = canvas.height = canvas.offsetHeight; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);
  return <canvas ref={canvasRef} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}

// ── 3D Metric Card ─────────────────────────────────────────────────────────────
function CrystalCard({ label, value, sub, color = "#a855f7", spark, icon, trend, delay = 0 }) {
  const [hov, setHov] = useState(false);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const ref = useRef(null);

  const onMove = (e) => {
    const r = ref.current.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width - 0.5) * 18;
    const y = ((e.clientY - r.top) / r.height - 0.5) * -18;
    setTilt({ x, y });
  };
  const onLeave = () => { setTilt({ x: 0, y: 0 }); setHov(false); };

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={onLeave}
      style={{
        position: "relative",
        borderRadius: 20,
        padding: "22px 20px 18px",
        cursor: "default",
        animationDelay: `${delay}ms`,
        animation: "crystalRise 0.7s cubic-bezier(0.22,1,0.36,1) both",
        transformStyle: "preserve-3d",
        transform: `perspective(800px) rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) ${hov ? "translateZ(12px) scale(1.015)" : "translateZ(0) scale(1)"}`,
        transition: hov ? "transform 0.08s linear" : "transform 0.5s cubic-bezier(0.22,1,0.36,1)",
        background: `linear-gradient(135deg, rgba(8,5,22,0.92) 0%, rgba(14,8,35,0.88) 50%, rgba(8,5,22,0.95) 100%)`,
        border: `1px solid ${hov ? color + "55" : color + "28"}`,
        boxShadow: hov
          ? `0 0 0 1px ${color}18, 0 8px 40px rgba(0,0,0,0.7), 0 0 60px ${color}22, inset 0 1px 0 rgba(255,255,255,0.07)`
          : `0 4px 24px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.04)`,
        backdropFilter: "blur(24px)",
        overflow: "hidden",
      }}
    >
      {/* crystal facet overlay */}
      <div style={{
        position: "absolute", inset: 0, borderRadius: 20, pointerEvents: "none",
        background: `linear-gradient(135deg, rgba(255,255,255,${hov ? 0.06 : 0.02}) 0%, transparent 40%, rgba(${color === "#a855f7" ? "168,85,247" : color === "#34d399" ? "52,211,153" : "251,191,36"},${hov ? 0.05 : 0.01}) 100%)`,
        transition: "opacity 0.3s",
      }} />
      {/* top edge glow */}
      <div style={{
        position: "absolute", top: 0, left: "10%", right: "10%", height: 1,
        background: `linear-gradient(90deg, transparent, ${color}${hov ? "88" : "44"}, transparent)`,
        transition: "opacity 0.3s",
      }} />
      {/* floating icon orb */}
      <div style={{
        position: "absolute", top: 16, right: 16, width: 36, height: 36, borderRadius: "50%",
        background: `radial-gradient(circle at 35% 35%, ${color}33, ${color}11)`,
        border: `1px solid ${color}33`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 16,
        boxShadow: `0 0 20px ${color}22, inset 0 1px 0 rgba(255,255,255,0.1)`,
        transform: `translateZ(8px)`,
        transition: "box-shadow 0.3s",
        ...(hov ? { boxShadow: `0 0 30px ${color}44, inset 0 1px 0 rgba(255,255,255,0.15)` } : {}),
      }}>{icon}</div>
      <div style={{ fontSize: 10, color: color + "99", letterSpacing: "0.15em", textTransform: "uppercase", fontFamily: "'Space Mono', monospace", marginBottom: 10, position: "relative", zIndex: 1 }}>{label}</div>
      <div style={{
        fontSize: 28, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em",
        fontFamily: "'Playfair Display', serif",
        textShadow: `0 0 30px ${color}55`,
        position: "relative", zIndex: 1,
        transform: "translateZ(4px)",
      }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "rgba(200,180,255,0.45)", marginTop: 4, position: "relative", zIndex: 1 }}>{sub}</div>}
      {trend !== undefined && (
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 6, position: "relative", zIndex: 1 }}>
          <div style={{
            fontSize: 10, color: trend >= 0 ? "#4ade80" : "#f87171", fontWeight: 700,
            background: trend >= 0 ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
            border: `1px solid ${trend >= 0 ? "rgba(74,222,128,0.3)" : "rgba(248,113,113,0.3)"}`,
            padding: "1px 7px", borderRadius: 20,
            boxShadow: trend >= 0 ? "0 0 8px rgba(74,222,128,0.2)" : "0 0 8px rgba(248,113,113,0.2)",
          }}>{trend >= 0 ? "↑" : "↓"} {Math.abs(trend)}%</div>
          <span style={{ fontSize: 10, color: "rgba(148,163,184,0.35)" }}>vs last month</span>
        </div>
      )}
      {spark && (
        <div style={{ marginTop: 14, position: "relative", zIndex: 1 }}>
          <CrystalSparkline values={spark} color={color} />
        </div>
      )}
      <div style={{
        position: "absolute", bottom: 0, left: 0, right: 0, height: 2, borderRadius: "0 0 20px 20px",
        background: `linear-gradient(90deg, transparent, ${color}${hov ? "88" : "44"}, transparent)`,
        transition: "opacity 0.3s",
      }} />
    </div>
  );
}

function CrystalSparkline({ values, color = "#a855f7" }) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values, 1); const min = Math.min(...values);
  const range = max - min || 1;
  const w = 100, h = 36;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 6) - 3;
    return `${x},${y}`;
  });
  const gradId = `sg-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 36 }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.5" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
        <filter id="glow-spark">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={`url(#${gradId})`} stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" filter="url(#glow-spark)" />
    </svg>
  );
}

// ── 3D Bar Chart ───────────────────────────────────────────────────────────────
function CrystalBarChart({ data }) {
  const [hov, setHov] = useState(null);
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.revenue), 1);
  return (
    <div style={{ overflowX: "auto", paddingBottom: 4 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 160, minWidth: data.length * 50, padding: "0 4px", paddingTop: 30 }}>
        {data.map((d, i) => {
          const isH = hov === i;
          const h = Math.max(6, (d.revenue / max) * 130);
          return (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, cursor: "pointer" }}
              onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)}>
              {isH && d.revenue > 0 && (
                <div style={{
                  fontSize: 10, color: "#f0e6ff", background: "rgba(8,4,20,0.97)",
                  border: "1px solid rgba(168,85,247,0.5)", borderRadius: 8,
                  padding: "4px 8px", whiteSpace: "nowrap",
                  boxShadow: "0 0 20px rgba(168,85,247,0.4), 0 0 40px rgba(168,85,247,0.15)",
                  fontFamily: "'Space Mono', monospace",
                }}>${d.revenue.toFixed(0)}</div>
              )}
              {!isH && <div style={{ height: 22 }} />}
              {/* 3D bar */}
              <div style={{ width: "100%", position: "relative", height: h }}>
                {/* front face */}
                <div style={{
                  position: "absolute", bottom: 0, left: "8%", right: "8%", height: "100%",
                  background: d.revenue > 0
                    ? isH
                      ? "linear-gradient(180deg, #f0abff 0%, #a855f7 30%, #7c3aed 70%, #4c1d95 100%)"
                      : "linear-gradient(180deg, rgba(192,132,252,0.8) 0%, rgba(139,92,246,0.7) 40%, rgba(109,40,217,0.5) 100%)"
                    : "rgba(18,12,40,0.4)",
                  borderRadius: "4px 4px 2px 2px",
                  transition: "all 0.25s cubic-bezier(0.4,0,0.2,1)",
                  opacity: hov !== null && !isH ? 0.3 : 1,
                  boxShadow: isH ? "0 0 30px rgba(168,85,247,0.6), 0 -6px 20px rgba(168,85,247,0.4)" : d.revenue > 0 ? "0 0 10px rgba(168,85,247,0.2)" : "none",
                }} />
                {/* top face 3D */}
                {d.revenue > 0 && (
                  <div style={{
                    position: "absolute", top: -5, left: "8%", right: "0%", height: 8,
                    background: isH ? "linear-gradient(135deg, #fde8ff, #e879f9)" : "rgba(200,160,255,0.4)",
                    borderRadius: "3px 5px 3px 0", transform: "skewX(-20deg)",
                    opacity: hov !== null && !isH ? 0.3 : 1,
                    transition: "all 0.25s",
                  }} />
                )}
                {/* right face 3D */}
                {d.revenue > 0 && (
                  <div style={{
                    position: "absolute", bottom: 0, right: "-6%", width: "14%", height: "93%",
                    background: isH ? "linear-gradient(180deg, rgba(120,50,200,0.9), rgba(80,20,150,0.7))" : "rgba(100,50,180,0.25)",
                    borderRadius: "0 2px 2px 0", transform: "skewY(-8deg)",
                    opacity: hov !== null && !isH ? 0.3 : 1,
                    transition: "all 0.25s",
                  }} />
                )}
              </div>
              <div style={{ fontSize: 9, color: isH ? "#c084fc" : "rgba(148,163,184,0.35)", textAlign: "center", transition: "color 0.2s", fontWeight: isH ? 700 : 400, fontFamily: "'Space Mono', monospace" }}>
                {d.month?.split(" ")[0]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Signup Trend ───────────────────────────────────────────────────────────────
function SignupTrend({ data }) {
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.signups), 1);
  const w = 100, h = 70;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (d.signups / max) * (h - 6) - 3;
    return `${x},${y}`;
  });
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 70 }}>
      <defs>
        <linearGradient id="signup-g" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#34d399" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
        </linearGradient>
        <filter id="glow-line"><feGaussianBlur stdDeviation="1.5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill="url(#signup-g)" stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke="#34d399" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" filter="url(#glow-line)" />
    </svg>
  );
}

// ── Badge ───────────────────────────────────────────────────────────────────────
function Badge({ text }) {
  const map = {
    active:    { bg: "rgba(52,211,153,0.08)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    trialing:  { bg: "rgba(251,191,36,0.08)", color: "#fbbf24", border: "rgba(251,191,36,0.25)" },
    cancelled: { bg: "rgba(248,113,113,0.08)", color: "#f87171", border: "rgba(248,113,113,0.25)" },
    exempt:    { bg: "rgba(168,85,247,0.08)", color: "#a855f7", border: "rgba(168,85,247,0.25)" },
    paid:      { bg: "rgba(52,211,153,0.08)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    open:      { bg: "rgba(251,191,36,0.08)", color: "#fbbf24", border: "rgba(251,191,36,0.25)" },
    resolved:  { bg: "rgba(52,211,153,0.08)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    admin:     { bg: "rgba(168,85,247,0.08)", color: "#a855f7", border: "rgba(168,85,247,0.25)" },
    member:    { bg: "rgba(148,163,184,0.06)", color: "#94a3b8", border: "rgba(148,163,184,0.15)" },
  };
  const s = map[text?.toLowerCase()] || { bg: "rgba(148,163,184,0.06)", color: "#94a3b8", border: "rgba(148,163,184,0.15)" };
  return (
    <span style={{
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      padding: "2px 10px", borderRadius: 20, fontSize: 10.5, fontWeight: 700,
      letterSpacing: "0.06em", textTransform: "uppercase",
      boxShadow: `0 0 10px ${s.bg}`,
      fontFamily: "'Space Mono', monospace",
    }}>{text}</span>
  );
}

// ── 3D Nav Tab ─────────────────────────────────────────────────────────────────
function NavTab({ label, active, onClick, count, icon }) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "11px 20px", width: "100%", border: "none",
      background: active
        ? "linear-gradient(135deg, rgba(88,28,135,0.35) 0%, rgba(55,15,100,0.25) 100%)"
        : "transparent",
      color: active ? "#e9d5ff" : "rgba(148,163,184,0.45)",
      fontSize: 13, fontWeight: 500, cursor: "pointer",
      transition: "all 0.2s cubic-bezier(0.22,1,0.36,1)",
      fontFamily: "'Syne', sans-serif",
      position: "relative", textAlign: "left", borderRadius: 12,
      marginBottom: 2, marginLeft: 8, marginRight: 8,
      boxShadow: active ? "0 4px 20px rgba(88,28,135,0.25), inset 0 1px 0 rgba(255,255,255,0.06)" : "none",
      borderLeft: active ? "2px solid rgba(168,85,247,0.7)" : "2px solid transparent",
      transform: active ? "translateX(2px)" : "translateX(0)",
    }}>
      <span style={{ fontSize: 15, filter: active ? `drop-shadow(0 0 6px rgba(168,85,247,0.8))` : "none", transition: "filter 0.3s" }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
      {count !== undefined && (
        <span style={{
          fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20,
          background: active ? "rgba(168,85,247,0.25)" : "rgba(148,163,184,0.08)",
          color: active ? "#c084fc" : "rgba(148,163,184,0.4)",
          border: `1px solid ${active ? "rgba(168,85,247,0.3)" : "rgba(148,163,184,0.1)"}`,
          fontFamily: "'Space Mono', monospace",
        }}>{count}</span>
      )}
    </button>
  );
}

const td = { padding: "13px 14px", color: "rgba(148,163,184,0.6)", whiteSpace: "nowrap" };

// ── Users Table ────────────────────────────────────────────────────────────────
function UsersTable() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => { const t = setTimeout(() => setDebouncedSearch(search), 400); return () => clearTimeout(t); }, [search]);
  const params = new URLSearchParams({ limit: 100 });
  if (debouncedSearch) params.set("search", debouncedSearch);
  if (statusFilter) params.set("status", statusFilter);
  const { data, loading, refetch } = useAdminFetch(`/admin/users?${params}`);
  const handleToggleActive = async (userId, current) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/users/${userId}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !current }) });
    refetch();
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 22 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: "rgba(168,85,247,0.5)", fontSize: 15 }}>⌕</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or email…" className="crystal-input" style={{ paddingLeft: 38, width: "100%" }} />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="crystal-input" style={{ flex: "0 0 180px" }}>
          <option value="">All statuses</option>
          <option value="trialing">Trialing</option>
          <option value="active">Active (paid)</option>
          <option value="cancelled">Cancelled</option>
          <option value="exempt">Exempt</option>
        </select>
      </div>
      {loading ? <CrystalLoader /> : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                {["#", "Name", "Email", "Role", "Status", "Workspace", "Trial Ends", "Joined", "Action"].map(h => (
                  <th key={h} style={{ padding: "10px 14px", textAlign: "left", color: "rgba(168,85,247,0.6)", fontWeight: 700, fontSize: 9, textTransform: "uppercase", letterSpacing: "0.14em", borderBottom: "1px solid rgba(168,85,247,0.12)", whiteSpace: "nowrap", fontFamily: "'Space Mono', monospace" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.users?.map((u, idx) => (
                <tr key={u.id} className="crystal-row">
                  <td style={{ ...td, color: "rgba(148,163,184,0.3)", fontSize: 11 }}>{idx + 1}</td>
                  <td style={{ ...td, fontWeight: 600, color: "#ede9fe" }}>{u.name}</td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.5)", fontFamily: "'Space Mono', monospace", fontSize: 11 }}>{u.email}</td>
                  <td style={td}><Badge text={u.role} /></td>
                  <td style={td}><Badge text={u.subscription_status} /></td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>{u.workspace_id ?? "—"}</td>
                  <td style={{ ...td, color: u.trial_expired ? "#f87171" : "rgba(148,163,184,0.45)" }}>
                    {u.trial_ends_at ? new Date(u.trial_ends_at).toLocaleDateString() : "—"}
                    {u.trial_expired && <span style={{ marginLeft: 4, fontSize: 10 }}>⚠</span>}
                  </td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>{u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}</td>
                  <td style={td}>
                    {u.email === "wahaj@acedengroup.com" ? (
                      <span style={{ fontSize: 10, color: "#c084fc", background: "rgba(168,85,247,0.12)", border: "1px solid rgba(168,85,247,0.3)", padding: "3px 10px", borderRadius: 20, fontWeight: 700, boxShadow: "0 0 12px rgba(168,85,247,0.2)" }}>⬡ Super Admin</span>
                    ) : (
                      <button onClick={() => handleToggleActive(u.id, u.is_active)} style={{
                        fontSize: 10, fontWeight: 700, padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontFamily: "'Space Mono', monospace",
                        background: u.is_active ? "rgba(52,211,153,0.1)" : "rgba(248,113,113,0.08)",
                        color: u.is_active ? "#34d399" : "#f87171",
                        boxShadow: u.is_active ? "0 0 12px rgba(52,211,153,0.2)" : "0 0 12px rgba(248,113,113,0.15)",
                        border: `1px solid ${u.is_active ? "rgba(52,211,153,0.3)" : "rgba(248,113,113,0.25)"}`,
                        transition: "all 0.2s",
                      }}>{u.is_active ? "● Active" : "○ Disabled"}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 14, color: "rgba(148,163,184,0.4)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "#a855f7", fontWeight: 700, textShadow: "0 0 10px #a855f7" }}>{data?.total}</span>
            <span>total users</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Workspaces Table ───────────────────────────────────────────────────────────
function WorkspacesTable() {
  const { data, loading, refetch } = useAdminFetch("/admin/workspaces?limit=100");
  const handleToggleWorkspace = async (wsId, current) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/workspaces/${wsId}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !current }) });
    refetch();
  };
  if (loading) return <CrystalLoader />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["#", "Workspace", "Owner", "Members", "Tasks", "Created", "Action"].map(h => (
              <th key={h} style={{ padding: "10px 14px", textAlign: "left", color: "rgba(168,85,247,0.6)", fontWeight: 700, fontSize: 9, textTransform: "uppercase", letterSpacing: "0.14em", borderBottom: "1px solid rgba(168,85,247,0.12)", whiteSpace: "nowrap", fontFamily: "'Space Mono', monospace" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data?.workspaces?.map((ws, idx) => {
            const isActive = ws.is_active !== false;
            return (
              <tr key={ws.id} className="crystal-row">
                <td style={{ ...td, color: "rgba(148,163,184,0.3)", fontSize: 11 }}>{idx + 1}</td>
                <td style={{ ...td, fontWeight: 600, color: "#ede9fe" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: 10,
                      background: isActive ? "linear-gradient(135deg, rgba(109,40,217,0.7), rgba(168,85,247,0.8))" : "rgba(18,12,40,0.7)",
                      border: isActive ? "1px solid rgba(168,85,247,0.4)" : "1px solid rgba(168,85,247,0.1)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 700, color: isActive ? "#fff" : "rgba(148,163,184,0.3)",
                      flexShrink: 0, boxShadow: isActive ? "0 0 16px rgba(168,85,247,0.3), inset 0 1px 0 rgba(255,255,255,0.1)" : "none",
                    }}>{ws.name?.[0]?.toUpperCase() || "W"}</div>
                    <span style={{ color: isActive ? "#ede9fe" : "rgba(148,163,184,0.3)" }}>{ws.name}</span>
                  </div>
                </td>
                <td style={{ ...td, color: "rgba(148,163,184,0.5)", fontFamily: "'Space Mono', monospace", fontSize: 11 }}>{ws.owner_email ?? "—"}</td>
                <td style={td}><span style={{ color: "#a855f7", fontWeight: 700, textShadow: "0 0 8px rgba(168,85,247,0.6)" }}>{ws.member_count}</span></td>
                <td style={td}><span style={{ color: "#34d399", fontWeight: 600, textShadow: "0 0 8px rgba(52,211,153,0.5)" }}>{ws.task_count}</span></td>
                <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>{ws.created_at ? new Date(ws.created_at).toLocaleDateString() : "—"}</td>
                <td style={td}>
                  {ws.owner_email === "wahaj@acedengroup.com" ? (
                    <span style={{ fontSize: 10, color: "#c084fc", background: "rgba(168,85,247,0.12)", border: "1px solid rgba(168,85,247,0.3)", padding: "3px 10px", borderRadius: 20, fontWeight: 700 }}>⬡ Protected</span>
                  ) : (
                    <button onClick={() => handleToggleWorkspace(ws.id, isActive)} style={{
                      fontSize: 10, fontWeight: 700, padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontFamily: "'Space Mono', monospace",
                      background: isActive ? "rgba(52,211,153,0.1)" : "rgba(248,113,113,0.08)",
                      color: isActive ? "#34d399" : "#f87171",
                      border: `1px solid ${isActive ? "rgba(52,211,153,0.3)" : "rgba(248,113,113,0.25)"}`,
                      boxShadow: isActive ? "0 0 12px rgba(52,211,153,0.2)" : "0 0 12px rgba(248,113,113,0.15)",
                      transition: "all 0.2s",
                    }}>{isActive ? "● Active" : "○ Disabled"}</button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ marginTop: 14, color: "rgba(148,163,184,0.4)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "#a855f7", fontWeight: 700, textShadow: "0 0 10px #a855f7" }}>{data?.total}</span>
        <span>total workspaces</span>
      </div>
    </div>
  );
}

// ── Feedback ────────────────────────────────────────────────────────────────────
function FeedbackTable() {
  const { data, loading } = useAdminFetch("/admin/feedback?limit=100");
  if (loading) return <CrystalLoader />;
  const typeStyle = {
    bug:             { bg: "rgba(248,113,113,0.06)", color: "#f87171", border: "rgba(248,113,113,0.25)", icon: "🐛" },
    feedback:        { bg: "rgba(168,85,247,0.06)", color: "#c084fc", border: "rgba(168,85,247,0.25)", icon: "💬" },
    feature_request: { bg: "rgba(52,211,153,0.06)", color: "#34d399", border: "rgba(52,211,153,0.25)", icon: "✦" },
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {data?.items?.map(f => {
        const ts = typeStyle[f.type] || { bg: "rgba(148,163,184,0.06)", color: "#94a3b8", border: "rgba(148,163,184,0.2)", icon: "•" };
        return (
          <div key={f.id} className="feedback-card-3d">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ background: ts.bg, color: ts.color, border: `1px solid ${ts.border}`, padding: "2px 10px", borderRadius: 20, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", display: "flex", alignItems: "center", gap: 4, boxShadow: `0 0 12px ${ts.border}`, fontFamily: "'Space Mono', monospace" }}>{ts.icon} {f.type.replace("_", " ")}</span>
                <span style={{ color: "#ede9fe", fontWeight: 600, fontSize: 13 }}>{f.title}</span>
              </div>
              <Badge text={f.status} />
            </div>
            <p style={{ color: "rgba(148,163,184,0.55)", fontSize: 12.5, margin: "0 0 12px", lineHeight: 1.8 }}>{f.message}</p>
            <div style={{ display: "flex", gap: 16, fontSize: 11, color: "rgba(148,163,184,0.35)", flexWrap: "wrap" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "rgba(168,85,247,0.5)" }}>◎</span>
                <span style={{ color: "rgba(148,163,184,0.55)" }}>{f.user_name ?? "Anonymous"}</span>
                {f.user_email && <span>({f.user_email})</span>}
              </span>
              {f.page_context && <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "rgba(52,211,153,0.5)" }}>⊕</span> {f.page_context}</span>}
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "rgba(168,85,247,0.5)" }}>◷</span>{f.created_at ? new Date(f.created_at).toLocaleString() : "—"}</span>
            </div>
          </div>
        );
      })}
      {!data?.items?.length && (
        <div style={{ textAlign: "center", padding: 80, color: "rgba(148,163,184,0.25)" }}>
          <div style={{ fontSize: 44, marginBottom: 14, filter: "drop-shadow(0 0 24px rgba(168,85,247,0.5))" }}>✦</div>
          <div style={{ fontSize: 14, letterSpacing: "0.1em" }}>No feedback submissions yet</div>
        </div>
      )}
    </div>
  );
}

// ── Loader ──────────────────────────────────────────────────────────────────────
function CrystalLoader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 80, gap: 24 }}>
      <div style={{ position: "relative", width: 60, height: 60 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            position: "absolute", inset: i * 8, borderRadius: "50%",
            border: `1.5px solid transparent`,
            borderTop: `1.5px solid ${["#a855f7", "#34d399", "#818cf8"][i]}`,
            animation: `spin ${0.9 + i * 0.3}s linear infinite ${i % 2 ? "reverse" : ""}`,
            boxShadow: `0 0 ${12 - i * 2}px ${["rgba(168,85,247,0.4)", "rgba(52,211,153,0.4)", "rgba(129,140,248,0.4)"][i]}`,
          }} />
        ))}
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, filter: "drop-shadow(0 0 8px rgba(168,85,247,0.8))",
          animation: "pulse-glow 2s ease-in-out infinite",
        }}>✦</div>
      </div>
      <span style={{ color: "rgba(168,85,247,0.5)", fontSize: 10, letterSpacing: "0.25em", textTransform: "uppercase", fontFamily: "'Space Mono', monospace" }}>Channeling data…</span>
    </div>
  );
}

// ── Glass Panel ─────────────────────────────────────────────────────────────────
function GlassPanel({ children, style = {} }) {
  return (
    <div style={{
      background: "linear-gradient(135deg, rgba(8,5,22,0.88) 0%, rgba(12,7,30,0.82) 100%)",
      border: "1px solid rgba(168,85,247,0.15)",
      borderRadius: 20,
      padding: 24,
      backdropFilter: "blur(24px)",
      boxShadow: "0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04), 0 0 0 1px rgba(168,85,247,0.05)",
      position: "relative",
      overflow: "hidden",
      ...style,
    }}>
      <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: "linear-gradient(90deg, transparent, rgba(168,85,247,0.3), transparent)", pointerEvents: "none" }} />
      {children}
    </div>
  );
}

// ── Main Dashboard ──────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [tab, setTab] = useState("overview");
  const { data: metrics, loading, error, refetch } = useAdminFetch("/admin/metrics");
  const m = metrics;
  const [time, setTime] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(t); }, []);
  const timeStr = time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dateStr = time.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  const TABS = [
    { id: "overview",    label: "Overview",    icon: "◈", count: undefined },
    { id: "revenue",     label: "Revenue",     icon: "◎", count: m ? 4 : undefined },
    { id: "users",       label: "Users",       icon: "⬡", count: m?.users?.total },
    { id: "workspaces",  label: "Workspaces",  icon: "⊞", count: undefined },
    { id: "feedback",    label: "Feedback",    icon: "✦", count: undefined },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#04020d", color: "#ede9fe", position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600;700;900&family=Syne:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #04020d; }

        /* ── DEEP SPACE BG ── */
        .cosmos-bg {
          position: fixed; inset: 0;
          background:
            radial-gradient(ellipse 80% 60% at 20% 10%, rgba(60,15,120,0.35) 0%, transparent 60%),
            radial-gradient(ellipse 60% 50% at 80% 80%, rgba(10,60,80,0.25) 0%, transparent 60%),
            radial-gradient(ellipse 40% 30% at 60% 40%, rgba(30,5,80,0.2) 0%, transparent 70%),
            #04020d;
          pointer-events: none; z-index: 0;
        }

        /* animated aurora top */
        .aurora-veil {
          position: fixed; top: 0; left: 0; right: 0; height: 3px;
          background: linear-gradient(90deg,
            transparent 0%,
            rgba(88,28,135,0.6) 15%,
            rgba(168,85,247,1) 30%,
            rgba(99,235,200,0.8) 50%,
            rgba(168,85,247,0.9) 70%,
            rgba(88,28,135,0.6) 85%,
            transparent 100%);
          pointer-events: none; z-index: 30;
          filter: blur(0.5px);
          animation: auroraShift 8s ease-in-out infinite alternate;
        }
        .aurora-veil-2 {
          position: fixed; top: 0; left: 0; right: 0; height: 120px;
          background: linear-gradient(180deg, rgba(88,28,135,0.08) 0%, transparent 100%);
          pointer-events: none; z-index: 0;
        }

        @keyframes auroraShift {
          0% { background-position: 0% 0%; opacity: 0.7; }
          50% { opacity: 1; }
          100% { background-position: 100% 0%; opacity: 0.8; }
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes crystalRise {
          from { opacity: 0; transform: perspective(800px) translateY(30px) translateZ(-20px); }
          to { opacity: 1; transform: perspective(800px) translateY(0) translateZ(0); }
        }
        @keyframes pulse-glow {
          0%, 100% { filter: drop-shadow(0 0 8px rgba(168,85,247,0.8)); }
          50% { filter: drop-shadow(0 0 16px rgba(168,85,247,1)) drop-shadow(0 0 30px rgba(168,85,247,0.6)); }
        }
        @keyframes float-orb {
          0%, 100% { transform: translateY(0) scale(1); }
          50% { transform: translateY(-6px) scale(1.02); }
        }
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        @keyframes halo-rotate {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .dashboard-root {
          font-family: 'Syne', sans-serif;
          display: flex; min-height: 100vh;
          position: relative; z-index: 1;
        }

        /* ── SIDEBAR ── */
        .sidebar {
          width: 238px; min-height: 100vh;
          background: linear-gradient(180deg, rgba(6,3,18,0.97) 0%, rgba(8,4,22,0.95) 100%);
          border-right: 1px solid rgba(168,85,247,0.12);
          display: flex; flex-direction: column;
          position: fixed; top: 0; left: 0; bottom: 0; z-index: 10;
          backdrop-filter: blur(30px);
        }
        .sidebar::after {
          content: '';
          position: absolute; top: 15%; right: -1px; bottom: 15%;
          width: 1px;
          background: linear-gradient(180deg, transparent, rgba(168,85,247,0.5), rgba(52,211,153,0.4), rgba(168,85,247,0.5), transparent);
          animation: pulse-glow 4s ease-in-out infinite;
        }

        .logo-orb {
          width: 44px; height: 44px; border-radius: 14px;
          background: linear-gradient(135deg, rgba(88,28,135,0.95), rgba(168,85,247,0.9));
          display: flex; align-items: center; justify-content: center;
          font-family: 'Playfair Display', serif;
          font-size: 20px; font-weight: 900; color: #fff;
          box-shadow: 0 0 30px rgba(168,85,247,0.5), 0 0 60px rgba(168,85,247,0.2), inset 0 1px 0 rgba(255,255,255,0.2);
          border: 1px solid rgba(168,85,247,0.5);
          position: relative; animation: float-orb 4s ease-in-out infinite;
        }
        .logo-orb::before {
          content: ''; position: absolute; inset: -3px; border-radius: 17px;
          border: 1px solid rgba(168,85,247,0.2); animation: halo-rotate 8s linear infinite;
          background: linear-gradient(90deg, rgba(168,85,247,0.15), transparent, rgba(52,211,153,0.1), transparent, rgba(168,85,247,0.15));
        }

        .section-divider {
          height: 1px; margin: 12px 20px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.2), transparent);
        }

        /* ── MAIN ── */
        .main-content {
          margin-left: 238px; flex: 1; padding: 28px 32px;
          min-height: 100vh;
        }

        /* ── TOPBAR ── */
        .topbar {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 28px; padding-bottom: 20px;
          border-bottom: 1px solid rgba(168,85,247,0.1);
        }

        /* ── SECTION HEADING ── */
        .section-heading {
          font-family: 'Playfair Display', serif;
          font-size: 22px; font-weight: 700;
          color: #fff;
          letter-spacing: -0.02em;
          margin-bottom: 20px;
          text-shadow: 0 0 30px rgba(168,85,247,0.4);
          position: relative;
          display: inline-block;
        }
        .section-heading::after {
          content: '';
          position: absolute; bottom: -6px; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg, rgba(168,85,247,0.6), rgba(52,211,153,0.3), transparent);
        }

        /* ── GLASS PANEL ── */
        .panel-title {
          font-size: 11px; font-weight: 700;
          color: rgba(168,85,247,0.7);
          letter-spacing: 0.14em; text-transform: uppercase;
          font-family: 'Space Mono', monospace;
          margin-bottom: 16px;
          display: flex; align-items: center; gap: 8px;
        }
        .panel-title::before {
          content: '';
          display: inline-block; width: 4px; height: 4px;
          border-radius: 50%; background: rgba(168,85,247,0.8);
          box-shadow: 0 0 8px rgba(168,85,247,0.8);
        }

        /* ── ROWS ── */
        .stat-row {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
          gap: 12px; margin-top: 20px;
        }
        .stat-item {
          background: linear-gradient(135deg, rgba(8,5,22,0.85), rgba(12,7,30,0.8));
          border: 1px solid rgba(168,85,247,0.12);
          border-radius: 16px; padding: 16px 16px;
          text-align: center;
          transition: all 0.2s;
          position: relative; overflow: hidden;
          animation: crystalRise 0.6s cubic-bezier(0.22,1,0.36,1) both;
        }
        .stat-item::before {
          content: ''; position: absolute; top: 0; left: "20%"; right: "20%"; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.25), transparent);
        }
        .stat-item:hover {
          border-color: rgba(168,85,247,0.28);
          transform: translateY(-2px);
          box-shadow: 0 8px 30px rgba(0,0,0,0.4), 0 0 20px rgba(168,85,247,0.1);
        }
        .stat-label {
          font-size: 9px; color: rgba(148,163,184,0.45);
          text-transform: uppercase; letter-spacing: 0.14em;
          margin-bottom: 8px; font-family: 'Space Mono', monospace;
        }
        .stat-val {
          font-size: 20px; font-weight: 700;
          font-family: 'Playfair Display', serif;
          letter-spacing: -0.02em;
        }

        /* ── TABLE ROWS ── */
        .crystal-row { transition: background 0.15s; }
        .crystal-row:hover { background: rgba(168,85,247,0.04); }
        .crystal-row td { border-bottom: 1px solid rgba(168,85,247,0.05); }

        /* ── INPUTS ── */
        .crystal-input {
          background: rgba(8,5,22,0.8);
          border: 1px solid rgba(168,85,247,0.2);
          border-radius: 12px; color: #ede9fe;
          font-size: 13px; padding: 10px 14px;
          font-family: 'Syne', sans-serif;
          outline: none; transition: all 0.2s;
          backdrop-filter: blur(10px);
        }
        .crystal-input:focus {
          border-color: rgba(168,85,247,0.5);
          box-shadow: 0 0 0 3px rgba(168,85,247,0.1), 0 0 20px rgba(168,85,247,0.1);
        }
        .crystal-input option { background: #0c0618; }

        /* ── FEEDBACK CARD ── */
        .feedback-card-3d {
          background: linear-gradient(135deg, rgba(8,5,22,0.88), rgba(12,7,30,0.82));
          border: 1px solid rgba(168,85,247,0.13);
          border-radius: 18px; padding: 20px;
          transition: all 0.25s cubic-bezier(0.22,1,0.36,1);
          position: relative; overflow: hidden;
        }
        .feedback-card-3d::before {
          content: ''; position: absolute; top: 0; left: 15%; right: 15%; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.25), transparent);
        }
        .feedback-card-3d:hover {
          border-color: rgba(168,85,247,0.28);
          transform: translateY(-2px) translateZ(4px);
          box-shadow: 0 12px 40px rgba(0,0,0,0.5), 0 0 30px rgba(168,85,247,0.08);
        }

        /* refetch btn */
        .refetch-btn {
          background: rgba(168,85,247,0.1);
          border: 1px solid rgba(168,85,247,0.3);
          color: #c084fc; border-radius: 12px;
          padding: 8px 16px; font-size: 12px;
          cursor: pointer; font-family: 'Space Mono', monospace;
          transition: all 0.2s; letter-spacing: 0.05em;
        }
        .refetch-btn:hover {
          background: rgba(168,85,247,0.18);
          box-shadow: 0 0 20px rgba(168,85,247,0.2);
        }

        /* scrollbar */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: rgba(8,5,22,0.5); }
        ::-webkit-scrollbar-thumb { background: rgba(168,85,247,0.3); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(168,85,247,0.5); }
      `}</style>

      {/* bg layers */}
      <div className="cosmos-bg" />
      <div className="aurora-veil" />
      <div className="aurora-veil-2" />
      <CrystalField />

      <div className="dashboard-root">
        {/* ── SIDEBAR ── */}
        <aside className="sidebar">
          {/* logo */}
          <div style={{ padding: "28px 22px 22px", borderBottom: "1px solid rgba(168,85,247,0.08)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div className="logo-orb">Ω</div>
              <div>
                <div style={{ fontFamily: "'Playfair Display', serif", fontSize: 14, fontWeight: 700, color: "#ede9fe", letterSpacing: 0.02 }}>ArcaneOS</div>
                <div style={{ fontSize: 9, color: "rgba(168,85,247,0.5)", letterSpacing: "0.2em", textTransform: "uppercase", fontFamily: "'Space Mono', monospace", marginTop: 2 }}>Admin Console</div>
              </div>
            </div>
          </div>

          {/* time crystal */}
          <div style={{ margin: "16px 16px 8px", background: "rgba(168,85,247,0.04)", border: "1px solid rgba(168,85,247,0.1)", borderRadius: 14, padding: "12px 16px" }}>
            <div style={{ fontFamily: "'Space Mono', monospace", fontSize: 18, fontWeight: 700, color: "#c084fc", letterSpacing: "0.05em", textShadow: "0 0 20px rgba(168,85,247,0.6)" }}>{timeStr}</div>
            <div style={{ fontSize: 10, color: "rgba(148,163,184,0.4)", marginTop: 2 }}>{dateStr}</div>
          </div>

          <div className="section-divider" />

          {/* nav */}
          <div style={{ padding: "0 0 8px", flex: 1 }}>
            <div style={{ fontSize: 8, color: "rgba(148,163,184,0.2)", letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Space Mono', monospace", padding: "0 22px 8px" }}>Navigation</div>
            {TABS.map(t => (
              <NavTab key={t.id} label={t.label} active={tab === t.id} onClick={() => setTab(t.id)} count={t.count} icon={t.icon} />
            ))}
          </div>

          <div className="section-divider" />

          {/* system status */}
          <div style={{ padding: "14px 20px 24px" }}>
            <div style={{ fontSize: 8, color: "rgba(148,163,184,0.2)", letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Space Mono', monospace", marginBottom: 12 }}>System</div>
            {[["API", "#34d399"], ["Database", "#34d399"], ["Auth Layer", "#fbbf24"]].map(([name, col]) => (
              <div key={name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: "rgba(148,163,184,0.4)" }}>{name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: col, boxShadow: `0 0 8px ${col}`, animation: "pulse-glow 2s infinite" }} />
                  <span style={{ fontSize: 9, color: col + "aa", fontFamily: "'Space Mono', monospace" }}>live</span>
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* ── MAIN ── */}
        <main className="main-content">
          {/* topbar */}
          <div className="topbar">
            <div>
              <h1 style={{ fontFamily: "'Playfair Display', serif", fontSize: 28, fontWeight: 900, color: "#fff", letterSpacing: "-0.02em", lineHeight: 1, textShadow: "0 0 40px rgba(168,85,247,0.4)" }}>
                {TABS.find(t => t.id === tab)?.icon} {TABS.find(t => t.id === tab)?.label}
              </h1>
              <div style={{ fontSize: 11, color: "rgba(148,163,184,0.4)", marginTop: 5, fontFamily: "'Space Mono', monospace" }}>ArcaneOS · Admin Intelligence Layer</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {error && <span style={{ fontSize: 11, color: "#f87171", fontFamily: "'Space Mono', monospace" }}>⚠ {error}</span>}
              <button onClick={refetch} className="refetch-btn">↺ Refresh</button>
              <div style={{
                width: 36, height: 36, borderRadius: "50%",
                background: "linear-gradient(135deg, rgba(88,28,135,0.8), rgba(168,85,247,0.9))",
                border: "1px solid rgba(168,85,247,0.4)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 14, color: "#fff",
                boxShadow: "0 0 20px rgba(168,85,247,0.3)",
              }}>W</div>
            </div>
          </div>

          {/* ── OVERVIEW TAB ── */}
          {tab === "overview" && (
            <div>
              {loading ? <CrystalLoader /> : m && (
                <>
                  <div className="section-heading">Overview</div>

                  {/* metric cards grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
                    <CrystalCard label="Total Users" value={m.users.total} icon="⬡" color="#a855f7" sub={`${m.users.paid} paid`} trend={12} spark={m.signup_trend?.map(d => d.signups)} delay={0} />
                    <CrystalCard label="MRR" value={`$${m.revenue.mrr}`} icon="◎" color="#34d399" sub="monthly recurring" trend={8} delay={80} />
                    <CrystalCard label="ARR" value={`$${(m.revenue.arr).toLocaleString()}`} icon="↑" color="#818cf8" sub="annualized revenue" trend={15} delay={160} />
                    <CrystalCard label="Tasks Today" value={m.tasks.created_today} icon="✦" color="#fbbf24" sub={`${m.tasks.completion_rate}% complete`} trend={5} delay={240} />
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, marginBottom: 20 }}>
                    {/* signup trend */}
                    <GlassPanel>
                      <div className="panel-title">Signup Velocity</div>
                      <SignupTrend data={m.signup_trend} />
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 10, color: "rgba(148,163,184,0.3)", fontFamily: "'Space Mono', monospace" }}>
                        <span>{m.signup_trend[0]?.date}</span><span>Today</span>
                      </div>
                    </GlassPanel>

                    {/* subscription split */}
                    <GlassPanel>
                      <div className="panel-title">Subscription Split</div>
                      {[
                        { label: "Paid",      count: m.users.paid,      color: "#34d399", total: m.users.total },
                        { label: "Trialing",  count: m.users.trialing,  color: "#fbbf24", total: m.users.total },
                        { label: "Cancelled", count: m.users.cancelled, color: "#f87171", total: m.users.total },
                        { label: "Exempt",    count: m.users.exempt,    color: "#a855f7", total: m.users.total },
                      ].map(({ label, count, color, total }) => {
                        const pct = total ? Math.round((count / total) * 100) : 0;
                        return (
                          <div key={label} style={{ marginBottom: 16 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                <div style={{ width: 6, height: 6, borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}` }} />
                                <span style={{ fontSize: 12, color: "rgba(148,163,184,0.55)" }}>{label}</span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 10, color: "rgba(148,163,184,0.3)", fontFamily: "'Space Mono', monospace" }}>{pct}%</span>
                                <span style={{ fontSize: 14, color, fontWeight: 700, minWidth: 30, textAlign: "right", textShadow: `0 0 8px ${color}80` }}>{count}</span>
                              </div>
                            </div>
                            <div style={{ height: 4, background: "rgba(168,85,247,0.06)", borderRadius: 4, overflow: "hidden" }}>
                              <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${color}50, ${color})`, borderRadius: 4, transition: "width 0.8s cubic-bezier(0.4,0,0.2,1)", boxShadow: `0 0 10px ${color}50` }} />
                            </div>
                          </div>
                        );
                      })}

                      {/* users by role */}
                      <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid rgba(168,85,247,0.08)" }}>
                        <div className="panel-title" style={{ marginBottom: 12 }}>Users by Role</div>
                        {Object.entries(m.users.by_role).map(([role, count]) => (
                          <div key={role} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 12, color: "rgba(148,163,184,0.4)", textTransform: "capitalize" }}>{role}</span>
                            <span style={{ fontSize: 14, color: "rgba(168,85,247,0.7)", fontWeight: 700, fontFamily: "'Space Mono', monospace" }}>{count}</span>
                          </div>
                        ))}
                      </div>
                    </GlassPanel>
                  </div>

                  {/* stat row */}
                  <div className="stat-row">
                    {[
                      { label: "New This Week",   value: m.users.new_this_week,                color: "#a855f7" },
                      { label: "New This Month",  value: m.users.new_this_month,               color: "#a855f7" },
                      { label: "Tasks Today",     value: m.tasks.created_today,                color: "#34d399" },
                      { label: "Completion Rate", value: `${m.tasks.completion_rate}%`,        color: "#34d399" },
                      { label: "MRR",             value: `$${m.revenue.mrr}`,                  color: "#fbbf24" },
                      { label: "QRR",             value: `$${m.revenue.qrr}`,                  color: "#fbbf24" },
                      { label: "ARR",             value: `$${m.revenue.arr.toLocaleString()}`, color: "#fbbf24" },
                    ].map(({ label, value, color }, i) => (
                      <div key={label} className="stat-item" style={{ animationDelay: `${i * 50}ms` }}>
                        <div className="stat-label">{label}</div>
                        <div className="stat-val" style={{ color, textShadow: `0 0 16px ${color}80` }}>{value}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── REVENUE TAB ── */}
          {tab === "revenue" && (
            <div>
              {loading ? <CrystalLoader /> : m && (
                <>
                  <div className="section-heading">Revenue</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
                    <CrystalCard label="MRR" value={`$${m.revenue.mrr}`} icon="◎" color="#34d399" sub={`${m.users.paid} paid users`} delay={0} />
                    <CrystalCard label="ARR" value={`$${m.revenue.arr.toLocaleString()}`} icon="↑" color="#a855f7" sub="annualized" delay={80} />
                    <CrystalCard label="QRR" value={`$${m.revenue.qrr}`} icon="◈" color="#fbbf24" sub="this quarter" delay={160} />
                    <CrystalCard label="Plan Price" value={`$${m.revenue.plan_price}/mo`} icon="✦" color="#818cf8" sub="per user" delay={240} />
                  </div>

                  <GlassPanel style={{ marginBottom: 16 }}>
                    <div className="panel-title">Monthly Revenue — Last 12 Months</div>
                    <CrystalBarChart data={m.revenue.monthly_breakdown} />
                    <div style={{ marginTop: 28 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "6px 0 10px", borderBottom: "1px solid rgba(168,85,247,0.08)" }}>
                        {["Month", "New Paid", "Revenue"].map(h => (
                          <div key={h} style={{ fontSize: 9, color: "rgba(168,85,247,0.45)", textTransform: "uppercase", letterSpacing: "0.14em", fontFamily: "'Space Mono', monospace" }}>{h}</div>
                        ))}
                      </div>
                      {[...m.revenue.monthly_breakdown].reverse().slice(0, 8).map((d, i) => (
                        <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "12px 0", borderBottom: "1px solid rgba(168,85,247,0.05)", fontSize: 13 }}>
                          <span style={{ color: "rgba(148,163,184,0.45)" }}>{d.month}</span>
                          <span style={{ color: "rgba(148,163,184,0.35)", fontFamily: "'Space Mono', monospace" }}>{d.new_paid}</span>
                          <span style={{ color: d.revenue > 0 ? "#34d399" : "rgba(148,163,184,0.2)", fontWeight: 700, fontFamily: "'Space Mono', monospace", textShadow: d.revenue > 0 ? "0 0 8px rgba(52,211,153,0.4)" : "none" }}>${d.revenue.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: 18, padding: "12px 16px", background: "rgba(168,85,247,0.04)", borderRadius: 12, border: "1px solid rgba(168,85,247,0.1)", fontSize: 11, color: "rgba(148,163,184,0.35)", fontFamily: "'Space Mono', monospace", lineHeight: 1.8 }}>
                      ℹ Revenue at ${m.revenue.plan_price}/user/month. Set PLAN_PRICE_USD env var. Connect Lemon Squeezy webhook for real payment data.
                    </div>
                  </GlassPanel>
                </>
              )}
            </div>
          )}

          {/* ── USERS TAB ── */}
          {tab === "users" && (
            <div>
              <div className="section-heading">Users</div>
              <GlassPanel><UsersTable /></GlassPanel>
            </div>
          )}

          {/* ── WORKSPACES TAB ── */}
          {tab === "workspaces" && (
            <div>
              <div className="section-heading">Workspaces</div>
              <GlassPanel><WorkspacesTable /></GlassPanel>
            </div>
          )}

          {/* ── FEEDBACK TAB ── */}
          {tab === "feedback" && (
            <div>
              <div className="section-heading">Feedback</div>
              <FeedbackTable />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
