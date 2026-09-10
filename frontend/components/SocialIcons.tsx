export function XIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

export function LinkedInIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

// Reddit's own brand orange (#FF4500), full color rather than currentColor like the icons
// above — this one's used as a platform/integration badge (see the homepage's "Where
// Threadly works" section), where the point is to be recognizable as Reddit specifically,
// not to blend into surrounding text color the way a footer social link does. A simplified,
// hand-drawn Snoo silhouette (own shapes, not a reproduction of Reddit's exact brand
// artwork/path data) — legible at small badge sizes without needing Reddit's full logo file.
export function RedditIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#FF4500" />
      <line x1="16.1" y1="7.3" x2="17.6" y2="4.1" stroke="#fff" strokeWidth="1" strokeLinecap="round" />
      <circle cx="17.8" cy="3.7" r="1.3" fill="#fff" />
      <circle cx="6.3" cy="12.6" r="2.1" fill="#fff" />
      <circle cx="17.7" cy="12.6" r="2.1" fill="#fff" />
      <ellipse cx="12" cy="13.6" rx="7" ry="6" fill="#fff" />
      <circle cx="9" cy="12.6" r="1.15" fill="#FF4500" />
      <circle cx="15" cy="12.6" r="1.15" fill="#FF4500" />
      <path
        d="M8.5 15.6c1 .9 2.2 1.4 3.5 1.4s2.5-.5 3.5-1.4"
        stroke="#FF4500"
        strokeWidth="1"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}
