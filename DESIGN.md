# 宇宙第一工作台 Design System

## Product Register

This is an operate-first creator workspace. The interface should help a creator move from input to review to export with low cognitive load. Visual treatment supports scanability and confidence; it does not compete with generated content.

## Visual Direction

Swiss utility with Apple-like restraint: an off-white canvas, a quiet sidebar, one blue action color, and black primary actions. Surfaces are separated by proximity, spacing, and one-pixel rules. Cards are reserved for forms, results, settings, and repeated content that needs framing.

## Tokens

- Canvas: `#f7f8fa`
- Sidebar: `#fbfbfc`
- Surface: `#ffffff`
- Soft surface: `#f1f3f6`
- Ink: `#16181d`
- Muted text: `#69717d`
- Rule: `#e1e5ea`
- Action blue: `#1677ff`
- Success green: `#198754`
- Radius: 8px controls, 10px work surfaces
- Elevation: `0 14px 35px rgba(28, 36, 48, .055)` for primary work surfaces only

## Type and Spacing

Use the system sans stack with SF Pro / PingFang fallbacks. Body copy is 14-16px with 1.6-1.8 line-height. Page titles are 28-30px, section titles 16-18px, labels 11-13px. Use a 4px base rhythm with 8, 12, 16, 24, 32px intervals. Avoid negative tracking beyond `-0.04em`.

## Component Rules

- Sidebar: 216px desktop, single active row, blue inset marker.
- Header: 72px desktop, centered command search, API state at the right.
- Workspace: one primary form/result relationship; no decorative nested card walls.
- Primary action: black, 8px radius, white text, explicit verb.
- Secondary action: white surface with a one-pixel rule.
- Focus: blue border plus a soft three-pixel ring.
- Feedback: loading, empty, error, success, and disabled states must remain visible.
- Mobile: collapse to a bottom navigation, one-column forms, and preserve the primary action near the content it controls.

## Interaction Path

Arrival -> choose a workspace -> enter the minimum input -> generate -> review result -> export or continue. Each Tab keeps this path while adapting its labels and result view to the underlying function.
