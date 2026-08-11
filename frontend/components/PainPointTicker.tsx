// Quotes surfaced by the daily marketing/SEO research routine (see the "Threadly Daily
// Marketing & SEO Digest" cloud routine) — hand-copied in here, not fetched live. The routine's
// report lives on claude.ai, not this app, so refreshing this list day-to-day means swapping
// this array, the same as updating any other landing-page copy.
const PAIN_POINTS = [
  {
    quote:
      "Manual monitoring doesn't scale — people find perfect threads where prospects are asking for their product but arrive 6-8 hours too late, by which time there are 50+ comments and their response gets buried at the bottom.",
    source: "Indie Hackers",
  },
  {
    quote:
      "Problem keywords like 'spending hours on reddit,' 'manual reddit search,' and 'there has to be a better way' convert better than solution keywords, because fewer people monitor them.",
    source: "Indie Hackers",
  },
  {
    quote:
      "The mentions that matter most often don't tag you — a buyer asking for alternatives doesn't, and a customer sharing your product page without your handle doesn't.",
    source: "CommunityTracker",
  },
  {
    quote:
      "Automate the drafting, not the judgment — manual review isn't just a safety step, it's where your voice comes back in.",
    source: "Industry commentary",
  },
  {
    quote:
      "Multiple review sites report Tweet Hunter users citing X account warnings, shadowbans, and restrictions tied to its Auto DM/Auto Comment features.",
    source: "Product review sites",
  },
];

export function PainPointTicker() {
  // Rendered twice back-to-back so the CSS animation can loop seamlessly from -0% to -50%
  // and land exactly back on the first copy — see .pain-ticker-track's keyframes.
  const items = [...PAIN_POINTS, ...PAIN_POINTS];

  return (
    <aside className="pain-ticker" aria-label="What founders are saying about this problem">
      <div className="pain-ticker-header">
        <span className="pain-ticker-dot" />
        Customer Pain-Point Research
      </div>
      <div className="pain-ticker-window">
        <div className="pain-ticker-track">
          {items.map((item, i) => (
            <div className="pain-ticker-item" key={i}>
              <p>&ldquo;{item.quote}&rdquo;</p>
              <span className="pain-ticker-source">— {item.source}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
