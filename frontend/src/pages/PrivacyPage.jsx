// src/pages/PrivacyPage.jsx
import { useEffect } from "react";

const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap');

  .legal-root {
    min-height: 100vh;
    background: #120705;
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
    background: radial-gradient(circle, rgba(255,106,82,0.08) 0%, transparent 70%);
    pointer-events: none;
  }

  .legal-root::after {
    content: '';
    position: fixed;
    bottom: -200px; right: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(200,31,48,0.07) 0%, transparent 70%);
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
    color: #9a908a;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    margin-bottom: 28px;
    padding: 0;
    transition: color 0.15s;
  }

  .legal-back:hover { color: #efe7df; }

  .legal-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 28px;
  }

  .legal-logo-icon {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #ff6a52 0%, #c81f30 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: #f5f0eb;
    box-shadow: 0 0 20px rgba(255,106,82,0.4);
    flex-shrink: 0;
  }

  .legal-logo-text {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 16px; font-weight: 800;
    color: #efe7df;
    letter-spacing: -0.02em;
  }

  .legal-logo-sub {
    font-size: 11px;
    color: #6b6058;
    margin-top: 1px;
  }

  .legal-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 28px; font-weight: 800;
    letter-spacing: -0.03em;
    background: linear-gradient(135deg, #efe7df 0%, #ffb199 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 6px;
  }

  .legal-updated {
    font-size: 12px;
    color: #6b6058;
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
    color: #efe7df;
    margin-bottom: 10px;
    letter-spacing: -0.01em;
  }

  .legal-p {
    font-size: 14px;
    color: #9a908a;
    line-height: 1.75;
    margin-bottom: 10px;
  }

  .legal-ul {
    list-style: none;
    padding: 0; margin: 0 0 10px 0;
  }

  .legal-ul li {
    font-size: 14px;
    color: #9a908a;
    line-height: 1.75;
    padding-left: 18px;
    position: relative;
    margin-bottom: 4px;
  }

  .legal-ul li::before {
    content: '–';
    position: absolute;
    left: 0;
    color: #ff6a52;
  }

  .legal-link {
    color: #ff6a52;
    text-decoration: none;
  }

  .legal-link:hover { text-decoration: underline; }

  .legal-footer {
    margin-top: 40px;
    padding-top: 24px;
    border-top: 1px solid rgba(255,255,255,0.07);
    font-size: 13px;
    color: #6b6058;
    text-align: center;
  }

  @media (max-width: 480px) {
    .legal-card { border-radius: 16px; }
    .legal-title { font-size: 22px; }
  }
`;

export default function PrivacyPage() {
  // Jump to a section when the URL has a #hash (e.g. /privacy#data-deletion)
  useEffect(() => {
    const id = window.location.hash.replace("#", "");
    if (!id) return;
    const el = document.getElementById(id);
    if (el && el.scrollIntoView) el.scrollIntoView();
  }, []);


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

          <div className="legal-title">Privacy Policy</div>
          <div className="legal-updated">Last updated: November 2, 2026</div>
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
              <li>Billing information: processed securely by Polar — we do not store your card details.</li>
              <li>Usage data: features used, session duration, and interaction logs to improve the Service.</li>
              <li>Technical data: IP address, browser type, and device information.</li>
              <li>Connected-account data: when you connect Slack, Gmail, Microsoft Teams or WhatsApp Business, the messages and emails you choose to connect, which we read only to find tasks (see section 5).</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">3. How We Use Your Information</div>
            <ul className="legal-ul">
              <li>To provide, operate, and maintain the Service.</li>
              <li>To identify tasks in the messages you connect and show them on your board.</li>
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
              <li>Polar — payment processing for subscriptions.</li>
              <li>Groq — AI processing: the text of messages that may contain tasks (from Slack, Gmail, Microsoft Teams or WhatsApp) is sent to Groq to identify tasks, assignees and deadlines.</li>
              <li>Meta Platforms (WhatsApp Business Platform) — delivers your WhatsApp Business messages to us when you connect a number, and handles the sign-in used to connect it.</li>
              <li>Slack — to receive and process messages you choose to connect, for AI task extraction.</li>
              <li>Vercel (application hosting) and Supabase (database hosting) — they run and serve the Service and store its data.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">5. WhatsApp Business and Other Connected Messages</div>
            <p className="legal-p">
              If you connect a WhatsApp Business number, Slack, Gmail or Microsoft Teams, we use those messages only to find tasks for you. For WhatsApp, we receive messages sent to or from your connected business number through Meta's WhatsApp Business Platform.
            </p>
            <ul className="legal-ul">
              <li>What we receive from WhatsApp: the text of messages, and the sender's name and number as provided by WhatsApp. We ignore images, audio, documents and other non-text messages.</li>
              <li>What we save: a message is saved only when it is turned into a task. The task keeps the message text, any assignee and deadline found in it, and the WhatsApp message ID (used to avoid duplicates). Messages that are not tasks are not saved by us: short acknowledgements and greetings are discarded immediately, and other text is sent to our AI provider (Groq) only to decide whether it is a task.</li>
              <li>Connection details we store: an access token issued by Meta for your WhatsApp Business Account, and your WhatsApp Business Account and phone-number IDs. We do not store your chat history or contact list.</li>
              <li>What we do not do: we do not send WhatsApp messages on your behalf, use your messages for advertising, sell them, or use them to train our own models.</li>
              <li>Your control: you can disconnect at any time from the dashboard. Disconnecting removes the saved token and IDs and stops new messages from creating tasks. Tasks already created stay until you delete them.</li>
            </ul>
            <p className="legal-p">
              WhatsApp is a service of Meta Platforms, Inc. and its terms apply to your use of WhatsApp. AI Workflow Coordinator is not affiliated with or endorsed by WhatsApp or Meta.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">6. Data Retention</div>
            <p className="legal-p">
              We retain your data for as long as your account is active or as needed to provide the Service. You may request deletion of your account and associated data at any time by contacting us.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">7. Cookies</div>
            <p className="legal-p">
              We use essential cookies to maintain your session and authentication state. No third-party advertising cookies are used.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">8. Security</div>
            <p className="legal-p">
              We implement industry-standard security measures including HTTPS encryption and secure password hashing. However, no method of transmission over the Internet is 100% secure.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">9. Your Rights</div>
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

          <div className="legal-section" id="data-deletion">
            <div className="legal-h2">10. Data Deletion</div>
            <p className="legal-p">You can delete your data at any time:</p>
            <ul className="legal-ul">
              <li>Disconnect a source: use Disconnect next to the Connect WhatsApp or Connect Gmail button in the dashboard. This removes the saved connection details.</li>
              <li>Delete tasks: delete any task in the dashboard to remove it, along with the message text saved with it.</li>
              <li>Delete your account and all associated data: email{" "}
                <a className="legal-link" href="mailto:wahajkashan456@gmail.com?subject=Delete%20my%20data">wahajkashan456@gmail.com</a>{" "}
                from your account email address with the subject "Delete my data". We will confirm by email and delete your data within 30 days, except records we are required by law to keep (for example, payment records held by our payment provider).</li>
              <li>Remove access from WhatsApp's side: you can also remove AI Workflow Coordinator from your WhatsApp Business Account in Meta Business Settings. This stops Meta from sending us your messages.</li>
            </ul>
          </div>

          <div className="legal-section">
            <div className="legal-h2">11. Changes to This Policy</div>
            <p className="legal-p">
              We may update this Privacy Policy from time to time. We will notify you of significant changes via email or a notice on the Service.
            </p>
          </div>

          <div className="legal-section">
            <div className="legal-h2">12. Contact</div>
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
