# Design Principles Reference

This document contains curated best practices from world-class designers and design systems. Reference these principles when generating design variations.

---

## Part 1: UX Foundations

### Jakob Nielsen's 10 Usability Heuristics

1. **Visibility of system status** - Always keep users informed through appropriate feedback within reasonable time
2. **Match between system and real world** - Use familiar language, concepts, and conventions
3. **User control and freedom** - Provide clear "emergency exits" (undo, cancel, back)
4. **Consistency and standards** - Follow platform conventions; same words mean same things
5. **Error prevention** - Eliminate error-prone conditions or ask for confirmation
6. **Recognition over recall** - Minimize memory load; make options visible
7. **Flexibility and efficiency** - Provide accelerators for expert users (shortcuts, defaults)
8. **Aesthetic and minimalist design** - Remove irrelevant information; every element competes
9. **Help users recover from errors** - Plain language errors with constructive solutions
10. **Help and documentation** - Provide concise, task-focused help when needed

### Don Norman's Design Principles

- **Affordances** - Design elements should suggest their usage
- **Signifiers** - Visual cues that indicate where actions should happen
- **Mapping** - Controls should relate spatially to their effects
- **Feedback** - Every action needs a perceivable response
- **Conceptual model** - Users should understand how the system works

### Cognitive Load Principles

- **Limit choices** - 5-7 items max in navigation; 3-4 options in decisions
- **Progressive disclosure** - Show only what's needed at each step
- **Chunking** - Group related items; break long forms into steps
- **Visual hierarchy** - Guide attention with size, color, contrast, position
- **Reduce cognitive friction** - Minimize decisions, clicks, and reading

### URL & State Principles

- **URL state reflection** - Important UI state (filters, tabs, pagination) should be in the URL
- **Shareable links** - Users should be able to share/bookmark the current view
- **Browser navigation** - Back/forward buttons should work as expected

### Destructive Actions

- **Confirmation required** - Delete, remove, and irreversible actions need explicit confirmation
- **Clear consequences** - State exactly what will happen ("This will permanently delete 5 files")
- **Recovery path** - Prefer soft delete with undo over immediate permanent deletion
- **Visual distinction** - Destructive buttons use warning colors (red) and distinct styling

---

## Part 2: Visual Design Systems

### Typography (from iA, Stripe, Linear)

**Hierarchy:**

```
Display:    32-48px, -0.02em tracking, 700 weight
Heading 1:  24-32px, -0.02em tracking, 600 weight
Heading 2:  20-24px, -0.01em tracking, 600 weight
Heading 3:  16-18px, normal tracking, 600 weight
Body:       14-16px, normal tracking, 400 weight
Caption:    12-13px, +0.01em tracking, 400-500 weight
```

**Best practices:**

- Max 60-75 characters per line for readability
- Line height: 1.4-1.6 for body text, 1.2-1.3 for headings
- Use weight contrast (400 vs 600) more than size contrast
- Limit to 2 font families maximum
- System fonts for performance: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`

**Typographic details:**

- Use proper ellipsis `…` not `...` (three dots)
- Use curly quotes `"` `"` not straight quotes `"`
- Non-breaking spaces for values: `10 MB`, `5 items` (use `&nbsp;` or `\u00A0`)
- `font-variant-numeric: tabular-nums` for numbers in tables, counters, prices
- `text-wrap: balance` for headings (prevents orphans/widows)
- `text-wrap: pretty` for body text (better line breaks)

### Spacing System (8px grid)

```
4px   - Tight: icon padding, inline spacing
8px   - Base: related elements, form field padding
12px  - Comfortable: between form fields
16px  - Standard: section padding, card padding
24px  - Relaxed: between sections
32px  - Spacious: major section breaks
48px  - Generous: page section separation
64px+ - Hero: landing page sections
```

**Spacing principles:**

- Related items closer together (Gestalt proximity)
- Consistent internal padding (all sides equal, or vertical > horizontal)
- White space is not wasted space—it creates focus
- Touch targets minimum 44x44px (Apple HIG)

### Color (from Stripe, Linear, Vercel)

**Neutral foundation:**

```
Background:     #FFFFFF / #000000 (dark)
Surface:        #FAFAFA / #111111 (dark)
Border:         #E5E5E5 / #333333 (dark)
Text primary:   #171717 / #EDEDED (dark)
Text secondary: #737373 / #A3A3A3 (dark)
Text tertiary:  #A3A3A3 / #737373 (dark)
```

**Accent usage:**

- Primary action: single brand color, used sparingly
- Interactive elements: consistent color for all clickable items
- Semantic colors: red (error), green (success), yellow (warning), blue (info)
- Hover states: 10% darker or add subtle background
- Focus states: 2px ring with offset, high contrast

**Color principles:**

- WCAG AA minimum: 4.5:1 for text, 3:1 for UI elements
- One primary accent color; avoid rainbow interfaces
- Use opacity for secondary states (hover, disabled)
- Dark mode: don't just invert—reduce contrast, use darker surfaces

**Dark mode setup:**

```html
<!-- On <html> element -->
<html class="dark" style="color-scheme: dark">

<!-- Theme color matching page background -->
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
```

### Content Handling

**Text truncation:**

```css
/* Single line truncation */
.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Multi-line truncation */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

/* Break long words */
.break-words {
  overflow-wrap: break-word;
  word-break: break-word;
}
```

**Flex children with text:**

```css
/* IMPORTANT: Flex children with text need min-w-0 to truncate properly */
.flex-child-with-text {
  min-width: 0; /* Allows text to shrink below content size */
}
```

**Empty states:**

- Always design the empty state—it's the first thing users see
- Include helpful message + primary action
- Use illustration or icon to add visual interest

**Images:**

```jsx
// Always include explicit dimensions to prevent layout shift
<img
  src="/image.jpg"
  width={800}
  height={600}
  alt="Description"
  loading="lazy"  // Defer off-screen images
/>

// For above-the-fold images
<img src="/hero.jpg" width={1200} height={800} alt="Hero" priority />
```

### Border Radius (from modern SaaS)

```
None (0px):     Tables, dividers, full-bleed images
Small (4px):    Buttons, inputs, tags, badges
Medium (8px):   Cards, modals, dropdowns
Large (12px):   Feature cards, hero elements
Full (9999px): Avatars, pills, toggle tracks
```

**Principles:**

- Consistency: pick 2-3 radius values and stick to them
- Nested elements: inner radius = outer radius - padding
- Sharp corners feel technical/precise; round feels friendly/approachable

