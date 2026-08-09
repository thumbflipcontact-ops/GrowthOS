export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="9" fill="url(#threadly-logo-grad)" />
      <path
        d="M5.5 24C9 15 11 15 14 19.5C17 24 19 24 22 15C23.4 11 24.8 9.5 26.5 9"
        stroke="white"
        strokeOpacity="0.55"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="5.5" cy="24" r="2.1" fill="white" />
      <circle cx="14.2" cy="20.4" r="2.1" fill="white" />
      <circle cx="26.5" cy="9" r="2.4" fill="white" />
      <defs>
        <linearGradient
          id="threadly-logo-grad"
          x1="0"
          y1="0"
          x2="32"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#4f46e5" />
          <stop offset="55%" stopColor="#7c3aed" />
          <stop offset="100%" stopColor="#ec4899" />
        </linearGradient>
      </defs>
    </svg>
  );
}
