import { LinkedInIcon, XIcon } from "@/components/SocialIcons";

export function LandingFooter() {
  return (
    <footer className="landing-footer">
      <div>Threadly — AI finds the conversation. You approve the reply.</div>
      <div className="footer-social">
        <a
          href="https://x.com/AmolParikh10"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Follow on X"
          className="social-icon"
        >
          <XIcon />
        </a>
        <a
          href="https://www.linkedin.com/in/amol-parikh-4442b0b/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Connect on LinkedIn"
          className="social-icon"
        >
          <LinkedInIcon />
        </a>
      </div>
      <div className="footer-links">
        <a href="/features">Features</a>
        <a href="/use-cases">Use Cases</a>
        <a href="/#pricing">Pricing</a>
        <a href="/faq">FAQ</a>
        <a href="/privacy">Privacy Policy</a>
        <a href="/terms">Terms &amp; Conditions</a>
      </div>
      <div className="footer-copyright">© 2026 Threadly. All rights reserved.</div>
    </footer>
  );
}