### Shadows & Elevation (from Material, Linear)

```
Level 0: none (flat, on surface)
Level 1: 0 1px 2px rgba(0,0,0,0.05)      - Subtle lift (cards)
Level 2: 0 4px 6px rgba(0,0,0,0.07)      - Raised (dropdowns)
Level 3: 0 10px 15px rgba(0,0,0,0.1)     - Floating (modals)
Level 4: 0 20px 25px rgba(0,0,0,0.15)    - High (popovers)
```

**Principles:**

- Shadows should feel like natural light (top-down, slight offset)
- Dark mode: use lighter surface colors instead of shadows
- Combine with subtle border for definition
- Interactive elements can elevate on hover

---

## Part 3: Component Patterns

### Buttons (from Stripe, Linear)

**Hierarchy:**

1. **Primary** - One per view, main action, filled with brand color
2. **Secondary** - Supporting actions, outlined or ghost style
3. **Tertiary** - Low-emphasis actions, text-only with hover state
4. **Destructive** - Delete/remove actions, red with confirmation

**States:**

- Default → Hover (+shadow or darken) → Active (scale 0.97) → Disabled (50% opacity)
- Loading: replace text with spinner, maintain width
- Min width: 80px; min height: 36px (touch-friendly: 44px)

**Best practices:**

- **Specific labels:** "Save API Key" not "Continue" or "Submit"
- Verb + noun labels: "Create project" not "Create"
- Sentence case, not ALL CAPS
- Icon left of text (or icon-only with tooltip)
- Primary button right-aligned in forms/dialogs
- **Icon buttons require `aria-label`**

**Active state feedback:**

```css
button:active {
  transform: scale(0.97);
}
```

### Forms (from Airbnb, Stripe, Vercel)

**Input anatomy:**

```
┌─────────────────────────────────┐
│ Label                           │  ← Required (above input, not inside)
│ ┌─────────────────────────────┐ │
│ │ Placeholder...              │ │  ← Format hint only, ends with ...
│ └─────────────────────────────┘ │
│ Helper text or error message    │  ← Specific and actionable
└─────────────────────────────────┘
```

**Autocomplete attributes (required):**

```html
<!-- Always use appropriate autocomplete for user data -->
<input type="email" autocomplete="email" />
<input type="text" autocomplete="name" />
<input type="text" autocomplete="given-name" />
<input type="text" autocomplete="family-name" />
<input type="text" autocomplete="organization" />
<input type="text" autocomplete="street-address" />
<input type="text" autocomplete="postal-code" />
<input type="tel" autocomplete="tel" />
<input type="password" autocomplete="current-password" />
<input type="password" autocomplete="new-password" />
<input type="text" autocomplete="one-time-code" />
```

**Input types and modes:**

```html
<!-- Use correct type for validation and keyboard -->
<input type="email" inputmode="email" />
<input type="tel" inputmode="tel" />
<input type="url" inputmode="url" />
<input type="number" inputmode="numeric" />

<!-- Numeric input without spinners -->
<input type="text" inputmode="numeric" pattern="[0-9]*" />
```

**Disable spellcheck where inappropriate:**

```jsx
// Disable for codes, emails, usernames, URLs
<input type="text" spellCheck={false} autoComplete="username" />
<input type="email" spellCheck={false} />
<input type="text" spellCheck={false} placeholder="Enter code..." />
```

**Anti-patterns to avoid:**

```jsx
// NEVER block paste - this is hostile UX
<input onPaste={(e) => e.preventDefault()} />  // ❌ NEVER DO THIS

// NEVER use placeholder as label
<input placeholder="Email" />  // ❌ Placeholder disappears on focus

// NEVER validate on every keystroke
onChange={(e) => validateEmail(e.target.value)}  // ❌ Too aggressive
```

**Best practices:**

- Labels above inputs (not inside—accessibility)
- Placeholder ≠ label; use for format hints only, end with `...`
- Inline validation on blur, not on every keystroke
- Error messages: specific and actionable ("Email must include @")
- **Focus first error field** after form submission fails
- Success state: checkmark icon, green border (brief)
- Required fields: mark optional ones instead of required
- Single column forms outperform multi-column

**Unsaved changes warning:**

```jsx
// Warn users before leaving with unsaved changes
useEffect(() => {
  const handleBeforeUnload = (e) => {
    if (hasUnsavedChanges) {
      e.preventDefault();
      e.returnValue = '';
    }
  };
  window.addEventListener('beforeunload', handleBeforeUnload);
  return () => window.removeEventListener('beforeunload', handleBeforeUnload);
}, [hasUnsavedChanges]);
```

### Cards (from Material, Apple)

**Anatomy:**

```
┌────────────────────────────────┐
│ [Media/Image]                  │  ← Optional
├────────────────────────────────┤
│ Eyebrow · Metadata             │  ← Optional
│ Title                          │  ← Required
│ Description text that can      │  ← Optional
│ wrap to multiple lines...      │
├────────────────────────────────┤
│ [Actions]              [More]  │  ← Optional
└────────────────────────────────┘
```

**Best practices:**

- Entire card clickable for primary action
- Consistent padding (16-24px)
- Image aspect ratios: 16:9, 4:3, 1:1 (be consistent)
- Limit to 2 actions max; overflow to menu
- Hover: subtle lift (translateY -2px + shadow increase)

### Tables (from Linear, Notion)

**Best practices:**

- Left-align text, right-align numbers
- **Use `tabular-nums` for numeric columns** (consistent width digits)
- Zebra striping OR row hover, not both
- Sticky header on scroll
- Sortable columns: show current sort indicator
- Actions: row hover reveals action buttons (or kebab menu)
- Empty state: helpful message + action
- Pagination vs infinite scroll: pagination for data accuracy, infinite for browsing
- Min row height: 48px for touch; 40px for dense
- **Virtualize tables with >50 rows**

```css
.numeric-column {
  font-variant-numeric: tabular-nums;
  text-align: right;
}
```

### Navigation (from Apple HIG, Material)

**Patterns by scale:**

- **2-5 items**: Tab bar / horizontal tabs
- **5-10 items**: Side navigation (collapsible)
- **10+ items**: Side nav with sections/groups

**Best practices:**

- Current location always visible
- Breadcrumbs for deep hierarchy (not for flat structures)
- Mobile: bottom nav for primary actions (thumb-friendly)
- Icons + labels together; icon-only needs tooltip
- Consistent order across pages

