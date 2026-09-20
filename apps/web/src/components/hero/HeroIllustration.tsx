export function HeroIllustration() {
  return (
    <div className="hero-illustration" aria-hidden="true">
      <svg className="hero-art-svg" viewBox="0 0 640 420" xmlns="http://www.w3.org/2000/svg" focusable="false">
        <defs>
          <linearGradient id="heroCloudFill" gradientUnits="userSpaceOnUse" x1="330" y1="105" x2="330" y2="365">
            <stop offset="0%" stopColor="var(--cloud-start)" />
            <stop offset="100%" stopColor="var(--cloud-end)" />
          </linearGradient>
          <linearGradient id="heroFolderFill" gradientUnits="userSpaceOnUse" x1="285" y1="232" x2="463" y2="328">
            <stop offset="0%" stopColor="var(--folder-start)" />
            <stop offset="100%" stopColor="var(--folder-end)" />
          </linearGradient>
          <linearGradient id="heroFolderBackFill" gradientUnits="userSpaceOnUse" x1="290" y1="175" x2="290" y2="325">
            <stop offset="0%" stopColor="var(--folder-deep)" />
            <stop offset="100%" stopColor="var(--folder-start)" />
          </linearGradient>
          <radialGradient id="heroGlowFill" gradientUnits="userSpaceOnUse" cx="330" cy="252" r="315">
            <stop offset="0%" stopColor="var(--hero-glow)" />
            <stop offset="36%" stopColor="var(--hero-glow)" stopOpacity=".45" />
            <stop offset="72%" stopColor="var(--hero-glow)" stopOpacity="0" />
            <stop offset="100%" stopColor="var(--hero-glow)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="heroSheen" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0" />
            <stop offset="50%" stopColor="var(--glass-highlight)" stopOpacity=".9" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>
          <clipPath id="heroFolderClip"><rect x="305" y="244" width="138" height="72" rx="12" /></clipPath>
        </defs>
        <g className="hero-glow-svg"><ellipse cx="330" cy="252" rx="312" ry="188" fill="url(#heroGlowFill)" /></g>
        <g className="hero-cloud">
          <g fill="var(--cloud-shade)" opacity=".55" transform="translate(0 11)">
            <circle cx="185" cy="288" r="62" /><circle cx="300" cy="222" r="96" /><circle cx="448" cy="270" r="76" /><ellipse cx="335" cy="302" rx="192" ry="62" />
          </g>
          <g fill="url(#heroCloudFill)">
            <circle cx="185" cy="288" r="62" /><circle cx="300" cy="222" r="96" /><circle cx="448" cy="270" r="76" /><ellipse cx="335" cy="302" rx="192" ry="62" />
          </g>
        </g>
        <g className="hero-folder">
          <g className="hero-folder-back">
            <path d="M314 219 v-18 q0 -8 8 -8 h44 q8 0 8 8 v18 z" fill="url(#heroFolderBackFill)" />
            <rect x="312" y="217" width="125" height="94" rx="12" fill="url(#heroFolderBackFill)" />
            <g transform="rotate(-4 380 236)"><rect x="342" y="204" width="78" height="58" rx="6" fill="var(--card-fill)" /></g>
          </g>
          <g className="hero-folder-front">
            <rect x="305" y="244" width="138" height="72" rx="12" fill="url(#heroFolderFill)" />
            <rect x="317" y="251" width="114" height="12" rx="6" fill="var(--glass-highlight)" opacity=".5" />
            <g className="hero-folder-highlight" clipPath="url(#heroFolderClip)">
              <g transform="rotate(16 374 280)"><rect x="352" y="234" width="28" height="94" fill="url(#heroSheen)" /></g>
            </g>
          </g>
        </g>
        <g className="hero-image-card">
          <rect x="78" y="62" width="105" height="88" rx="16" fill="var(--card-fill)" stroke="var(--card-line)" strokeWidth="1.5" />
          <rect x="92" y="76" width="77" height="46" rx="8" fill="var(--card-icon)" />
          <circle cx="142" cy="90" r="6.5" fill="var(--card-icon-deep)" />
          <path d="M96 118 L114 102 L126 112 L141 97 L164 118 Z" fill="var(--card-icon-deep)" opacity=".85" />
          <rect x="92" y="130" width="50" height="7" rx="3.5" fill="var(--card-line)" />
          <rect x="92" y="141" width="30" height="7" rx="3.5" fill="var(--card-line)" />
        </g>
        <g className="hero-document-card">
          <rect x="278" y="34" width="134" height="96" rx="16" fill="var(--card-fill)" stroke="var(--card-line)" strokeWidth="1.5" />
          <rect x="294" y="52" width="68" height="10" rx="5" fill="var(--card-icon)" />
          <circle cx="390" cy="57" r="10" fill="var(--card-icon)" opacity=".75" />
          <rect x="294" y="72" width="102" height="8" rx="4" fill="var(--card-line)" />
          <rect x="294" y="86" width="88" height="8" rx="4" fill="var(--card-line)" />
          <rect x="294" y="100" width="62" height="8" rx="4" fill="var(--card-line)" />
        </g>
        <g className="hero-video-card">
          <rect x="495" y="52" width="122" height="96" rx="16" fill="var(--card-fill)" stroke="var(--card-line)" strokeWidth="1.5" />
          <rect x="511" y="68" width="90" height="52" rx="9" fill="var(--card-icon)" />
          <path d="M546 82 L570 96 L546 110 Z" fill="var(--card-fill)" />
          <rect x="511" y="128" width="56" height="7" rx="3.5" fill="var(--card-line)" />
        </g>
        <g className="hero-bubble-1"><circle cx="78" cy="262" r="15" fill="var(--bubble-fill)" /><circle cx="73" cy="256" r="4.5" fill="#ffffff" opacity=".55" /></g>
        <g className="hero-bubble-2"><circle cx="612" cy="208" r="11" fill="var(--bubble-fill)" /><circle cx="608" cy="204" r="3.2" fill="#ffffff" opacity=".55" /></g>
        <g className="hero-bubble-3"><circle cx="548" cy="332" r="8" fill="var(--bubble-fill)" /></g>
        <g className="hero-bubble-4"><circle cx="152" cy="352" r="9" fill="var(--bubble-fill)" /></g>
      </svg>
    </div>
  );
}