# Plan: Eval Suite Tab + File Split in advocate-design-system.jsx

## Context

The advocate design system JSX prototype (`project_requirements_and_research/advocate-design-system.jsx`) is a ~2400-line single-file React app. The presearch doc (Section 9) defines a comprehensive eval framework: 10 test categories, 50+ test cases, MVP gate cases, pass/fail criteria, and adversarial scenarios. This plan:
1. Splits the monolith into logical modules (tokens, primitives, screens)
2. Adds a new "Eval Suite" tab to the design doc that visually renders the eval dataset structure

---

## File split

All files live in `project_requirements_and_research/`.

### `design-tokens.jsx` — ALREADY DONE
Lines ~1–182. Exports: `useWindowWidth`, `computeScale`, `I`, `blendWithBlack`, `tintSurface`, `makeDark`, `adjustBrightness`, `patientThemesLight`, `providerLight`, `themeIcons`, `shapes`, `typeScale`.

### `components.jsx` — ALREADY DONE
Lines ~183–395. Exports: `ColorSwatch`, `ColorGroup`, `M3Button`, `M3Card`, `M3Chip`, `M3NavItem`, `ConfidenceBadge`, `StarRating`, `ChatMessage`, `StageIndicator`, `MiniChatPreview`, `MiniSpecialistPreview`, `MiniChecklistPreview`, `TypingIndicator`.

### `patient-screens.jsx` (new)
Lines ~397–542, ~870–1237 (patient-only screens + SettingsScreen):
- `RecognitionScreen` (397), `NavigationScreen` (420), `PrepScreen` (458)
- `ChecklistScreen` (808), `WelcomeScreen` (871), `TimelineScreen` (926)
- `ProviderSearchScreen` (989), `SomaticScreen` (1090), `DismissalScreen` (1135), `SettingsScreen` (1185)
- Imports: React+useState from "react"; shapes, I from "./design-tokens.jsx"; M3Card, M3Button, M3Chip, M3NavItem, ConfidenceBadge, StarRating, ChatMessage, TypingIndicator, StageIndicator from "./components.jsx"

### `provider-screens.jsx` (new)
Lines ~544–807 (provider screens + shared schedule data):
- `SCHEDULE_DATA` (544), `STATUS_DOT_COLORS` (555), `STATUS_DOT_LABELS` (562)
- `ScheduleTimeline` (569) — shared helper used by provider screens
- `ProviderBriefScreen` (611), `ProviderDashboardScreen` (654)
- `PatientSummaryScreen` (698), `DismissalFlagsScreen` (772)
- Imports: React+useState from "react"; shapes, I from "./design-tokens.jsx"; M3Button, M3Card, M3Chip, ConfidenceBadge from "./components.jsx"

### `platform-views.jsx` (new)
Lines ~1237–1808 (platform device frame views):
- `navItems` (1237), `PlatformHeader` (1239), `MobileChatContent` (1250), `ChatInput` (1259)
- `IOSView` (1270), `AndroidView` (1333), `DesktopView` (1386), `WindowsView` (1455)
- `MacView` (1513), `WebView` (1597), `TabletView` (1672), `WindowsBrowserView` (1743)
- Imports: React+useState from "react"; shapes, I, useWindowWidth, computeScale from "./design-tokens.jsx"; M3Button, M3Card, M3Chip, M3NavItem, ChatMessage, ConfidenceBadge, StageIndicator from "./components.jsx"; all screens from "./patient-screens.jsx" and "./provider-screens.jsx"

### `platform-adaptations.jsx` (new)
Lines ~1811–2128 (platform-specific UI component demos):
- `IOSAdaptations` (1811), `AndroidAdaptations` (1857), `DesktopAdaptations` (1907)
- `WindowsAdaptations` (1955), `MacAdaptations` (2000), `WebAdaptations` (2044)
- `TabletAdaptations` (2087), `WindowsBrowserAdaptations` (2106)
- Imports: React from "react"; shapes, I from "./design-tokens.jsx"; M3Button, M3Card, M3Chip, M3NavItem from "./components.jsx"; navItems from "./platform-views.jsx"