---

## Part 4: Interaction Design

### Feedback Patterns (from Dan Saffer's Microinteractions)

**Every action needs feedback:**

1. **Immediate** - Button press visual (scale, color change)
2. **Progress** - Loading states for anything >1s
3. **Completion** - Success confirmation (toast, checkmark, animation)
4. **Failure** - Clear error with recovery path

**Loading states:**

- 0-100ms: No indicator needed
- 100-300ms: Subtle change (opacity, skeleton)
- 300ms-1s: Spinner or progress bar
- 1s+: Skeleton screens + progress indication
- 10s+: Background processing with notification

### State Handling

**Every component needs these states:**

```
Default    → Base appearance
Hover      → Interactive hint (cursor change, highlight)
Focus      → Keyboard navigation (visible ring)
Active     → Being pressed/activated
Loading    → Async operation in progress
Disabled   → Not available (reduce opacity, remove pointer)
Error      → Invalid input or failed operation
Success    → Completed successfully (brief)
Empty      → No data to display (helpful message + action)
```

### Touch & Pointer Interactions

**Faster tap response:**

```css
/* Remove 300ms tap delay on touch devices */
button, a, [role="button"] {
  touch-action: manipulation;
}
```

**Contain scroll in modals:**

```css
/* Prevent scroll chaining to body when modal/drawer reaches edge */
.modal, .drawer, .dropdown {
  overscroll-behavior: contain;
}
```

**Touch targets:**

- Minimum 44x44px for all interactive elements (Apple HIG)
- Provide adequate spacing between targets (8px minimum)

**Hover states for pointer devices only:**

```css
/* Only apply hover effects on devices with fine pointers */
@media (hover: hover) and (pointer: fine) {
  .card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-lg);
  }
}
```

**Tap highlight:**

```css
/* Customize or remove tap highlight on mobile */
button {
  -webkit-tap-highlight-color: transparent; /* Remove default */
  /* Or use a custom color */
  -webkit-tap-highlight-color: rgba(0, 0, 0, 0.1);
}
```

### Optimistic Updates (from Linear, Notion)

- Update UI immediately, sync in background
- Show subtle "Saving..." indicator
- On failure: revert UI + show error toast with retry
- Best for: toggles, reordering, text edits
- Avoid for: destructive actions, payments

### Progressive Disclosure

**Reveal complexity gradually:**

- Show essential options first
- "Advanced" or "More options" for power features
- Inline expansion over page navigation
- Tooltips for supplementary information
- Context menus for secondary actions

### Inferring Intent

**Anticipate user actions before they happen:**

```jsx
// Preload on mousedown (fires before click)
<button
  onMouseDown={() => prefetchData()}
  onClick={() => showData()}
>
  View Details
</button>

// Preload on hover for links
<Link
  href="/dashboard"
  onMouseEnter={() => router.prefetch('/dashboard')}
>
  Dashboard
</Link>
```

**Proximity-based preloading:**

```jsx
// Start loading when cursor approaches
function useProximityPreload(ref, onApproach) {
  useEffect(() => {
    const element = ref.current;
    const handleMouseMove = (e) => {
      const rect = element.getBoundingClientRect();
      const distance = Math.hypot(
        e.clientX - (rect.left + rect.width / 2),
        e.clientY - (rect.top + rect.height / 2)
      );
      if (distance < 100) onApproach();
    };
    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, [ref, onApproach]);
}
```

**Smart defaults:**

- Pre-fill forms with likely values
- Remember user's last selection
- Use geolocation for location fields
- Default date pickers to sensible dates (today, tomorrow)

### Interaction Metaphors

**Physical analogies users already understand:**

| Gesture | Real-world Metaphor | UI Behavior |
|---------|---------------------|-------------|
| Drag | Moving physical objects | Reorder, move items |
| Swipe | Flipping pages, pushing aside | Navigate, dismiss |
| Pinch | Zooming a camera lens | Scale content |
| Pull down | Stretching a spring | Refresh content |
| Long press | Pressing firmly to reveal | Context menu |

**Consistency requirement:**

Once you establish a gesture metaphor, use it consistently:

```
❌ Swipe right to delete in one view, swipe right to archive in another
✅ Swipe right always archives, swipe left always deletes
```

**Honor platform conventions:**

- iOS: Swipe from left edge = back navigation
- Android: Back button/gesture = return to previous screen
- Desktop: Right-click = context menu

### Ergonomic Interactions

**Expand hit areas with pseudo-elements:**

```css
/* Thin visual element with large tap target */
.icon-button {
  position: relative;
  width: 24px;
  height: 24px;
}

.icon-button::after {
  content: '';
  position: absolute;
  inset: -12px; /* Expands hit area to 48x48px */
}
```

**Bidirectional scroll support:**

```css
/* Support both LTR and RTL scrolling */
.horizontal-scroll {
  overflow-x: auto;
  scroll-behavior: smooth;
  /* Use logical properties */
  scroll-padding-inline: 16px;
}
```

**Thumb-friendly mobile zones:**

```
┌─────────────────────────────────┐
│     Hard to reach (top)         │  ← Avoid primary actions here
├─────────────────────────────────┤
│                                 │
│     Comfortable middle          │  ← Secondary actions OK
│                                 │
├─────────────────────────────────┤
│     Easy reach (bottom)         │  ← Primary actions here
└─────────────────────────────────┘
```

### Contained Gestures

**Prevent gesture conflicts with parent elements:**

```css
/* Contain drag/swipe gestures within element */
.draggable-area {
  touch-action: none; /* Disable browser handling */
  user-select: none;  /* Prevent text selection during drag */
}

/* Allow vertical scroll but capture horizontal */
.horizontal-swipe {
  touch-action: pan-y; /* Allow vertical, capture horizontal */
}
```

**Pointer capture for drag operations:**

```jsx
function useDrag(onDrag, onDragEnd) {
  const handlePointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      onDrag({ x: e.clientX, y: e.clientY });
    }
  };

  const handlePointerUp = (e) => {
    e.currentTarget.releasePointerCapture(e.pointerId);
    onDragEnd();
  };

  return {
    onPointerDown: handlePointerDown,
    onPointerMove: handlePointerMove,
    onPointerUp: handlePointerUp,
  };
}
```

**Drag threshold detection:**

