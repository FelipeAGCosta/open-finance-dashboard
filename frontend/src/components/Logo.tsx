/** Marca própria: monograma com uma linha ascendente em ouro velho sobre grafite. */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <defs>
        <linearGradient id="logo-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2a2b30" />
          <stop offset="1" stopColor="#131417" />
        </linearGradient>
        <linearGradient id="logo-gold" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#b8862f" />
          <stop offset="1" stopColor="#f3d48a" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#logo-bg)" />
      <rect x="2.5" y="2.5" width="59" height="59" rx="15.5" fill="none" stroke="rgba(255,255,255,0.08)" />
      <path d="M16 44 L27 33 L35 39 L48 22" fill="none" stroke="url(#logo-gold)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="48" cy="22" r="4.5" fill="#f3d48a" />
    </svg>
  );
}
