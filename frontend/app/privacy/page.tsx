import { Logo } from "@/components/Logo";

export const metadata = {
  title: "Privacy Policy — Threadly",
};

export default function PrivacyPage() {
  return (
    <>
      <header className="legal-header">
        <a href="/" className="legal-header-inner">
          <Logo size={22} />
          Threadly
        </a>
      </header>

      <article className="legal">
        <h1>Privacy Policy</h1>
        <p className="updated">Last updated: August 7, 2026</p>

        <p>
          This Privacy Policy explains what information Threadly (&quot;Threadly,&quot;
          &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;) collects when you use our website
          and application (the &quot;Service&quot;), how we use it, and the choices you have. By
          using the Service you agree to the collection and use of information as described
          here.
        </p>

        <h2>1. Information we collect</h2>

        <h3>1.1 Account information</h3>
        <p>
          When you register, we collect your name, email address, and a hashed (never
          plaintext) password. We automatically create a workspace tied to your account to
          organize your connected platforms and settings — you don&apos;t need to name or
          configure it yourself.
        </p>

        <h3>1.2 Connected platform data</h3>
        <p>
          When you connect an account (X/Twitter or Reddit) via OAuth, we receive and
          store an access token (and refresh token, where the platform provides one) that lets
          Threadly act on your behalf within the scopes you approved during that platform&apos;s
          own consent screen. These tokens are encrypted at rest. We never see or store your
          password for any connected platform — authentication happens entirely on that
          platform&apos;s own site.
        </p>
        <p>
          Using that connection, Threadly reads public posts and conversations on the connected
          platform matching the keywords and criteria you configure, in order to identify
          conversations that may be relevant to you and draft a suggested reply.
        </p>

        <h3>1.3 Content you create in Threadly</h3>
        <p>
          We store the conversations Threadly finds, the replies it drafts, and your decisions
          (approve, reject, or edit) on each draft. Nothing is ever published to a connected
          platform without your explicit approval — see Section 3.
        </p>

        <h3>1.4 Payment information</h3>
        <p>
          Subscription payments are processed by Polar (acting as merchant of record), our
          payment processor. Threadly never receives or stores your full card number — Polar
          handles card collection, billing, and applicable tax compliance directly. We store only
          your subscription status (trial, active, past due, canceled) and billing period dates.
        </p>

        <h3>1.5 Usage and log data</h3>
        <p>
          We keep an audit log of security-relevant account actions (logins, connections made or
          removed, subscription changes, configuration changes) including timestamps and IP
          address, for security and support purposes.
        </p>

        <h3>1.6 Cookies</h3>
        <p>
          We use a session cookie to keep you signed in and a second cookie to protect
          state-changing requests from cross-site forgery. Both are essential to the Service
          functioning and are not used for advertising or cross-site tracking.
        </p>

        <h2>2. How we use your information</h2>
        <ul>
          <li>To provide, maintain, and secure the Service, including keeping you signed in and processing your subscription.</li>
          <li>To operate the AI agents that find relevant conversations and draft replies on your behalf.</li>
          <li>To communicate with you about your account, billing, or changes to the Service.</li>
          <li>To detect, investigate, and prevent fraud, abuse, or security incidents.</li>
          <li>To comply with legal obligations.</li>
        </ul>

        <h2>3. Human approval — how content drafting and AI processing works</h2>
        <p>
          Threadly is built around one permanent rule: <strong>nothing is ever posted, messaged,
          or published to any connected platform without your explicit, per-item approval.</strong>{" "}
          This is not a limitation of an early version — it is a permanent design principle of
          the Service.
        </p>
        <p>
          To draft a reply, the text of the conversation Threadly found is sent to Anthropic&apos;s
          Claude API for processing. Anthropic processes this content to generate the draft and
          does not use it to train models available to other customers, consistent with
          Anthropic&apos;s own commercial API terms. See{" "}
          <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noreferrer">
            Anthropic&apos;s Privacy Policy
          </a>{" "}
          for how Anthropic itself handles data sent to its API.
        </p>

        <h2>4. Third-party service providers</h2>
        <p>We share information with the following categories of service providers, only as needed for them to perform their function:</p>
        <ul>
          <li><strong>Polar</strong> — subscription billing and payment processing (merchant of record).</li>
          <li><strong>Anthropic</strong> — AI processing to draft replies (Claude API).</li>
          <li><strong>X (Twitter) and Reddit</strong> — the platforms you explicitly connect via OAuth; we exchange data with them only within the scopes you grant.</li>
          <li><strong>Railway</strong> and <strong>Vercel</strong> — infrastructure providers hosting our backend, database, and website.</li>
        </ul>
        <p>We do not sell your personal information to anyone, ever.</p>

        <h2>5. Data retention</h2>
        <p>
          We retain account and connection data for as long as your account is active. If you
          disconnect a platform, its access token is deleted immediately. If you delete your
          account, we delete your personal data within 30 days, except where retention is
          required for legal, tax, or fraud-prevention purposes.
        </p>

        <h2>6. Data security</h2>
        <p>
          Passwords are hashed, never stored in plaintext. OAuth tokens for connected platforms
          are encrypted at rest. All traffic between your browser and Threadly is encrypted in
          transit (HTTPS). No method of transmission or storage is 100% secure, and we cannot
          guarantee absolute security.
        </p>

        <h2>7. Your rights</h2>
        <p>Depending on where you live, you may have the right to:</p>
        <ul>
          <li>Access the personal data we hold about you.</li>
          <li>Correct inaccurate data.</li>
          <li>Request deletion of your account and associated data.</li>
          <li>Disconnect any connected platform at any time from your dashboard, immediately revoking Threadly&apos;s access.</li>
          <li>Export your data.</li>
        </ul>
        <p>To exercise any of these rights, contact us using the details in Section 11.</p>

        <h2>8. Children&apos;s privacy</h2>
        <p>
          The Service is not directed to, and we do not knowingly collect personal information
          from, anyone under 18 years old.
        </p>

        <h2>9. International data transfers</h2>
        <p>
          Threadly is operated from India, and our infrastructure providers may process and store
          data in other countries. By using the Service, you consent to your information being
          transferred to and processed in countries other than your own.
        </p>

        <h2>10. Changes to this policy</h2>
        <p>
          We may update this Privacy Policy from time to time. If we make material changes,
          we&apos;ll notify you by email or through the Service before the change takes effect.
        </p>

        <h2>11. Contact us</h2>
        <p>
          Questions about this Privacy Policy or your data can be sent to{" "}
          <a href="mailto:thumbflip.contact@gmail.com">thumbflip.contact@gmail.com</a>.
        </p>
      </article>
    </>
  );
}