```jsx
// Distinguish click from drag with movement threshold
const DRAG_THRESHOLD = 5; // pixels

function useDragThreshold() {
  const startPos = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const handlePointerDown = (e) => {
    startPos.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e) => {
    if (!startPos.current) return;

    const distance = Math.hypot(
      e.clientX - startPos.current.x,
      e.clientY - startPos.current.y
    );

    if (distance > DRAG_THRESHOLD) {
      setIsDragging(true);
    }
  };

  const handlePointerUp = (e) => {
    const wasDragging = isDragging;
    setIsDragging(false);
    startPos.current = null;
    return wasDragging; // Return true if was drag, false if was click
  };

  return { isDragging, handlePointerDown, handlePointerMove, handlePointerUp };
}
```

**Gesture state machine:**

```
IDLE → PRESS (pointer down)
PRESS → DRAG (movement > threshold)
PRESS → CLICK (pointer up, no movement)
DRAG → DRAG_END (pointer up)
DRAG_END → IDLE (animation complete)
```

---

## Part 5: Motion & Animation

### The Frequency Principle

Animation frequency should match usage frequency:

| Usage Pattern | Animation Approach |
|---|---|
| 100+ times/day | No animation—instant response |
| Occasional use | Standard animation (150-300ms) |
| Rare/first-time | Can add delight, longer duration |

Example: A "send message" button used constantly → instant. An "export report" button used weekly → can animate.

### Easing Blueprint

**Ease-out family (most common):**

Use for entrances, user-initiated actions, and most UI transitions.

```css
:root {
  /* Increasing intensity: quad → cubic → quart → quint */
  --ease-out-quad: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --ease-out-cubic: cubic-bezier(0.215, 0.61, 0.355, 1);
  --ease-out-quart: cubic-bezier(0.165, 0.84, 0.44, 1);
  --ease-out-quint: cubic-bezier(0.23, 1, 0.32, 1);
}
```

**Ease-in-out family:**

Use for on-screen movement (element moving from point A to point B).

```css
:root {
  --ease-in-out-quad: cubic-bezier(0.455, 0.03, 0.515, 0.955);
  --ease-in-out-cubic: cubic-bezier(0.645, 0.045, 0.355, 1);
}
```

**Easing decision flowchart:**

```
Is the element entering or exiting the screen?
  → Yes: Use ease-out (for both enter AND exit)

Is the element moving on screen (A to B)?
  → Yes: Use ease-in-out

Is it a hover state or color change?
  → Yes: Use ease (CSS default) or ease-out-quad

Is it constant/looping motion (spinner, progress)?
  → Yes: Use linear
```

### Timing Guidelines

| Element Type | Duration | Notes |
|---|---|---|
| Micro-interactions | 100-150ms | Buttons, toggles, hover states |
| Tooltips, dropdowns | 150-250ms | Small UI appearing |
| Modals, drawers | 200-300ms | Larger surfaces |
| Page transitions | 300-400ms | Full view changes |
| Staggered items | 30-50ms delay | Between each item |

**Important:** Exit animations should be 20-30% faster than entrances.

### Animation Patterns

**Entrances:**

- Fade in + slide up (8-16px)
- Scale from 0.95 to 1 + fade (never from 0)
- Stagger children by 30-50ms

**Exits:**

- Fade out (faster than entrance)
- Scale to 0.95 + fade
- Slide in direction of dismissal

**Transform origin:**

Always set `transform-origin` toward the trigger element:

```css
/* Dropdown opening from button */
.dropdown {
  transform-origin: top left; /* Opens from button location */
}

/* Modal opening from center */
.modal {
  transform-origin: center center;
}
```

**Hover flicker prevention:**

```css
/* ❌ Don't animate the parent on hover */
.card:hover {
  transform: scale(1.02); /* Causes flicker */
}

/* ✅ Animate a child element instead */
.card:hover .card-content {
  transform: scale(1.02);
}
```

**Sequential tooltips:**

After the first tooltip in a series, skip animation for subsequent ones:

```jsx
// Skip animation if another tooltip was shown recently
const skipAnimation = Date.now() - lastTooltipTime < 300;
```

### Spring Physics

**When to use springs:**

- Drag and drop interactions
- Gesture-based animations
- Interruptible motion (user can grab mid-animation)
- Physics-based feel (natural, organic)

**Spring parameters:**

```jsx
// Physical spring configuration
const spring = {
  stiffness: 300,  // Higher = faster, snappier
  damping: 30,     // Higher = less oscillation
  mass: 1          // Higher = more inertia, slower
};

// Typical ranges:
// stiffness: 100-1000 (most UI: 200-400)
// damping: 10-100 (most UI: 20-40)
// mass: 0.5-2 (most UI: 1)
```

**Critical principle: Never reuse spring values**

Each interaction should have its own tuned spring. A dropdown menu spring differs from a drag-to-dismiss spring.

```jsx
// ❌ Bad - same spring for everything
const SPRING = { stiffness: 300, damping: 30 };

// ✅ Good - tuned per interaction
const DROPDOWN_SPRING = { stiffness: 400, damping: 35, mass: 0.8 };
const DRAG_SPRING = { stiffness: 250, damping: 25, mass: 1 };
const BOUNCE_SPRING = { stiffness: 180, damping: 12, mass: 1 };
```

**Damping for rubber band effects:**

```jsx
// Rubber band effect for over-scroll
function rubberBand(offset, limit, elasticity = 0.55) {
  const clampedOffset = Math.max(0, offset);
  const delta = clampedOffset - limit;
  if (delta <= 0) return offset;

  // Logarithmic decay for natural feel
  return limit + (1 - Math.exp(-delta / (limit * elasticity))) * limit * elasticity;
}
```

**iOS-style projection (momentum scrolling):**

```jsx
// Project final position based on velocity
function project(velocity, position, deceleration = 0.998) {
  // v(t) = v0 * deceleration^t
  // When v(t) ≈ 0, t = log(0.001) / log(deceleration)
  const duration = Math.log(0.001) / Math.log(deceleration);
  const distance = velocity * (1 - Math.pow(deceleration, duration)) / (1 - deceleration);
  return position + distance;
}
```

**Framer Motion spring shorthand:**

```jsx
// Simple configuration
const springConfig = {
  type: "spring",
  duration: 0.5,  // Overall duration
  bounce: 0.2     // 0 = no bounce, 1 = very bouncy
};

// Subtle bounce (most UI): 0.1 - 0.3
// Playful bounce: 0.3 - 0.5
// Avoid > 0.5 in most production UI
```

### Motion Choreography

**Blur overlapping layers:**

