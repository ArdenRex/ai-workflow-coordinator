// src/pages/PrivacyPage.jsx
import { useNavigate } from "react-router-dom";

const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap');

  .legal-root {
    min-height: 100vh;
    background: #0d0f1e;
    font-family: 'Inter', system-ui, sans-serif;
    padding: clamp(24px, 4vw, 60px) clamp(16px, 4vw, 24px);
    position: relative;
    overflow: hidden;
  }

  .legal-root::before {
    content: '';
    position: fixed;
    top: -200px; left: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(79,142,247,0.08) 0%, transparent 70%);
    pointer-events: none;
  }

  .legal-root::after {
    content: '';
    position: fixed;
    bottom: -200px; right: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(123,92,240,0.07) 0%, transparent 70%);
    pointer-events: none;
  }

  .legal-card {
    max-width: 760px;
    margin: 0 auto;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 24px;
    padding: clamp(24px, 5vw, 48px);
    backdrop-filter: blur(20px);
    box-shadow: 0 24px 64px rgba(0,0,0,0.4);
    position: relative;
    z-index: 1;
    animation: cardIn 0.5s cubic-bezier(0.16,1,0.3,1) both;
  }

  @keyframes cardIn {
    from { opacity: 0; transform: translateY(24px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  .legal-back {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: none;
    border: none;
    color: #8b90b8;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    margin-bottom: 28px;
    padding: 0;
    transition: color 0.15s;
  }

  .legal-back:hover { color: #e8eaf6; }

  .legal-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 28px;
  }

  .legal-logo-icon {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: #fff;
    box-shadow: 0 0 20px rgba(79,142,247,0.4);
    flex-shrink: 0;
  }

  .legal-logo-text {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 16px; font-weight: 800;
    color: #e8eaf6;
    letter-spacing: -0.02em;
  }

  .legal-logo-sub {
    font-size: 11px;
    color: #555a80;
    margin-top: 1px;
  }

  .legal-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 28px; font-weight: 800;
    letter-spacing: -0.03em;
    background: linear-gradient(135deg, #f0f2ff 0%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 6px;
  }

  .legal-updated {
    font-size: 12px;
    color: #555a80;
    margin-bottom: 32px;
  }

  .legal-divider {
    height: 1px;
    background: rgba(255,255,255,0.07);
    margin-bottom: 32px;
  }

  .legal-section {
    margin-bottom: 28px;
  }

  .legal-h2 {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 15px; font-weight: 700;
    color: #e8eaf6;
    margin-bottom: 10px;
    letter-spacing: -0.01em;
  }

  .legal-p {
    font-size: 14px;
    color: #8b90b8;
    line-height: 1.75;
    margin-bottom: 10px;
  }

  .legal-ul {
    list-style: none;
    padding: 0; margin: 0 0 10px 0;
  }

  .legal-ul li {
    font-size: 14px;
    color: #8b90b8;
    line-height: 1.75;
    padding-left: 18px;
    position: relative;
    margin-bottom: 4px;
  }

  .legal-ul li::before {
    content: '–';
    position: absolute;
    left: 0;
    color: #4f8ef7;
  }

  .legal-link {
    color: #4f8ef7;
    text-decoration: none;
  }

  .legal-link:hover { text-decoration: underline; }

  .legal-footer {
    margin-top: 40px;
    padding-top: 24px;
    border-top: 1px solid rgba(255,255,255,0.07);
    font-size: 13px;
    color: #555a80;
    text-align: center;
  }

  @media (max-width: 480px) {
    .legal-card { border-radius: 16px; }
    .legal-title { font-size: 22px; }
  }
`;

export default function PrivacyPage() {
  const navigate = useNavigate();

  return (
    <>
      <style>{STYLES}</style>
      <div className="legal-root">
        <div className="legal-card">

          <button className="legal-back" onClick={() => navigate(-1)}>
            ← Back
          </button>

          <div className="legal-logo">
            <div className="legal-logo-icon">AI</div>
            <div>
              <div className="legal-logo-text">AI Workflow</div>
              <div className="legal-logo-sub">Coordinator</div>
            </div>
          </div>

          <div className="legal-title">Privacy Policy</div>
          <div className="legal-updated">Last updated: May 25, 2026</div>
          <div className="legal-divider" />

          <div className="legal-section">
            <div className="legal-h2">1. Introduction</div>
            <p className="legal-p">
              Aceden Group ("we", "us", "our") operates AI Workflow Coordinator at acedengroup.com. This Privacy Policy explains how we collect, use, and protect your personal information when you use our Service.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">2. Information We Collect</div>
            <p className="legal-p">We collect the following types of information:</p>
            <ul className="legal-ul">
              <li>Account information: name, email address, and password when you register.</li>
              <li>Billing information: processed securely by Lemon Squeezy — we do not store your card details.</li>
              <li>Usage data: features used, session duration, and interaction logs to improve the Service.</li>
              <li>Technical data: IP address, browser type, and device information.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">3. How We Use Your Information</div>
            <ul className="legal-ul">
              <li>To provide, operate, and maintain the Service.</li>
              <li>To process payments and manage your subscription.</li>
              <li>To send transactional emails (receipts, account alerts).</li>
              <li>To improve and personalise your experience.</li>
              <li>To respond to support requests.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">4. Sharing of Information</div>
            <p className="legal-p">
              We do not sell your personal data. We share data only with trusted third-party service providers necessary to operate the Service, including:
            </p>
            <ul className="legal-ul">
              <li>Lemon Squeezy — payment processing.</li>
              <li>Hosting and infrastructure providers.</li>
              <li>Analytics tools (anonymised data only).</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">5. Data Retention</div>
            <p className="legal-p">
              We retain your data for as long as your account is active or as needed to provide the Service. You may request deletion of your account and associated data at any time by contacting us.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">6. Cookies</div>
            <p className="legal-p">
              We use essential cookies to maintain your session and authentication state. No third-party advertising cookies are used.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">7. Security</div>
            <p className="legal-p">
              We implement industry-standard security measures including HTTPS encryption and secure password hashing. However, no method of transmission over the Internet is 100% secure.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">8. Your Rights</div>
            <p className="legal-p">You have the right to:</p>
            <ul className="legal-ul">
              <li>Access the personal data we hold about you.</li>
              <li>Request correction of inaccurate data.</li>
              <li>Request deletion of your data.</li>
              <li>Withdraw consent at any time.</li>
            </ul>
            <p className="legal-p">
              To exercise these rights, email us at{" "}
              <a className="legal-link" href="mailto:wahajkashan456@gmail.com">wahajkashan456@gmail.com</a>.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">9. Changes to This Policy</div>
            <p className="legal-p">
              We may update this Privacy Policy from time to time. We will notify you of significant changes via email or a notice on the Service.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">10. Contact</div>
            <p className="legal-p">
              For privacy-related questions, contact us at{" "}
              <a className="legal-link" href="mailto:wahajkashan456@gmail.com">wahajkashan456@gmail.com</a>.
            </p>
          </div>

          <div className="legal-footer">
            © 2026 Aceden Group · acedengroup.com ·{" "}
            <a className="legal-link" href="/terms">Terms of Service</a> ·{" "}
            <a className="legal-link" href="/refund">Refund Policy</a>
          </div>

        </div>
      </div>
    </>
  );
}
