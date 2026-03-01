# Plan: Advocate Design System — Phone Scale Fix + Missing Screens

## Context
The `advocate-design-system.jsx` design preview has two issues:
1. **Phone scale**: iOS and Android phone frames render at full `width: 375` with no visual scaling, making them feel oversized on the page rather than like a device preview.
2. **Missing screens**: Stage 3 (Provider Search), Welcome screen, Somatic Prompt Card demo, and Dismissal Alert Card demo are all specified in the M3 design spec but not implemented in the JSX.

## File to modify
`project_requirements_and _research/advocate-design-system.jsx`

---

## Part 1: Phone Scale Fix

Wrap the `width: 375` phone div in both `IOSView` and `AndroidView` with a scale container using CSS transform. The phone's internal layout stays at 375px (correct proportions, legible text, correct padding) — it just renders visually smaller.

```jsx
// Wrap pattern for both IOSView and AndroidView:
<div style={{ transform: "scale(0.78)", transformOrigin: "top center", marginBottom: -80 }}>
  <div style={{ width: 375, margin: "0 auto", borderRadius: 44, ... }}>
    ...
  </div>
</div>
```

- Scale: `0.78` — 375px → ~293px visual, feels like a device preview without being too small to read
- `transformOrigin: "top center"` — anchors scaling to top so it doesn't float
- `marginBottom: -80` — compensates for the extra whitespace CSS transform leaves (scaled-down element still occupies its original layout box height)
- Android uses `borderRadius: 24` (not 44) so keep that intact

---

## Part 2: New Screens

### 2a. `WelcomeScreen({ t })` component
- Two entry point cards side by side (outlined variant)
- Card A: filled card with calendar icon — "I have an appointment" → enters Stage 4
- Card B: outlined card with search icon — "Something feels wrong" → enters Stage 1
- FHIR connection status at bottom: small dot + "Connected to health records" in `onSurfaceVariant`
- "Continue previous session" as a small `elevated` card below the entry cards: shows "Resume: Headache journey · Stage 2 · Last active 2h ago" in `onSurfaceVariant`, with an `arrowRight` icon
- Centered layout, generous padding, Display Small headline at top

### 2b. `ProviderSearchScreen({ t })` component (Stage 3)
Per spec section 8.4:
- Top search bar: `extraLarge` border radius, leading search icon, trailing filter icon
- Horizontal scrolling filter chip row: Distance, Insurance, Reviews, Availability
- Two provider cards (elevated): name, credentials, specialty, distance, star rating
  - One expanded to show review summary (2 strong + 1 critical)
- Segmented button (list/map toggle) in `secondaryContainer` — shown as two chips

### 2c. `SomaticPromptCard({ t })` component + demo screen
- New screen "Somatic" tab
- Shows a normal chat screen (Recognition stage) where somatic fallback has triggered
- Chat input area gets `tertiary` border + label "Tell me about what you feel in your body"
- A `tertiaryContainer` card appears above input with body-part selection chips:
  - "Head / neck", "Chest", "Abdomen", "Back", "Limbs"
  - Secondary chips for sensation type: "Aching", "Sharp", "Pressure", "Burning"
- Card has `large` border radius and 1dp `tertiary` border per spec

### 2d. `DismissalAlertCard({ t })` component + demo screen
- New screen "Dismissal" tab
- Shows post-appointment context: first, a completed appointment outcome card (`tertiaryContainer` background: "Appointment completed · Neurotology Consult · Feb 24")
- Then the dismissal alert below it in context:
  - `errorContainer` background, shieldAlert-style icon (use `I.alertCircle`) in `onErrorContainer`
  - Title: "Concern may not have been addressed"
  - Body: specific gap + suggested follow-up question
  - Two action buttons: "Ask about this" (filled) + "Mark as resolved" (outlined)
- Demonstrating the full dismissal_pattern_detector output in realistic post-appointment flow

---

## Part 2e. `TimelineScreen({ t })` component — Stage 1 output
- New "Timeline" tab (fills the gap between Stage 1 and Stage 2)
- Vertical symptom timeline: each entry is an elevated card with a left-side date column and a right-side content column
- Date column: `onSurfaceVariant` label (body small), vertical line connecting entries (2dp, `outlineVariant`)
- Entry types: Encounter (calendar icon), Condition (alertCircle icon), Observation (zap icon), each with distinct `primaryContainer` / `tertiaryContainer` / `secondaryContainer` backgrounds
- Each entry shows: event type label, title, FHIR citation chip in `tertiary`
- At least 4 entries showing a timeline from Oct 2025 → Feb 2026 (matching the headache scenario)
- "Export Timeline" button (outlined) at bottom