When animated elements cross paths, they create visual noise. Add subtle blur:

```css
/* Add 1-2px blur during transitions */
.transitioning-element {
  filter: blur(1px);
}

/* Or use will-change to hint GPU compositing */
.animated-layer {
  will-change: transform;
  transform: translateZ(0); /* Force separate layer */
}
```

**Stagger animation delays:**

```jsx
// Stagger children by 30-50ms each
const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.04, // 40ms between each
      delayChildren: 0.1,    // Wait 100ms before starting
    }
  }
};

const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0 }
};
```

**Double exit stiffness:**

Exit animations should feel quicker. Double the spring stiffness:

```jsx
function AnimatedPanel({ isOpen }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{
        enter: { type: "spring", stiffness: 300, damping: 30 },
        exit: { type: "spring", stiffness: 600, damping: 30 } // 2x stiffness
      }}
    />
  );
}
```

**Crossfade icons (not swap):**

When changing icons, don't just swap. Scale down + blur out the old, scale up + blur in the new:

```jsx
// Icon crossfade
<AnimatePresence mode="wait">
  <motion.div
    key={iconKey}
    initial={{ opacity: 0, scale: 0.5, filter: 'blur(7px)' }}
    animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
    exit={{ opacity: 0, scale: 0.5, filter: 'blur(7px)' }}
    transition={{ duration: 0.15 }}
  >
    <Icon />
  </motion.div>
</AnimatePresence>
```

**Morph surfaces with overflow: hidden:**

When morphing between shapes, prevent content from spilling:

```jsx
// Container with overflow: hidden + crossfade content
<motion.div
  layout
  style={{ overflow: 'hidden', borderRadius: 12 }}
  transition={{ layout: { duration: 0.3 } }}
>
  <AnimatePresence mode="wait">
    <motion.div
      key={contentKey}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {content}
    </motion.div>
  </AnimatePresence>
</motion.div>
```

### High-Frequency Actions

**No fade-in for menus:**

Menus triggered frequently should appear instantly, but can fade out:

```jsx
// Instant appear, animated dismiss
<motion.div
  initial={false} // Skip enter animation
  animate={{ opacity: 1 }}
  exit={{ opacity: 0, transition: { duration: 0.1 } }}
>
  <Menu />
</motion.div>
```

**Skip animation between rapid data updates:**

```jsx
// Skip animation if update is too fast
const lastUpdate = useRef(Date.now());
const ANIMATION_THRESHOLD = 100; // ms

function updateValue(newValue) {
  const now = Date.now();
  const shouldAnimate = now - lastUpdate.current > ANIMATION_THRESHOLD;
  lastUpdate.current = now;

  if (shouldAnimate) {
    animateToValue(newValue);
  } else {
    setValueInstantly(newValue);
  }
}
```

**Keyboard interactions often need no animation:**

```jsx
// Tab navigation - instant focus, no animation
// Arrow key navigation - instant highlight
// Enter to select - instant (or very fast 50ms)
const keyboardTransition = { duration: 0.05 };
const pointerTransition = { duration: 0.15 };

const transition = isKeyboardNav ? keyboardTransition : pointerTransition;
```

### Gesture Lifecycle

**Three phases of gesture handling:**

```
START (pointer down)  → Set constraints, capture pointer
MOVE (pointer move)   → Update position continuously
END (pointer up)      → Animate to final position
```

**Use jump() for continuous updates, set() for animated snap:**

```jsx
import { useMotionValue, useSpring } from 'framer-motion';

function DraggableElement() {
  const x = useMotionValue(0);
  const springX = useSpring(x, { stiffness: 300, damping: 30 });

  const handleDrag = (e) => {
    // During drag: jump() for instant tracking (no spring delay)
    x.jump(e.clientX - startX);
  };

  const handleDragEnd = () => {
    // On release: set() for animated snap to final position
    springX.set(snapToNearest(x.get()));
  };

  return <motion.div style={{ x: springX }} />;
}
```

**useTransform for derived values:**

```jsx
import { useMotionValue, useTransform } from 'framer-motion';

function SwipeCard() {
  const x = useMotionValue(0);

  // Derive rotation from horizontal position
  const rotate = useTransform(x, [-200, 200], [-15, 15]);

  // Derive opacity from position
  const opacity = useTransform(x, [-200, 0, 200], [0.5, 1, 0.5]);

  return (
    <motion.div
      style={{ x, rotate, opacity }}
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
    />
  );
}
```

**Gesture state tracking:**

```jsx
function useGestureState() {
  const [state, setState] = useState('idle');
  // idle → press → drag → drag-end → idle

  const handlers = {
    onPointerDown: () => setState('press'),
    onDragStart: () => setState('drag'),
    onDragEnd: () => {
      setState('drag-end');
      // Return to idle after animation
      setTimeout(() => setState('idle'), 300);
    },
    onPointerUp: () => {
      if (state === 'press') setState('idle'); // Was click, not drag
    }
  };

  return { state, handlers };
}
```

### Animation Performance

**Only animate compositor properties:**

```css
/* ✅ GPU-accelerated (cheap) */
transform: translateX(100px);
transform: scale(1.1);
transform: rotate(45deg);
opacity: 0.5;

/* ❌ Triggers layout/paint (expensive) */
width: 200px;
height: 200px;
top: 100px;
left: 100px;
margin: 20px;
padding: 20px;
```

**Never use `transition: all`:**

```css
/* ❌ Bad - animates everything including layout properties */
.element {
  transition: all 0.3s ease;
}

/* ✅ Good - explicit properties */
.element {
  transition: transform 0.3s var(--ease-out-cubic),
              opacity 0.3s var(--ease-out-cubic);
}
```

**Fix transform shakiness:**

```css
/* Add will-change if animation looks shaky */
.animated-element {
  will-change: transform;
}

/* Remove after animation completes to free memory */
```

**CSS vs JavaScript animations:**

| Use CSS | Use JavaScript |
|---|---|
| Simple state transitions | Complex sequences |
| Hover/focus effects | Gesture-based |
| No user interaction during | Interruptible animations |
| Performance-critical | Dynamic values |

### Reduced Motion

**Every animation needs a reduced motion alternative:**

```css
/* Base animation */
.modal {
  animation: slideIn 0.3s var(--ease-out-cubic);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
}

/* Reduced motion: instant or fade only */
@media (prefers-reduced-motion: reduce) {
  .modal {
    animation: fadeIn 0.15s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
  }
}
```

**Framer Motion hook:**

