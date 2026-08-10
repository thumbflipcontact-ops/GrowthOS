"use client";

import { useEffect, useState } from "react";
import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";
import { api } from "@/lib/api-client";
import type { PricingTier } from "@/lib/types";

// Shown while the live tier counts are loading/unavailable, and used as the pricing card's
// price until they arrive — deliberately the standard (highest) price, never a lower one, so
// a slow or failed fetch can't advertise a rate a signup won't actually get.
const FALLBACK_PRICE_USD = 29;

function tierNote(tier: PricingTier): string {
  if (tier.capacity === null) return "Standard price";
  if (tier.is_sold_out) return "Sold out";
  if (tier.is_current) return tier.spots_left === 1 ? "1 spot left" : `${tier.spots_left} spots left`;
  return `Next ${tier.capacity} users`;
}

function tierBarFillPercent(tiers: PricingTier[]): number {
  const n = tiers.length;
  if (n < 2) return 0;
  const segment = 100 / (n - 1);
  let filled = 0;
  for (let i = 0; i < n - 1; i++) {
    const tier = tiers[i];
    if (tier.is_sold_out) {
      filled += segment;
      continue;
    }
    if (tier.is_current && tier.capacity) {
      filled += segment * (tier.spots_taken / tier.capacity);
    }
    return filled;
  }
  return filled;
}

function TierBar({ tiers }: { tiers: PricingTier[] }) {
  const n = tiers.length;
  return (
    <div className="tier-bar-wrap">
      <div className="tier-bar">
        <div className="tier-bar-track">
          <div className="tier-bar-fill" style={{ width: `${tierBarFillPercent(tiers)}%` }} />
        </div>
        <div className="tier-bar-stops">
          {tiers.map((tier, i) => (
            <div
              key={tier.key}
              className={`tier-stop${tier.is_current ? " current" : ""}${tier.is_sold_out ? " sold-out" : ""}`}
              style={{ left: `${n > 1 ? (i / (n - 1)) * 100 : 50}%` }}
            >
              <span className="tier-dot" />
              <div className="tier-price">${tier.price_usd}</div>
              <div className="tier-note">{tierNote(tier)}</div>
            </div>
          ))}
        </div>
      </div>
      <p className="tier-bar-caption">
        Price is set automatically by signup order — no codes to enter, and once you&apos;re in,
        that price is locked in for as long as you stay subscribed.
      </p>
    </div>
  );
}

const STEPS = [
  {
    title: "Tell it what you're building",
    body: "Give Threadly your keywords and ICP once — the pain points, questions, and phrases your future users are already posting.",
  },
  {
    title: "It watches, so you don't have to",
    body: "Conversation Finder scans X on a schedule and drafts a reply with Claude the moment something's worth joining. No more refreshing search tabs all day.",
  },
  {
    title: "You approve — or you don't",
    body: "Every draft sits in your Approval Inbox until you personally read and approve it. Threadly will never publish on its own, ever.",
  },
];

const PLATFORMS = [{ name: "X (Twitter)", soon: false }];

export default function RootPage() {
  const [tiers, setTiers] = useState<PricingTier[] | null>(null);

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

  useEffect(() => {
    api
      .pricingTiers()
      .then((res) => setTiers(res.tiers))
      .catch(() => {
        // Public, best-effort — the pricing card falls back to FALLBACK_PRICE_USD and the
        // checkout flow itself (which independently re-derives the real tier server-side) is
        // unaffected either way.
      });
  }, []);

  const currentPrice = tiers?.find((t) => t.is_current)?.price_usd ?? FALLBACK_PRICE_USD;

  return (
    <>
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Built for founders finding their first users
        </span>
        <h1>
          Stop searching for the right conversation.{" "}
          <span className="grad">Let AI find it for you on&nbsp;X.</span>
        </h1>
        <p className="lead">
          Building a product means your next user is out there right now, posting about the
          exact problem you solve — on X. Threadly finds that conversation
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
        <p className="hero-note">No card required · cancel anytime, nothing charged until you subscribe</p>
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
          <iframe
            src="https://www.loom.com/embed/cf01ff136ed4416e84bfa106391029ec?hideEmbedTopBar=true"
            title="Threadly product demo"
            className="demo-embed"
            allow="fullscreen"
            allowFullScreen
          />
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

      <section id="pricing" className="landing-section">
        {tiers && <TierBar tiers={tiers} />}
        <div className="pricing-wrap">
          <div className="pricing-card">
            <div className="muted">Threadly Subscription</div>
            <div className="price">
              ${currentPrice}
              <span>/month</span>
            </div>
            <div className="muted">7-day free trial, no card required — then ${currentPrice}/month, locked in for good</div>
            <ul>
              <li>Unlimited approved connections on X</li>
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

      <LandingFooter />
    </>
  );
}