### `eval-suite.jsx` (new)
New component — see design section below.
- Imports: React from "react"; shapes, I from "./design-tokens.jsx"; M3Card, M3Chip from "./components.jsx"

### `advocate-design-system.jsx` (rewritten/trimmed)
After extraction, contains only:
- Imports from all 6 new modules
- `SignInScreen` component (lines ~2132–2379, stays here)
- `tabs` array (updated to include eval-suite)
- `AdvocateDesignSystem` default export

---

## Eval Suite component design (`eval-suite.jsx`)

```jsx
export function EvalSuiteScreen({ t }) { ... }
```

### Layout (3 sections, top to bottom)

**Section 1 — Stat banner (3 cards in a row)**
| Stat | Value |
|---|---|
| Total test cases | 50+ |
| Pass rate target | >90% |
| Consistency lock | temperature=0 |

Each card: `M3Card variant="outlined"`, large number in `t.primary`, label in `t.onSurfaceVariant`, icon from `I`.

**Section 2 — Category table + Example case (side by side on wide, stacked on narrow)**

Left: Category overview table
Columns: Category | Target | Status
10 rows from presearch Section 9 (see below)
Status chips: "Planned" = surfaceContainerHigh/onSurfaceVariant, "In Progress" = secondaryContainer/onSecondaryContainer, "Done" = primaryContainer/onPrimaryContainer
Row border: `1px solid t.outlineVariant`

| Category | Target | Initial Status |
|---|---|---|
| Happy path — appointment prep | 15+ | Planned |
| Happy path — navigation | 5+ | Planned |
| Edge cases | 10+ | Planned |
| Adversarial | 10+ | Planned |
| Multi-step | 10+ | Planned |
| Clinical accuracy | 5+ | Planned |
| Tool selection | 5+ | Planned |
| Consistency | 5+ | Planned |
| Somatic fallback | 5+ | Planned |
| Patient's Own Words | 5+ | Planned |

Right: Example test case card (MVP Gate Case 2)
Fields: Input query | Expected tool calls (chip row) | Expected output | Pass criteria | Fail criteria
Pass criteria: `t.primary` with `I.checkCircle`
Fail criteria: `t.error` with `I.alertCircle`

**Section 3 — Adversarial scenarios table**
Header in `t.errorContainer`/`t.onErrorContainer` with `I.shieldCheck` icon
4 rows from Demo 10:
1. Instruction injection — Condition.code.display
2. Role confusion — Patient.name.text
3. Base64 injection — DocumentReference
4. System prompt extraction — Patient message

Each row: attack vector, location, expected behavior. Row background alternates `t.surface` / `t.surfaceContainerLowest`.

---

## Tab registration

In `advocate-design-system.jsx`, add to `tabs` array:
```js
{ id: "eval-suite", label: "Eval Suite" },
```

Add conditional block:
```jsx
{activeTab === "eval-suite" && (
  <EvalSuiteScreen t={t} />
)}
```

---

## Import graph after split

```
main.jsx
  └── advocate-design-system.jsx
        ├── design-tokens.jsx          (tokens, themes, icons, hooks)
        ├── components.jsx             (M3Button, M3Card, M3Chip, ...)
        ├── patient-screens.jsx        (imports from tokens + components)
        ├── provider-screens.jsx       (imports from tokens + components)
        ├── platform-views.jsx         (imports from tokens + components + patient-screens + provider-screens)
        ├── platform-adaptations.jsx   (imports from tokens + components + platform-views[navItems])
        └── eval-suite.jsx             (imports from tokens + components)
```

`advocate-design-system.jsx` imports from all 6 modules.

---

## Styling conventions

- All colors via `t.*` tokens — no hardcoded values
- `M3Card`, `M3Chip`, `ConfidenceBadge` reused from `components.jsx`
- No emojis; icons from `I` object
- No `!important`

---

## Verification

1. `cd project_requirements_and_research && npm run dev`
2. All 5 tabs render without error (Design System, Preview, Sign In, Flows, Eval Suite)
3. Toggle dark mode — eval suite colors invert correctly
4. Switch patient themes — accent colors update in stat cards
5. No console errors or missing import warnings
