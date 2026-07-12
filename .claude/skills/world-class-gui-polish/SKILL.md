---
name: world-class-gui-polish
description: Use when the user asks to polish, enhance, make exciting, add wow, sparkle, improve dark/light mode, modernize, or make a GUI/front-end experience world class, including typography and font reviews for page purpose, audience, industry fit, and open-source recommendations.
---

# World-Class GUI Polish

## Purpose

Turn an existing interface into a sharper, more memorable, production-quality experience while preserving the product's real workflow. Use this skill for visual polish, UX refinement, typography and font selection, theme improvements, and "make it wow" requests.

## Operating Mode

- Implement improvements unless the user explicitly asks only for ideas.
- Read the existing frontend first: routes, components, CSS/theme tokens, design-system conventions, and tests/smokes.
- Preserve the app's domain. Operational tools should feel dense, clear, and efficient; creative tools can be more expressive.
- Keep copy functional. Do not add visible text that explains features, styling, shortcuts, or how to use the UI.

## Web-Informed Inspiration

Browse when the user asks for web suggestions, current inspiration, competitor-level quality, or "world class" design direction. Use current sources for ideas, then adapt patterns rather than copying.

Good source targets:
- Official design systems for relevant component patterns.
- Current product screenshots or docs from comparable best-in-class apps.
- Accessibility/color guidance from primary sources.
- Font foundries, open-source font repositories, and license pages.
- Domain-specific examples that match the user's app category.

When using web input:
- Cite sources in the final response.
- Extract design principles, not copyrighted layouts.
- Prefer 2-4 high-signal sources over broad trend roundups.
- Reject ideas that conflict with the app's workflow, accessibility, or performance.

## Typography and Font Review

Treat fonts as part of the product strategy, not decoration.

When polishing type:
- Identify the page purpose: operational dashboard, developer tool, creative editor, commerce, portfolio, marketing page, documentation, game, or data-heavy workspace.
- Identify the audience: technical operators, executives, consumers, creators, students, enterprise buyers, accessibility-sensitive users, or mixed groups.
- Choose typography to match the desired feel: trusted, fast, editorial, playful, premium, technical, calm, clinical, creative, or high-energy.
- Research current industry-suggested fonts for that use case when the user asks for web-informed or best-practice guidance.
- Prefer open-source fonts when feasible; verify license terms before recommending or importing a font.
- Consider variable fonts, optical sizes, tabular numbers, mono companions, language coverage, loading performance, and fallback stacks.
- Keep font count low: usually one strong UI family plus an optional display or monospace companion.
- Avoid changing fonts in isolation; update type scale, line height, weight, letter spacing, hierarchy, and control sizing together.
- Ensure numbers, labels, tables, buttons, and dense panels remain scan-friendly.

Recommended source targets for font decisions:
- Google Fonts, Fontsource, GitHub repos for the font, or official foundry pages for open-source licensing and availability.
- Design-system typography docs for the product category.
- Current high-quality products in the same domain to infer typographic conventions.

If adding web fonts:
- Use existing project conventions first.
- Prefer self-hosting or established package imports when the repo already uses them.
- Keep load cost controlled with selected weights/styles only.
- Define robust fallback stacks and test before/after layout shifts.
- Do not introduce commercial fonts unless the user has confirmed licensing.

## Polish Workflow

1. Diagnose the current UI.
   - Identify the highest-impact visual issues: contrast, spacing, typography, hierarchy, alignment, density, theme leaks, icon treatment, component states, and responsive behavior.
   - Screenshot or inspect the target screens before editing when possible.

2. Choose a design direction.
   - Define the intended mood in concrete terms: e.g. "Carbon-dark operational console", "calm SaaS command center", "editorial portfolio", or "immersive game dashboard".
   - Pick a font strategy that fits the page purpose, audience, and industry expectations.
   - Keep the palette multi-dimensional. Avoid a one-note theme dominated by one hue family.

3. Implement tightly.
   - Prefer existing tokens, components, and helper classes.
   - Add scoped overrides near related CSS so cascade intent is clear.
   - Improve real states: hover, focus, disabled, empty, loading, error, selected, active, and mobile drawer states.
   - Ensure text fits inside controls and panels at desktop and mobile sizes.
   - Avoid unrelated refactors.

4. Raise the perceived quality.
   - Establish clear hierarchy through type scale, weight, spacing, and surface contrast.
   - Audit headings, body text, labels, buttons, tables, forms, code, numbers, and empty/error states for correct font usage.
   - Use restrained motion and shadows only when they clarify layering.
   - Make primary actions obvious and secondary actions quiet.
   - Use icons where they improve scanning; keep labels where commands need clarity.
   - Use real assets or generated imagery when the experience depends on visual richness.

5. Verify visually and technically.
   - Run the app/build tests appropriate to the repo.
   - Use browser screenshots for at least one desktop and one mobile viewport when layout or styling changes are meaningful.
   - Check for horizontal overflow, overlapping text, unreadable contrast, blank assets, and broken focus states.
   - Rebuild generated frontend artifacts if the repo tracks them.

## Final Response

Keep the close-out short and concrete:
- What changed and where.
- What was verified.
- Any remaining limitation.
- Web sources used, if browsing informed the work.