## Part 2f. Stage 5 prep tabs — extend `PrepScreen` to show all 3 tabs
Currently `PrepScreen` only renders "Patient Prep Sheet" content regardless of which tab chip is selected. Fix this:
- Add `useState` for active prep tab (default: `"prep"`)
- Tab 1 "Patient Prep": existing content (already implemented)
- Tab 2 "Clinical Brief": rendered inside `PrepScreen` using provider theme colors (`providerLight` or dark variant). Shows a compact version of `ProviderBriefScreen` content in a read-only inset card. Label: "Preview — what your doctor will receive."
- Tab 3 "My Own Words": two sub-sections:
  - **Prose version** (body large, 1.6 line height, generous padding): "In my own words: I've been having these debilitating headaches since October when I hit my head. Nobody has taken it seriously. They happen every day and feel like pressure behind my eyes..."
  - **Bullet summary** (3 key points as M3 list items with `primary` leading dots)
  - "Practice reading aloud" button (filled tonal, toggles to "Stop practice") — uses a second `useState(false)` inside `PrepScreen` for aloud mode; when active, wraps first sentence in `secondaryContainer` background span

## Part 2g. `TabletView({ t })` component
- New "Tablet" tab showing a tablet-sized frame (~768px wide, iPad-style border radius ~24px)
- Two-column split: chat on left (~55%), structured output panel on right (~45%)
- Navigation: bottom nav bar (same as phone) — tablet portrait uses bottom nav per spec breakpoint 600–840dp
- Left panel: chat messages + input
- Right panel: stage indicator at top, then specialist card (Stage 2 content)
- Shows the responsive advantage: chat + output visible simultaneously
- Frame: 768×560 visible area, `borderRadius: 24`, `border: 2px solid outlineVariant`

## Part 2h. `WindowsBrowserView({ t })` component
- New "Windows Browser" tab showing Edge/Chrome browser on Windows
- Uses the `WebView` layout as base (top nav bar, chat + side panel)
- Windows chrome: `borderRadius: 4` (Fluent-style, sharper corners)
- Title bar: Windows-style with minimize/maximize/close controls (flat squares, not macOS circles)
- Address bar: Fluent-style pill with search icon
- Content: same web layout as `WebView` but with Windows browser chrome wrapping it
- Height/width similar to `WebView` mock (~900×500)

---

## Part 3: Tab registration

Add new tab entries to the `tabs` array at line 1062 (Settings tab goes between existing tabs and new ones):
```js
{ id: "welcome", label: "Welcome" },
{ id: "timeline", label: "Timeline" },   // Stage 1 output
{ id: "search", label: "Stage 3" },
{ id: "somatic", label: "Somatic" },
{ id: "dismissal", label: "Dismissal" },
{ id: "settings", label: "Settings" },
{ id: "tablet", label: "Tablet" },
{ id: "winbrowser", label: "Win Browser" },
```

Add corresponding conditional renders in the content section (lines ~1211-1215).

Add missing SVG icons to the `I` object:
```js
// Filled star for ratings
star: (c, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill={c} stroke="none"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>,
// Outline star for partial ratings
starOutline: (c, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>,
// Chevron down for expandable rows
chevronDown: (c, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
// Database for FHIR source attribution
database: (c, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
// Calendar for appointment entry points and timeline
calendar: (c, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
```

Also add a reusable `StarRating({ rating, max = 5, t })` helper that renders `rating` filled stars + `max-rating` outline stars + numeric label.

---

## Part 3b: iOS Dynamic Island
Replace the current 3-dot status bar in `IOSView` with a Dynamic Island:
- Keep the `9:41` time on the left
- Add a centered pill (width: 120, height: 34, borderRadius: 20, backgroundColor: `#000`) at top center — the Dynamic Island
- Signal indicators (battery/wifi) in a row on the right
- The status bar height stays at 50px

## Part 3c: Stage 3 map view state
In `ProviderSearchScreen`, add a `useState` for `viewMode` ("list" | "map"):
- Segmented control at top (List / Map chips)
- "List" state: existing provider cards list
- "Map" state: grey rectangle placeholder (`surfaceContainerHigh` background) with 3 `mapPin` icons at different positions and a floating provider name card at bottom (like Google Maps bottom sheet preview)

