// src/pages/RefundPage.jsx
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

  .legal-highlight {
    background: rgba(79,142,247,0.08);
    border: 1px solid rgba(79,142,247,0.2);
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 20px;
  }

  .legal-highlight .legal-p {
    margin-bottom: 0;
    color: #a5b4fc;
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

export default function RefundPage() {
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

          <div className="legal-title">Refund Policy</div>
          <div className="legal-updated">Last updated: May 25, 2026</div>
          <div className="legal-divider" />

          <div className="legal-section">
            <div className="legal-highlight">
              <p className="legal-p">
                We offer a <strong style={{color:"#e8eaf6"}}>48-hour refund window</strong> from your first charge. If you are not satisfied after your free trial ends and are billed, contact us within 48 hours for a full refund — no questions asked.
              </p>
            </div>
          </div>

          <div className="legal-section">
            <div className="legal-h2">1. Free Trial</div>
            <p className="legal-p">
              AI Workflow Coordinator offers a 7-day free trial. You will not be charged during this period. Your first payment is processed on the 8th day. You may cancel at any time before the trial ends with no charge.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">2. Eligibility for Refund</div>
            <p className="legal-p">You are eligible for a full refund if:</p>
            <ul className="legal-ul">
              <li>You request it within 48 hours of your first charge (after the 7-day trial ends).</li>
              <li>You have not excessively used the Service during the paid period.</li>
            </ul>
            <p className="legal-p">
              Refunds are not available for renewal charges after the first billing cycle, except in cases of technical error or duplicate charge.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">3. How to Request a Refund</div>
            <p className="legal-p">
              To request a refund, email us at{" "}
              <a className="legal-link" href="mailto:wahajkashan456@gmail.com">wahajkashan456@gmail.com</a>{" "}
              with the subject line "Refund Request" and include your registered email address and the reason for your request.
            </p>
            <p className="legal-p">
              We aim to process all refund requests within 3–5 business days. Refunds are issued to the original payment method.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">4. Non-Refundable Situations</div>
            <ul className="legal-ul">
              <li>Requests made more than 48 hours after the first charge.</li>
              <li>Subsequent monthly renewal charges.</li>
              <li>Accounts suspended for violating our Terms of Service.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">5. Cancellation vs. Refund</div>
            <p className="legal-p">
              Cancelling your subscription stops future charges but does not automatically trigger a refund. If you wish to cancel and receive a refund within the eligible window, please contact us directly rather than only cancelling via your account settings.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">6. Contact</div>
            <p className="legal-p">
              For refund requests or billing questions, contact us at{" "}
              <a className="legal-link" href="mailto:wahajkashan456@gmail.com">wahajkashan456@gmail.com</a>.
            </p>
          </div>

          <div className="legal-footer">
            © 2026 Aceden Group · acedengroup.com ·{" "}
            <a className="legal-link" href="/terms">Terms of Service</a> ·{" "}
            <a className="legal-link" href="/privacy">Privacy Policy</a>
          </div>

        </div>
      </div>
    </>
  );
}
