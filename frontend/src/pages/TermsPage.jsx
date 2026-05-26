// src/pages/TermsPage.jsx

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

export default function TermsPage() {

  return (
    <>
      <style>{STYLES}</style>
      <div className="legal-root">
        <div className="legal-card">

          <button className="legal-back" onClick={() => window.history.back()}>
            ← Back
          </button>

          <div className="legal-logo">
            <div className="legal-logo-icon">AI</div>
            <div>
              <div className="legal-logo-text">AI Workflow</div>
              <div className="legal-logo-sub">Coordinator</div>
            </div>
          </div>

          <div className="legal-title">Terms of Service</div>
          <div className="legal-updated">Last updated: May 25, 2026</div>
          <div className="legal-divider" />

          <div className="legal-section">
            <div className="legal-h2">1. Acceptance of Terms</div>
            <p className="legal-p">
              By accessing or using AI Workflow Coordinator ("the Service") at acedengroup.com, you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">2. Description of Service</div>
            <p className="legal-p">
              AI Workflow Coordinator is a SaaS platform that helps individuals and teams automate and coordinate workflows using artificial intelligence. The Service is provided on a monthly subscription basis.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">3. Free Trial</div>
            <p className="legal-p">
              New users are eligible for a 7-day free trial. No charge is made during the trial period. On the 8th day, your selected subscription plan will be billed automatically. You may cancel at any time before the trial ends to avoid being charged.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">4. Billing & Payments</div>
            <p className="legal-p">
              Subscriptions are billed monthly. Payments are processed securely through Dodo Payments. By subscribing, you authorize us to charge your payment method on a recurring basis until you cancel.
            </p>
            <ul className="legal-ul">
              <li>All prices are listed in USD.</li>
              <li>Billing occurs on the same date each month following your first charge.</li>
              <li>You will receive an email receipt for every payment.</li>
              <li>Failed payments may result in temporary suspension of your account.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">5. Cancellation</div>
            <p className="legal-p">
              You may cancel your subscription at any time from your account settings. Cancellation takes effect at the end of your current billing period. You will retain access to the Service until that date.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">6. Acceptable Use</div>
            <p className="legal-p">You agree not to:</p>
            <ul className="legal-ul">
              <li>Use the Service for any unlawful purpose.</li>
              <li>Attempt to reverse-engineer, copy, or resell any part of the Service.</li>
              <li>Introduce malware, spam, or disruptive code.</li>
              <li>Violate the rights of other users or third parties.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">7. Intellectual Property</div>
            <p className="legal-p">
              All content, branding, and code within the Service are the property of Aceden Group. You are granted a limited, non-exclusive licence to use the Service for its intended purpose only.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">8. Disclaimer of Warranties</div>
            <p className="legal-p">
              The Service is provided "as is" without warranties of any kind. We do not guarantee uninterrupted or error-free operation. Use the Service at your own risk.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">9. Limitation of Liability</div>
            <p className="legal-p">
              To the maximum extent permitted by law, Aceden Group shall not be liable for any indirect, incidental, or consequential damages arising from your use of the Service.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">10. Governing Law</div>
            <p className="legal-p">
              These Terms are governed by the laws of Pakistan. Any disputes shall be subject to the exclusive jurisdiction of the courts of Pakistan.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">11. Changes to Terms</div>
            <p className="legal-p">
              We may update these Terms at any time. Continued use of the Service after changes constitutes acceptance of the new Terms. We will notify users of significant changes via email.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">12. Contact</div>
            <p className="legal-p">
              For questions about these Terms, contact us at{" "}
              <a className="legal-link" href="mailto:wahajkashan456@gmail.com">wahajkashan456@gmail.com</a>.
            </p>
          </div>

          <div className="legal-footer">
            © 2026 Aceden Group · acedengroup.com ·{" "}
            <a className="legal-link" href="/privacy">Privacy Policy</a> ·{" "}
            <a className="legal-link" href="/refund">Refund Policy</a>
          </div>

        </div>
      </div>
    </>
  );
}
