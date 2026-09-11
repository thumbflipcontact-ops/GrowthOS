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

// Google's standard multi-color "G" mark — the same icon Google's own brand guidelines
// expect on any third-party "Continue with Google" / "Sign in with Google" button (see
// frontend/app/login/page.tsx, frontend/app/signup/page.tsx). Full color like RedditIcon
// below, for the same reason: the point is to be recognizable as Google specifically.
export function GoogleIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"
      />
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
