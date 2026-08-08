"use client";

import { useEffect } from "react";
import { Logo } from "@/components/Logo";
import { api } from "@/lib/api-client";

const STEPS = [
  {
    title: "Tell it what you're building",
    body: "Give Threadly your keywords and ICP once — the pain points, questions, and phrases your future users are already posting.",
  },
  {
    title: "It watches, so you don't have to",
    body: "Conversation Finder scans X and Reddit on a schedule and drafts a reply with Claude the moment something's worth joining. No more refreshing search tabs all day.",
  },
  {
    title: "You approve — or you don't",
    body: "Every draft sits in your Approval Inbox until you personally read and approve it. Threadly will never publish on its own, ever.",
  },
];

const PLATFORMS = [
  { name: "X (Twitter)", soon: false },
  { name: "Reddit", soon: false },
];

export default function RootPage() {
  useEffect(() => {
    api
      .me()
      .then(() => {
        window.location.href = "/dashboard";
      })
      .catch(() => {
        // Not signed in — stay on the landing page, no redirect.
      });
  }, []);

  return (
    <>
      <nav className="landing-nav">
        <div className="landing-nav-inner">
          <a href="/" className="brand">
            <Logo size={28} />
            Threadly
          </a>
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

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Built for founders finding their first users
        </span>
        <h1>
          Stop searching for the right conversation. <span className="grad">Let AI find it for you.</span>
        </h1>
        <p className="lead">
          Building a product means your next user is out there right now, posting about the
          exact problem you solve — on X or Reddit. Threadly finds that conversation
          for you and drafts a reply, so you spend your time building, not scrolling search
          results. Nothing goes out without your yes.
        </p>
        <div className="hero-ctas">
          <a href="/signup" className="btn btn-grad">
            Start your 7-day free trial
          </a>
          <a href="/login" className="btn-ghost">
            Log in
          </a>
        </div>
        <p className="hero-note">Card required to start · cancel anytime before day 7, pay nothing</p>
      </header>

      <section className="landing-section">
        <div className="section-heading">
          <h2>How it works</h2>
          <p>Three steps, and a human in the loop at the end of every one.</p>
        </div>
        <div className="steps-grid">
          {STEPS.map((step, i) => (
            <div className="step-card" key={step.title}>
              <span className="step-number">{i + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-section">
        <div className="section-heading">
          <h2>See it in action</h2>
          <p>A real walkthrough of the actual product — not a mockup.</p>
        </div>
        <div className="demo-frame">
          <div className="demo-placeholder">Demo video coming shortly</div>
        </div>
      </section>

      <section className="landing-section">
        <div className="section-heading">
          <h2>Where Threadly works</h2>
        </div>
        <div className="platform-row">
          {PLATFORMS.map((p) => (
            <div key={p.name} className={`platform-pill${p.soon ? " soon" : " live"}`}>
              {!p.soon && <span className="dot" />}
              {p.name}
              {p.soon && " — soon"}
            </div>
          ))}
        </div>
      </section>

      <section className="landing-section">
        <div className="section-heading">
          <h2>Simple pricing</h2>
          <p>One plan. No tiers to compare, no surprise limits to hit.</p>
        </div>
        <div className="pricing-wrap">
          <div className="pricing-card">
            <div className="muted">Threadly Subscription</div>
            <div className="price">
              $49<span>/month</span>
            </div>
            <div className="muted">7-day free trial, then $49/month</div>
            <ul>
              <li>Unlimited approved connections across X and Reddit</li>
              <li>AI-drafted replies via Claude, on your schedule</li>
              <li>Full manual approval on every single post</li>
              <li>Cancel anytime from your dashboard</li>
            </ul>
            <a href="/signup" className="btn btn-grad btn-block">
              Start your 7-day free trial
            </a>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div>Threadly — AI finds the conversation. You approve the reply.</div>
        <div className="footer-links">
          <a href="/privacy">Privacy Policy</a>
          <a href="/terms">Terms &amp; Conditions</a>
        </div>
      </footer>
    </>
  );
}
