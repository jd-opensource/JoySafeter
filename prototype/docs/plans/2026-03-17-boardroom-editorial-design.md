# Boardroom Editorial UI Redesign

**Date:** 2026-03-17

## Objective

Refactor the JoySafeter frontend into a boardroom-grade enterprise interface for senior executives and enterprise buyers while keeping all existing functionality and interaction flows intact.

## Design Direction

The product should feel like an executive briefing system rather than an AI demo. The interface should communicate trust, control, and operational clarity through restrained typography, disciplined spacing, and a consistent material system.

## Core Principles

1. Low noise over visual novelty
2. Structural clarity over decorative effects
3. Trust and seriousness over startup energy
4. Consistency across dashboards, chat, settings, and builders
5. UI-only changes with no functional regression

## Visual Language

### Palette

- Backgrounds move to warm off-white, parchment gray, and graphite-tinted neutrals
- Primary emphasis uses deep ink blue instead of violet gradients
- Semantic states remain clear but become less saturated and more institutional
- Borders and dividers provide hierarchy before shadows do

### Typography

- Use the existing local `Soehne` family for the primary interface voice
- Preserve mono typography only for code, logs, and technical readouts
- Increase contrast in title hierarchy and reduce marketing-style headline treatment

### Components

- Replace glassmorphism and glow with document-like panels
- Reduce rounded corners across buttons, cards, and form controls
- Use thin borders, subtle elevation, and structured spacing
- Make pills, badges, and toggles quieter and more functional

### Motion

- Remove buoyant hover movement and glow feedback
- Keep only quiet opacity, translate, and collapse transitions
- Motion should support orientation, not entertainment

## Page Family Guidance

### Global Shell

- Sidebar becomes more architectural and less playful
- Main content reads like briefing pages with a fixed rhythm
- Top-level shells use stronger sectional framing and clearer page headers

### Auth

- Remove particles and startup-style promotional atmosphere
- Use an executive landing composition: concise brand narrative on the left, disciplined sign-in card on the right
- Treat auth as a premium product entry point, not a marketing splash

### Dashboard and List Pages

- Convert bento-style cards into executive summary modules
- Make KPIs read like operational briefings
- Normalize filters, toolbars, tables, and status chips

### Copilot and Chat

- Shift to a high-trust workstation aesthetic
- Reduce toy-like UI accents in threads, composer, and tool panels
- Tighten hierarchy between conversation, context, and execution metadata

### Settings and Configuration

- Unify dialogs, forms, provider cards, and control surfaces
- Use clearer section framing for setup-heavy screens

### Builder and Workspace

- Keep canvas behavior unchanged
- Modernize surrounding panels, toolbars, drawers, and status components so advanced surfaces still fit the executive system

## Non-Goals

- No changes to routes, state, APIs, or data flow
- No copy overhaul beyond small UI labels required for hierarchy
- No redesign of product functionality

## Success Criteria

- The interface no longer reads as a violet-gradient AI prototype
- Shared tokens and components provide a coherent visual language across the app
- Primary high-traffic surfaces follow the same executive-grade system
- Build, type-check, and lint continue to work after the refactor