## Part 3d: Settings screen
New "Settings" tab showing:
- **Account section**: Avatar circle (primary color, initials), name, email
- **Theme section**: 5 theme color circles in a row (reuse the header's theme circles pattern) with active indicator
- **FHIR connection**: Status card with green/red indicator dot, "Connected to OpenEMR" label, "Disconnect" text button
- **Preferences**: Dark mode toggle (M3 Switch), Caregiver mode toggle
- **Session**: "Clear session data" outlined button, "Export all data" outlined button
Component adaptations grid: account avatar, toggle list item, connection status card

## Part 3e: Caregiver mode badge — add to Components tab
Under a new "Caregiver Mode" section in the Components tab:
- App bar with the Advocate logo + a small `secondaryContainer` badge pill saying "Proxy: Sarah M."
- Note below: "All outputs include 'Prepared by [caregiver] on behalf of [patient]'"
- Shows how the badge sits in the top-right of the app bar without disrupting other nav elements

---

## Part 3f: Spec gap fixes to existing screens

### TypingIndicator component
Add `TypingIndicator({ t })` — agent-styled bubble with 3 small circles (16dp each), `primaryContainer` background, 20dp radius. Add it to `RecognitionScreen` between the last agent message and the quick reply chips.

### ChecklistScreen — category headers + FHIR items
Restructure `ChecklistScreen` items into 3 groups:
- **Documents** (label small subheader, `onSurfaceVariant`, uppercase): Insurance card, Photo ID, Portal records download
- **Medical Info** (auto-populated from FHIR — show small database icon in `tertiary` + "From your records" label): Medications list (Lisinopril 10mg, Metformin 500mg), Active conditions
- **Personal Prep**: Top 3 concerns, Symptom start dates, Questions for specialist, Transportation

FHIR auto-populated items get a `tertiaryContainer` background (instead of `surfaceContainerHigh`) and a small `I.database` icon next to the text.

### ProviderBriefScreen — Discrepancy flag styling
Change the "Discrepancy Flag" row from a plain label+text to an `errorContainer` card with 3dp `error` left border — matching spec 8.7: "Use `errorContainer` background with left border accent (`error` color)."

### NavigationScreen — "Why this specialist?" expandable
Add a collapsed expandable row at the bottom of the specialist card: chevron-down icon + "Why this specialist?" label in `onSurfaceVariant`. Static (no animation needed in design spec).

---

## Part 4: Component Adaptations grids for new screens

Each new screen gets a 2-column adaptations grid below its mockup, consistent with existing platform screens:

- **Welcome** — EntryCard (filled vs outlined), FHIR status indicator, session resume link
- **Timeline** — Timeline entry card variants (Encounter/Condition/Observation), icon+color legend
- **Stage 3 (Provider Search)** — Search bar, Filter chips, Provider card (expanded vs collapsed), Map/List toggle, star rating widget
- **Somatic** — SomaticPromptCard component, body-part chips, sensation chips, somatic-mode input border + label
- **Dismissal** — DismissalAlertCard component, action button pair (filled + outlined), badge variants
- **Settings** — Account avatar, toggle list item, FHIR connection status card (tertiaryContainer vs errorContainer)
- **Tablet** — Two-column layout diagram, touch target sizing (48dp min), bottom nav vs nav rail breakpoint
- **Win Browser** — Fluent hover card, Windows tab bar (sharp radius), Fluent button variants

## Part 5: Components tab additions

### MiniChatPreview + MiniSpecialistPreview
Add a "Composite Previews" section at the bottom of the Components tab (after Shape Scale). Show `MiniChatPreview` and `MiniSpecialistPreview` side by side in a 2-column grid.

### FHIR Citation Block
Add standalone showcase of the FHIR citation block:
- `surfaceContainerHigh` background, 3dp `tertiary` left border, label + monospace resource IDs

### StageProgressIndicator
Add standalone showcase of `StageIndicator` at each stage (1 through 5) stacked vertically, showing the progression states.

### Caregiver Mode badge
Add a "Caregiver Mode" section showing the app bar with a `secondaryContainer` pill badge "Proxy: Sarah M." on the right side of the nav bar.

## Part 6: maxWidth fix

Add `"tablet"` and `"winbrowser"` to the existing `["desktop", "windows", "mac", "web"]` list on line 1122 so these wide mockups get `maxWidth: 960` instead of 800. `"welcome"`, `"timeline"`, `"search"`, `"somatic"`, `"dismissal"` stay at 800 (phone-width content).

---

## Verification
Open the JSX in a React preview (e.g. StackBlitz or the project's dev server). Confirm:
1. No regressions — all existing tabs render correctly
2. iOS/Android phone frames are visually scaled down ~78% with no overflow/clipping issues
3. iOS status bar shows Dynamic Island pill
4. Stage 5 prep tabs switch between Patient Prep, Clinical Brief preview, and My Own Words content
5. Welcome tab shows two entry point cards + FHIR status indicator
6. Timeline tab shows 4+ dated entries with color-coded event types + legend
7. Stage 3 tab shows search bar + filter chips + provider cards + map/list toggle
8. Somatic tab shows tertiaryContainer prompt card with body-part and sensation chips
9. Dismissal tab shows errorContainer alert card with both action buttons
10. Settings tab shows account, theme, FHIR, preferences, session sections
11. Tablet tab shows two-column split with bottom nav
12. Win Browser tab shows Fluent browser chrome with square controls
13. ChecklistScreen groups items into 3 categories with FHIR auto-populated items highlighted
14. ProviderBriefScreen discrepancy flag uses errorContainer with left border
15. All new screens respond to dark mode toggle and all 5 patient themes + provider theme