```jsx
import { useReducedMotion } from 'framer-motion';

function Modal({ children }) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={{ opacity: 0, y: shouldReduceMotion ? 0 : 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0.1 : 0.3 }}
    >
      {children}
    </motion.div>
  );
}
```

**What reduced motion should do:**

- Remove parallax effects
- Stop auto-playing videos/carousels
- Replace slide/scale with fade or instant
- Keep essential feedback (success checkmarks can still appear, just not animated)

---

## Part 6: Accessibility Essentials

### WCAG Quick Reference

**Perceivable:**

- Color contrast: 4.5:1 text, 3:1 UI components
- Don't rely on color alone (add icons, patterns)
- Text resizable to 200% without loss
- Captions for video; transcripts for audio

**Operable:**

- All functionality via keyboard
- No keyboard traps
- Skip links for repeated content
- Touch targets: 44x44px minimum

**Understandable:**

- Consistent navigation
- Identify input errors clearly
- Labels and instructions for forms

**Robust:**

- Semantic HTML elements
- ARIA only when HTML isn't enough
- Tested with screen readers

### Focus Management

**Use `:focus-visible` over `:focus`:**

```css
/* ✅ Only show focus ring for keyboard navigation */
:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* ❌ Don't remove outline without replacement */
:focus {
  outline: none; /* BAD - removes accessibility */
}
```

**Compound controls:**

```css
/* Highlight parent when any child is focused */
.input-group:focus-within {
  box-shadow: 0 0 0 2px var(--color-primary);
}
```

### Keyboard Navigation

**All interactive elements must be keyboard-operable:**

```jsx
// ❌ Click-only interaction
<div onClick={handleAction}>Click me</div>

// ✅ Keyboard accessible
<button onClick={handleAction}>Click me</button>

// ✅ If must use div, add keyboard support
<div
  role="button"
  tabIndex={0}
  onClick={handleAction}
  onKeyDown={(e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleAction();
    }
  }}
>
  Click me
</div>
```

**Keyboard patterns:**

- Tab order must match visual order
- Enter/Space activate buttons and links
- Escape closes dialogs and dropdowns
- Arrow keys navigate within components (tabs, menus)

### ARIA Patterns

**Icon buttons require `aria-label`:**

```jsx
// ❌ No accessible name
<button><CloseIcon /></button>

// ✅ Accessible
<button aria-label="Close dialog"><CloseIcon /></button>
```

**Form controls require labels:**

```jsx
// ❌ No label
<input type="email" placeholder="Email" />

// ✅ Visible label
<label>
  Email
  <input type="email" />
</label>

// ✅ Or visually hidden label
<label htmlFor="email" className="sr-only">Email</label>
<input id="email" type="email" placeholder="email@example.com" />
```

**Live regions for async updates:**

```jsx
// Announce dynamic content to screen readers
<div aria-live="polite" aria-atomic="true">
  {statusMessage}
</div>
```

**Semantic HTML before ARIA:**

```jsx
// ❌ ARIA role when native element exists
<div role="button" tabIndex={0}>Submit</div>

// ✅ Use native element
<button>Submit</button>

// ❌ ARIA for native functionality
<div role="navigation">...</div>

// ✅ Use native element
<nav>...</nav>
```

**Common ARIA patterns:**

```html
<!-- Modal -->
<div role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <h2 id="modal-title">Dialog Title</h2>
</div>

<!-- Tab panel -->
<div role="tablist">
  <button role="tab" aria-selected="true" aria-controls="panel1">Tab 1</button>
</div>
<div role="tabpanel" id="panel1">Content</div>

<!-- Loading state -->
<button aria-busy="true" aria-describedby="loading-text">
  <span id="loading-text" className="sr-only">Loading...</span>
</button>
```

---

## Part 7: Performance Patterns

### Virtualization

**Large lists require virtualization:**

```jsx
// Use virtualization for lists > 50 items
import { VList } from 'virtua';

function LargeList({ items }) {
  return (
    <VList style={{ height: 400 }}>
      {items.map(item => <ListItem key={item.id} item={item} />)}
    </VList>
  );
}
```

**CSS-based virtualization:**

```css
/* For simpler cases, use content-visibility */
.list-item {
  content-visibility: auto;
  contain-intrinsic-size: 0 60px; /* Estimated height */
}
```

### Layout Thrashing

**Avoid layout reads in render:**

```jsx
// ❌ Bad - forces layout recalculation
function Component() {
  const width = element.getBoundingClientRect().width; // Layout read
  element.style.width = width + 10 + 'px'; // Layout write
  const height = element.offsetHeight; // Another layout read!
}

// ✅ Good - batch reads, then writes
function Component() {
  // Batch reads
  const width = element.getBoundingClientRect().width;
  const height = element.offsetHeight;

  // Then batch writes
  requestAnimationFrame(() => {
    element.style.width = width + 10 + 'px';
    element.style.height = height + 10 + 'px';
  });
}
```

**Properties that trigger layout:**

- `offsetHeight`, `offsetWidth`, `offsetTop`, `offsetLeft`
- `getBoundingClientRect()`
- `scrollHeight`, `scrollWidth`, `scrollTop`, `scrollLeft`
- `getComputedStyle()`

### Resource Loading

**Preconnect to CDN domains:**

```html
<!-- Add in <head> for domains you'll fetch from -->
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://cdn.example.com" crossorigin />
```

**Preload critical fonts:**

```html
<link
  rel="preload"
  href="/fonts/inter-var.woff2"
  as="font"
  type="font/woff2"
  crossorigin
/>
```

**Image loading strategy:**

```jsx
// Above the fold: load immediately
<img src="/hero.jpg" fetchpriority="high" />

// Below the fold: lazy load
<img src="/card.jpg" loading="lazy" />

// Critical background images: preload
<link rel="preload" as="image" href="/hero-bg.jpg" />
```

---

## Part 8: Content & Copy

### Writing Style

**Active voice over passive:**

```
✅ "Install the CLI"
❌ "The CLI will be installed"

✅ "Your changes were saved"
❌ "Changes have been saved by the system"
```

**Title Case for headings and buttons:**

```
✅ "Save API Key"
❌ "Save api key"

✅ "Getting Started"
❌ "Getting started"
```

**Use numerals:**

```
✅ "8 deployments"
❌ "eight deployments"

✅ "3 items selected"
❌ "three items selected"
```

### Labels & Messages

**Specific labels over generic:**

