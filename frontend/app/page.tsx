"use client";

import { useEffect, useId, useState } from "react";
import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";
import { api } from "@/lib/api-client";
import type { PricingTier } from "@/lib/types";

// Shown while the live tier counts are loading/unavailable, and used as the pricing card's
// price until they arrive — deliberately the standard (highest) price, never a lower one, so
// a slow or failed fetch can't advertise a rate a signup won't actually get.
const FALLBACK_PRICE_USD = 29;

// Gives Google and AI answer engines (ChatGPT/Perplexity-style crawlers) a clean, structured
// "what is this" to cite directly, rather than having to infer it from prose — same reasoning
// as the FAQ page's FAQPage schema. This page is a client component ("use client" above), so
// this can't go through the metadata API (server-components-only) — a plain <script> tag in
// the JSX below works the same way the blog posts' JSON-LD does.
const ORGANIZATION_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Threadly",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  url: "https://www.usethreadly.co",
  description:
    "Threadly finds relevant conversations on Reddit matching your keywords, has Claude judge which ones are genuine leads, drafts a reply, and requires your approval before anything posts.",
  offers: {
    "@type": "Offer",
    price: "9",
    priceCurrency: "USD",
    description: "Tiered launch pricing starting from $9/month, a 7-day free trial with no card required.",
  },
  author: { "@type": "Organization", name: "Threadly", url: "https://www.usethreadly.co" },
};

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
    body: "Give Threadly your website, and it works out specific keywords people actually say, not broad topics like \"SEO.\" That's what tells it which Reddit posts are worth a reply.",
  },
  {
    title: "It watches, so you don't have to",
    body: "Conversation Finder scans Reddit once a day — no login required — then Claude reads each match to judge whether it's a genuine lead and how strong their buying intent is, not just whether it shares a keyword. Worth-joining posts get a drafted reply. No more refreshing search tabs all day.",
  },
  {
    title: "You approve — or you don't",
    body: "Every draft sits in your Approval Inbox with a lead-match score, a buying-intent flag, and Claude's own rating of the reply it wrote — so you know exactly what you're looking at before you approve anything. Threadly will never publish on its own, ever.",
  },
];

const PLATFORMS = [{ name: "Reddit", soon: false }];

// Official embed badge from tinystartups.com — each future launch site provides its own
// distinct badge markup like this one, so entries here are whole components, not a shared
// name/href template.
function TinyStartupsBadge() {
  const gradientId = useId();

  return (
    <a
      href="https://www.tinystartups.com/startup/threadly"
      target="_blank"
      rel="noopener"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "14px",
        padding: "14px 22px 14px 18px",
        borderRadius: "14px",
        textDecoration: "none",
        fontFamily: "'Inter', system-ui, sans-serif",
        background:
          "linear-gradient(#fff,#fff) padding-box, linear-gradient(90deg,#3525E6,#D81FE0,#22B8F0) border-box",
        border: "2px solid transparent",
        color: "#0E0B1F",
      }}
    >
      <svg width="56" height="56" viewBox="0 0 100 100">
        <defs>
          <linearGradient id={gradientId} x1=".1" y1="0" x2=".9" y2="1">
            <stop offset="0%" stopColor="#3525E6" />
            <stop offset="55%" stopColor="#D81FE0" />
            <stop offset="100%" stopColor="#22B8F0" />
          </linearGradient>
        </defs>
        <path
          d="M50 6C52 32 68 48 94 50C68 52 52 68 50 94C48 68 32 52 6 50C32 48 48 32 50 6Z"
          fill={`url(#${gradientId})`}
        />
      </svg>
      <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
        <span style={{ fontSize: "22px", fontWeight: 800, letterSpacing: "-0.025em" }}>
          Tiny Startups
        </span>
        <span style={{ fontSize: "11px", color: "#6A6585", marginTop: "4px" }}>
          tinystartups.com
        </span>
      </span>
    </a>
  );
}

// Official embed badge from vibecodinglist.com — plain <img>, not next/image, since that
// component requires the source hostname to be allow-listed in next.config.js and this
// matches the exact embed markup vibecodinglist.com itself provides. The UTM params in the
// href are theirs, for their own attribution — left exactly as given, not simplified away.
function VibeCodingListBadge() {
  return (
    <a
      href="https://vibecodinglist.com/projects/threadly?utm_source=vcl_badge&utm_medium=builder_site&utm_campaign=listed_badge&utm_content=threadly"
      target="_blank"
      rel="noopener"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="https://vibecodinglist.com/assets/embed-widget/featured-on-badge-dark.png"
        alt="Featured on VibeCodingList"
        width={200}
        height={51}
      />
    </a>
  );
}

// Only real, confirmed placements go here — this renders as an "as featured on" trust signal,
// so it must never claim coverage that doesn't exist yet.
const FEATURED_ON = [
  { key: "tinystartups", badge: <TinyStartupsBadge /> },
  { key: "vibecodinglist", badge: <VibeCodingListBadge /> },
];

// Below this many real logos, scrolling would just show the same logo(s) repeating right next
// to themselves — better to show them once, static, and switch on the moving belt once there
// are enough distinct entries for it to actually read as a belt.
const MIN_LOGOS_TO_SCROLL = 4;

function FeaturedOnBelt() {
  const scrolling = FEATURED_ON.length >= MIN_LOGOS_TO_SCROLL;
  // Rendered twice back-to-back only when scrolling — same seamless-loop technique as
  // PainPointTicker (render twice, animate 0% -> -50%), just horizontal instead of vertical.
  const items = scrolling ? [...FEATURED_ON, ...FEATURED_ON] : FEATURED_ON;

  return (
    <section className="landing-section featured-on">
      <div className="section-heading">
        <h2>Featured on</h2>
      </div>
      <div className="featured-on-window">
        <div className={`featured-on-track${scrolling ? "" : " static"}`}>
          {items.map((item, i) => (
            <div className="featured-on-slot" key={`${item.key}-${i}`}>
              {item.badge}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

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
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(ORGANIZATION_JSON_LD) }}
      />
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Find leads on Reddit
        </span>
        <h1>
          Your next customer is already on Reddit.{" "}
          <span className="grad">AI finds them before you scroll past.</span>
        </h1>
        <p className="lead">
          Building a product means your next user is out there right now, posting about the
          exact problem you solve — on Reddit. Threadly finds that conversation for you and
          drafts a reply, so you spend your time building, not scrolling search results.
          Nothing goes out without your yes — and finding leads never asks you to log in.
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
        <div className="demo-frame" style={{ position: "relative", paddingBottom: "75%", height: 0 }}>
          {/* Loom embed (oEmbed-reported aspect ratio is 1920x1440, hence the 75% above) —
              replaces the old self-hosted /demo.mp4. See
              https://www.loom.com/share/b4ab34fd594e4befb6913c1869fab50e */}
          <iframe
            src="https://www.loom.com/embed/b4ab34fd594e4befb6913c1869fab50e"
            title="Threadly demo — approving and posting AI Reddit replies"
            frameBorder={0}
            allow="fullscreen"
            allowFullScreen
            style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%" }}
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
              <li>Unlimited approved connections on Reddit</li>
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

      <FeaturedOnBelt />

      <LandingFooter />
    </>
  );
}
