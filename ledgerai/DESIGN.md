---
name: LedgerAI
description: AI-native financial service platform for Indian businesses.
colors:
  primary: "#10b981" # Compliance Emerald (placeholder hex for emerald-500)
  neutral-bg: "#0b0f19" # Deep Charcoal / Black
  neutral-text: "#f9fafb"
---

<!-- SEED: re-run /impeccable document once there's code to capture the actual tokens and components. -->

# Design System: LedgerAI

## 1. Overview

**Creative North Star: "The Precise Emerald Sanctuary"**

LedgerAI's visual system is designed to evoke the calm, expert authority of a senior Chartered Accountant while leveraging the speed and precision of AI. It moves away from "cyber-dark" clichés (neon cyan, heavy glassmorphism) in favor of a restrained, "Linear-like" aesthetic: high-contrast typography, plenty of negative space, and a single, purposeful accent hue.

The system is built for focus. It rejects the "toy-ish" dashboard look, avoiding oversized icons and generic marketing gradients. Instead, it prioritizes a professional, data-dense but breathable layout where every pixel serves the user's financial clarity.

**Key Characteristics:**
- **Restrained & Professional**: Neutral-heavy with a single meaningful accent.
- **Breathable Density**: Data is arranged for clarity, not just volume.
- **Precision Typography**: Sharp hierarchy that honors the importance of numbers.
- **Visible Security**: Sharp edges and subtle borders convey structural integrity.

## 2. Colors

The palette is anchored in deep neutrals to provide a stable, high-trust backdrop for sensitive financial data.

### Primary
- **Compliance Emerald** (#10b981 / oklch(70.5% 0.17 160)): Used exclusively for success states, compliance confirmation, and primary calls to action. Its rarity is the point.

### Neutral
- **Deep Slate Ground** (#0b0f19): The primary canvas. A deep charcoal that avoids "pure black" to maintain depth.
- **High-Trust White** (#f9fafb): Primary text color for maximum readability.
- **Subtle Boundary** (#1f2937): Used for borders and dividers to create structure without visual noise.

### Named Rules
**The Emerald Constraint.** The primary emerald accent is used on ≤10% of any given screen. It signifies "all is well" or "take action here." Overuse erodes its meaning as a compliance signal.

## 3. Typography

**Display Font:** Inter (System fallback)
**Body Font:** Inter (System fallback)
**Label/Mono Font:** JetBrains Mono or Inter (for financial figures)

**Character:** The system uses Inter for its objective, modern, and highly legible character. Financial figures use a tabular-mono variant or a monospace font to ensure numerical alignment and a "high-precision" feel.

### Hierarchy
- **Display** (700, clamp(2rem, 5vw, 3rem), 1.1): Used for page titles and hero numbers.
- **Headline** (600, 1.5rem, 1.2): Section headers.
- **Body** (400, 1rem, 1.5): Primary content and descriptions. Max line length capped at 75ch.
- **Label** (500, 0.75rem, 1, uppercase): Metadata, table headers, and tiny signals.

### Named Rules
**The Tabular Number Rule.** All financial data and counts must use tabular-nums or a monospace font to ensure vertical alignment across tables and cards. Numbers are the product; they must be perfectly aligned.

## 4. Elevation

Depth is conveyed through tonal layering and sharp borders rather than soft, ambient shadows.

**The Linear Border Rule.** Surfaces are separated by 1px solid borders (`var(--border)`). Shadows appear only for floating elements like modals or dropdowns, using a sharp, short offset to imply "just off the page."

## 5. Components

[Components to be resolved during implementation. Seed mode: no components exist for the new design.]

## 6. Do's and Don'ts

### Do:
- **Do** use `Compliance Emerald` as a reward signal for positive financial/compliance states.
- **Do** maintain a minimum of 40px padding between major dashboard sections to ensure breathability.
- **Do** use subtle borders (1px) for card definitions.

### Don't:
- **Don't** use generic Tally-style UI patterns or "spreadsheet-as-interface" layouts.
- **Don't** use neon cyan, purple gradients, or heavy "glassmorphism" effects.
- **Don't** use "toy-ish" illustrations or overly colorful consumer-app aesthetics.
- **Don't** use modals as a first resort; prioritize inline or progressive alternatives.