```
✅ "Save API Key"
❌ "Continue"

✅ "Create Project"
❌ "Submit"

✅ "Delete Repository"
❌ "Confirm"
```

**Error messages include fix/next step:**

```
✅ "Email must include @ symbol"
❌ "Invalid email"

✅ "Password must be at least 8 characters"
❌ "Password too short"

✅ "Could not connect. Check your internet connection and try again."
❌ "Network error"
```

### Internationalization

**Use Intl APIs for formatting:**

```jsx
// ❌ Hardcoded format
const date = `${month}/${day}/${year}`;
const price = `$${amount.toFixed(2)}`;

// ✅ Locale-aware formatting
const date = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium'
}).format(new Date());

const price = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD'
}).format(amount);

// Relative time
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
rtf.format(-1, 'day'); // "yesterday"
```

---

## Part 9: Anti-Patterns Checklist

Flag these patterns during design review:

### Accessibility Violations

- [ ] `user-scalable=no` or `maximum-scale=1` in viewport meta
- [ ] `<div onClick>` instead of `<button>` for interactive elements
- [ ] Form inputs without associated labels
- [ ] Icon buttons without `aria-label`
- [ ] `outline: none` without focus replacement

### Performance Issues

- [ ] `transition: all` (animates layout properties)
- [ ] Images without explicit `width` and `height`
- [ ] Large arrays (>50 items) rendered without virtualization
- [ ] Layout reads (`getBoundingClientRect`) in render cycle

### UX Problems

- [ ] `onPaste` with `preventDefault()` (blocks paste)
- [ ] Hardcoded date/number formats (not using Intl)
- [ ] Placeholder used as label
- [ ] Validation on every keystroke
- [ ] No empty state designed

### Mobile Issues

- [ ] Touch targets smaller than 44x44px
- [ ] No `touch-action: manipulation` on buttons
- [ ] Hover effects without `@media (hover: hover)` query

### Interface Robustness Checklist

Test every interactive component against these stress conditions:

**Rapid User Input:**
- [ ] Scroll fast — does it break or show visual glitches?
- [ ] Spam click — does it trigger multiple actions or crash?
- [ ] Resize window rapidly — does layout break or cause errors?
- [ ] Type very fast in inputs — does it lag or lose characters?

**Animation Interruption:**
- [ ] Interrupt animations mid-way — does it recover gracefully?
- [ ] Close modal while opening — does it handle state correctly?
- [ ] Navigate away during transition — does it clean up properly?
- [ ] Trigger multiple animations simultaneously — do they conflict?

**Network Conditions:**
- [ ] Test with slow network (3G throttling) — does it show loading states?
- [ ] Test with offline mode — does it fail gracefully?
- [ ] Test with request timeout — does it retry or show error?

**Input Methods:**
- [ ] Test with keyboard only — is everything accessible?
- [ ] Test with screen reader — are states announced?
- [ ] Test with touch device — are hit areas adequate?
- [ ] Test with trackpad gestures — do scroll/swipe work correctly?

**State Combinations:**
- [ ] Test all combinations of loading + error + empty states
- [ ] Test disabled state during async operations
- [ ] Test hover + focus + active simultaneously
- [ ] Test with maximum and minimum content

**Memory & Performance:**
- [ ] Run for extended period — does memory grow unbounded?
- [ ] Test with large datasets — does it virtualize or paginate?
- [ ] Monitor for memory leaks in animations and observers
- [ ] Check for event listener cleanup on unmount

---

## Part 10: Design System References

### Study These Systems

**For Clarity & Precision:**

