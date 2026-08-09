import { Logo } from "@/components/Logo";

export function LandingNav() {
  return (
    <nav className="landing-nav">
      <div className="landing-nav-inner">
        <div className="landing-nav-left">
          <a href="/" className="brand">
            <Logo size={28} />
            Threadly
          </a>
          <div className="landing-nav-links">
            <a href="/features">Features</a>
            <a href="/#pricing">Pricing</a>
            <a href="/faq">FAQ</a>
          </div>
        </div>
        <div className="hstack">
          <a href="/login" className="btn-ghost">
            Log in
          </a>
          <a href="/signup" className="btn btn-grad">
            Start free trial
          </a>
        </div>
      </div>
    </nav>
  );
}
