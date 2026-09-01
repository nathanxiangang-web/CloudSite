# UI 0.3.1 Design QA

## Source and rendered evidence

- Source: `C:\Users\Nathan\Desktop\Codex 图像 2026年9月1日 11_29_34.png`
- Mobile render: `work/ui-0.3.1/mobile-home-final.png`
- Combined comparison: `work/ui-0.3.1/mobile-reference-comparison.png`
- Desktop regression render: `work/ui-0.3.1/desktop-home.png`

## Comparison setup

- Mobile viewport: 393 CSS px wide.
- Desktop viewport: 1440 × 900 CSS px.
- Source normalization: cropped only the reference browser chrome (top 154 px and bottom toolbar after y=1598), then scaled to the rendered app-surface height for a shared comparison input.
- State: authenticated user, four collections, recent resources, and popular resources loaded from an isolated temporary QA database.
- The reference is a phone presentation rather than a same-DPR browser capture, so absolute page height was not treated as a fidelity metric. Component order, proportions, hierarchy, breakpoints, and visible states were compared.

## Verification

- Mobile desktop sidebar hidden; mobile header visible with logo left and account menu right.
- Hero, search, five labeled navigation items, compact storage row, two-column categories, four collection cards, three recent rows, and six popular cards match the reference hierarchy.
- No horizontal overflow at 393 px; no broken images.
- Mobile navigation, search navigation, and account dropdown work.
- 768–1023 px uses a compact 132 px desktop sidebar without horizontal overflow.
- Desktop keeps the existing CloudSite layout; sidebar is sticky and equals `100dvh`, main content uses `min-height:100dvh`, and mobile-only controls remain hidden.
- Browser console showed no application errors. The first collection image is eager-loaded to avoid the observed development LCP warning.
- TypeScript lint, seven web security tests, and the production Next.js build all pass.

## Comparison history

1. Initial pass exposed a three-line mobile title and invalid QA collection cover paths.
2. The title column and type size were adjusted to preserve the intended two-line headline.
3. QA covers were switched to the real bundled collection assets and recaptured; all images load successfully.
4. Tablet sidebar width and mobile recent-row visibility were corrected and rechecked.

## Remaining differences

- QA username and resource counts intentionally differ from the reference because the verification uses isolated local data.
- Existing CloudSite “为什么选择” and footer content remain below the reference-focused sections; no existing product content was removed.

final result: passed