- [Linear](https://linear.app) - Information density done right
- [Stripe](https://stripe.com) - Trust through craft
- [Vercel](https://vercel.com) - Developer-focused simplicity

**For Warmth & Approachability:**

- [Airbnb](https://airbnb.com) - Friendly, image-forward
- [Notion](https://notion.so) - Flexible, playful
- [Slack](https://slack.com) - Conversational, colorful

**For Data & Density:**

- [Bloomberg Terminal](https://bloomberg.com) - Maximum information
- [Figma](https://figma.com) - Tool-like precision
- [GitHub](https://github.com) - Code-centric clarity

**For Motion & Delight:**

- [Apple](https://apple.com) - Cinematic quality
- [Framer](https://framer.com) - Motion-first

### When Generating Variants

Reference specific aspects:

- "Use Linear's density approach"
- "Stripe's button hierarchy"
- "Airbnb's card layout"
- "Notion's toggle interaction"
- "Vercel's dark mode palette"

---

## Part 11: Code Patterns Library

Practical patterns for implementing advanced interactions.

### useMotionValue vs useState

**Performance difference:**

```jsx
// ❌ Bad - triggers re-render on every frame
const [x, setX] = useState(0);
<div style={{ transform: `translateX(${x}px)` }} />

// ✅ Good - bypasses React, updates directly
const x = useMotionValue(0);
<motion.div style={{ x }} />
```

Use `useMotionValue` for:
- Continuous animation values (position, scale, opacity)
- Gesture-driven values (drag position)
- Any value that changes at 60fps

Use `useState` for:
- Discrete states (open/closed, active tab)
- Values that trigger layout changes

### useSpring: jump() vs set()

```jsx
const springValue = useSpring(0, { stiffness: 300, damping: 30 });

// set() - Animate to target value with spring physics
springValue.set(100); // Smoothly animates from current → 100

// jump() - Instantly set value, no animation
springValue.jump(100); // Immediately becomes 100

// Use jump() during drag, set() on release
const handleDrag = (e) => springValue.jump(e.clientX);
const handleRelease = () => springValue.set(snapPoint);
```

### Grid Stacking for Overlapping Elements

**Stack elements using CSS Grid (no absolute positioning):**

```jsx
// All children occupy the same grid cell
function StackedElements({ children }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr',
      gridTemplateRows: '1fr',
    }}>
      {children.map((child, i) => (
        <div key={i} style={{ gridArea: '1 / 1' }}>
          {child}
        </div>
      ))}
    </div>
  );
}
```

**Benefits over `position: absolute`:**
- Children contribute to parent size
- Natural document flow
- Better for responsive layouts

### Native Scroll vs Wheel Events

**Prefer native scroll over wheel event listeners:**

```jsx
// ❌ Bad - janky, blocks main thread
element.addEventListener('wheel', (e) => {
  scrollPosition += e.deltaY;
  element.style.transform = `translateY(${-scrollPosition}px)`;
});

// ✅ Good - smooth, GPU-accelerated
<div style={{ overflow: 'auto', scrollBehavior: 'smooth' }}>
  {content}
</div>
```

**When you need scroll position reactively:**

```jsx
// Use Intersection Observer for scroll-triggered effects
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  },
  { threshold: 0.1 }
);
```

### clip-path for Animated Resizing

**Animate size without layout shifts:**

```jsx
// ❌ Bad - animating width triggers layout
<motion.div animate={{ width: isOpen ? 300 : 0 }} />

// ✅ Good - clip-path is GPU-accelerated
<motion.div
  style={{ width: 300 }} // Fixed width
  animate={{
    clipPath: isOpen
      ? 'inset(0 0 0 0)'
      : 'inset(0 100% 0 0)' // Clip from right
  }}
/>
```

**Reveal patterns:**

```css
/* Reveal from left */
clip-path: inset(0 100% 0 0) → inset(0 0 0 0)

/* Reveal from center */
clip-path: inset(0 50% 0 50%) → inset(0 0 0 0)

/* Reveal from top */
clip-path: inset(0 0 100% 0) → inset(0 0 0 0)

/* Circle reveal from center */
clip-path: circle(0% at 50% 50%) → circle(100% at 50% 50%)
```

### Scroll Fading (Blur Fade Effect)

**Fade content at scroll edges:**

```css
.scroll-container {
  overflow-y: auto;
  mask-image: linear-gradient(
    to bottom,
    transparent 0%,
    black 10%,
    black 90%,
    transparent 100%
  );
}

/* Or use scroll-driven animations (modern browsers) */
@supports (animation-timeline: scroll()) {
  .scroll-item {
    animation: fadeIn linear both;
    animation-timeline: view();
    animation-range: entry 0% entry 20%;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
}
```

### overflow: clip vs hidden

**Use `clip` when you don't need scroll:**

```css
/* hidden: creates scroll container, may affect stacking */
.container { overflow: hidden; }

/* clip: just clips, no scroll container created */
.container { overflow: clip; }
```

**When to use each:**
- `hidden` - Need scrollable overflow (JS can scroll it)
- `clip` - Just want to hide overflow, no scroll needed (better perf)

### Re-mount with React Key for CSS Keyframes

**Replay CSS animations by changing key:**

```jsx
// CSS animation plays once on mount
function Notification({ message }) {
  const [key, setKey] = useState(0);

  const triggerAnimation = () => setKey(k => k + 1);

  return (
    <div key={key} className="animate-shake">
      {message}
    </div>
  );
}
```

```css
.animate-shake {
  animation: shake 0.5s ease-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-5px); }
  75% { transform: translateX(5px); }
}
```

### Smart Image Preloading

**Preload images before they're needed:**

```jsx
// Preload on hover (link navigation)
function NavLink({ href, children }) {
  const preloadImages = () => {
    const images = ['/hero.jpg', '/feature.png'];
    images.forEach(src => {
      const img = new Image();
      img.src = src;
    });
  };

  return (
    <Link
      href={href}
      onMouseEnter={preloadImages}
      onFocus={preloadImages}
    >
      {children}
    </Link>
  );
}

// Preload based on viewport proximity
function useImagePreload(src, rootMargin = '200px') {
  const ref = useRef(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          const img = new Image();
          img.src = src;
          observer.disconnect();
        }
      },
      { rootMargin }
    );

    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [src, rootMargin]);

  return ref;
}
```

### layoutId for Shared Element Transitions

**Morph elements between views:**

```jsx
import { motion, AnimatePresence } from 'framer-motion';

function App() {
  const [selected, setSelected] = useState(null);

  return (
    <>
      {/* Grid of cards */}
      {items.map(item => (
        <motion.div
          key={item.id}
          layoutId={`card-${item.id}`}
          onClick={() => setSelected(item)}
        >
          <Card item={item} />
        </motion.div>
      ))}

      {/* Expanded view */}
      <AnimatePresence>
        {selected && (
          <motion.div
            layoutId={`card-${selected.id}`}
            className="expanded-card"
          >
            <ExpandedCard item={selected} />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
```

### Debounced Resize Observer

**Prevent excessive callbacks during resize:**

```jsx
function useResizeObserver(ref, callback, debounceMs = 100) {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    let timeoutId;
    const observer = new ResizeObserver((entries) => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        callback(entries[0].contentRect);
      }, debounceMs);
    });

    observer.observe(element);
    return () => {
      clearTimeout(timeoutId);
      observer.disconnect();
    };
  }, [ref, callback, debounceMs]);
}
```

---

## Quick Decision Framework

When unsure, ask:

1. **Is it clear?** → User knows what to do and what happened
2. **Is it fast?** → Minimum steps, appropriate feedback
3. **Is it consistent?** → Matches patterns elsewhere in the app
4. **Is it accessible?** → Keyboard, screen reader, color contrast
5. **Is it calm?** → No unnecessary motion, color, or elements
6. **Is it specific?** → Labels describe exactly what will happen
7. **Is it recoverable?** → User can undo or go back

### Animation Decision Quick Check

```
Should this animate?
├── Used 100+ times/day? → No animation
├── Entering/exiting screen? → ease-out, 150-250ms
├── Moving on screen? → ease-in-out, 200-300ms
├── Hover/color change? → ease, 100-150ms
└── Unsure? → Start without animation, add if needed
```

### Interaction Pattern Quick Reference

| Situation | Solution |
|-----------|----------|
| Overlapping motion | Add 1-2px blur during transition |
| Menu animation | Fade-out only, no fade-in (instant appear) |
| Keyboard interactions | Often no animation needed (50ms max) |
| High-frequency updates | Skip animation if update < 100ms apart |
| Drag gesture | Use `jump()` during, `set()` at end |
| Touch gestures | Use `touch-action: none` to capture |
| Thin hit areas | Expand with `::after` pseudo-element |
| Scroll-based animation | Use native scroll, not wheel event |
| Width animation | Use `clip-path` instead of width |
| Replay CSS animation | Change React `key` prop |
| Morph between elements | Use Framer Motion `layoutId` |
| State during gesture | Track: idle → press → drag → drag-end |
| Overflow without scroll | Use `overflow: clip` |
| Exit animations | Double the spring stiffness |
| Icon swap | Crossfade with scale 0.5 + blur 7px |
| Preload data | Start on `mousedown` (before click) |
| Spring animation values | Never reuse — tune per interaction |
| React animation perf | Use `useMotionValue`, not `useState` |
