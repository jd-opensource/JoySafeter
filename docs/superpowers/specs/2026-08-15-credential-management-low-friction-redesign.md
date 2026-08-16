# Credential Management Low-Friction Redesign

Date: 2026-08-15
Status: Approved for implementation
Scope: `/managed/credentials?tab=models|services|mcp`

## Goal

Reduce the cognitive and interaction cost of managing model connections,
service credentials, and MCP credential vaults without changing backend APIs,
credential identity, lifecycle rules, or canonical routes.

## User Mental Model

Users arrive with one of three tasks:

- connect a model provider for an agent;
- store authentication material for an environment's external service;
- create an MCP credential vault and add MCP server credentials to it.

The page must use those task terms consistently. Users must not need to
understand the internal secret/credential/vault implementation before acting.

## Design Principles

- One visible primary action per tab.
- Search is always visible; low-frequency filters are progressively disclosed.
- Resource name is the primary identifier; public ID is supporting information.
- Normal status is visible but quiet; archived status receives stronger emphasis.
- Common layout and interaction stay identical across all three tabs.
- Type-specific columns remain honest; do not invent metadata to fill space.
- Destructive lifecycle actions stay in row/detail menus and confirmation dialogs.
- Deep links, per-tab state, read-only behavior, and lifecycle capabilities remain intact.

## Page Structure

1. Existing page title and concise subtitle.
2. Route-backed tabs immediately below the header.
3. One bordered resource panel containing:
   - search;
   - a compact filter menu;
   - the tab-specific create action;
   - active filter chips;
   - desktop table or mobile cards;
   - one consistent pagination footer.

The generic page-level `New` action and the per-list duplicate action must be
replaced by one tab-specific action:

- `New model connection`
- `New service credential`
- `New MCP credential vault`

The generic kind chooser remains available for external callers/tests that need
it, but is no longer the normal page entry point.

## Search and Filters

Search updates immediately and resets the active cursor page. Each tab preserves
its own search, created-time filter, archived visibility, and page size while the
list unmounts.

The default toolbar exposes only search, filters, and create. The filter menu
contains:

- created time: all, last 7 days, last 30 days, last 90 days;
- include archived resources.

An active filter count appears on the filter button. Active filters render below
the toolbar as removable chips with a clear-all action.

## Resource Identity

All lists use a shared identity cell/card:

- resource name first;
- optional secondary description, such as model name;
- truncated canonical public ID with copy action;
- default and lifecycle badges adjacent to the name.

The ID must never own the first standalone column. Copy controls and action menus
must stop row navigation.

## Type-Specific Lists

### Model Connections

Desktop columns:

- identity: name, model name, public ID, default/lifecycle badges;
- provider and protocol;
- compatible engines;
- created time;
- actions.

### Service Credentials

Desktop columns:

- identity: name, public ID, lifecycle badge;
- created time;
- actions.

Do not expose secret key names or values in the list.

### MCP Credential Vaults

Desktop columns:

- identity: name, public ID, lifecycle badge;
- created time;
- actions.

The two-stage domain flow remains: creating a vault navigates to its detail route
with `?add=1`, where the first member credential can be added.

## Empty States

Differentiate:

- truly empty collection: explain the resource purpose and show the sole create
  action when writable;
- no search/filter match: explain that no match was found and offer clear filters;
- active collection empty while archived resources are hidden: offer to include
  archived resources.

Read-only projects never render write CTAs.

## Responsive Behavior

- Desktop: compact table inside the resource panel.
- Tablet: type-specific secondary information may wrap within existing columns.
- Mobile: stacked resource cards replace the table; search occupies the first row
  and filter/create actions occupy the second row.

All clickable rows/cards support keyboard activation. Nested copy/menu controls
must not trigger navigation.

## Compatibility and Constraints

- Preserve canonical routes and `create=model|service|vault` deep links.
- Preserve independent query/error boundaries and server-side kind filtering.
- Preserve all lifecycle actions currently covered by parity tests.
- Preserve project/scope stale-action guards.
- Do not add backend requests solely for counts or decoration.
- Do not add a new UI dependency when existing Radix/shadcn primitives suffice.
- Keep the existing neutral visual language and semantic design tokens.

## Dialectical Assessment of the Existing Implementation

The current implementation should not be treated as a failed design. It already
solves several difficult correctness problems that the redesign must preserve:

- URL-backed tabs provide linkability, browser history, and predictable back
  navigation.
- Each tab owns independent search, archived visibility, page size, cursor, query
  key, and error boundary.
- Model/service filtering happens server-side before cursor pagination.
- `create=*` deep links are consumed once and remain compatible with callers from
  agent, environment, and session workflows.
- Project read-only checks and managed-scope stale-action guards prevent unsafe
  mutations after organization/project switches.
- Lifecycle actions and capability parity are protected by a substantial test
  suite.
- The shared table already supports keyboard row activation and nested action
  menus.

The redesign therefore applies a preserve-and-improve strategy:

| Preserve                           | Improve                                         |
| ---------------------------------- | ----------------------------------------------- |
| Route and query semantics          | Duplicate generic/per-tab create actions        |
| Independent tab state and requests | Disconnected header, toolbar, table, pagination |
| Lifecycle and stale-scope guards   | ID-first information hierarchy                  |
| Existing dialogs and detail routes | Permanently expanded low-frequency filters      |
| Capability parity                  | Weak empty/search/no-active differentiation     |
| Keyboard table behavior            | Mobile table compression                        |

This boundary prevents a visual refactor from accidentally weakening proven
domain behavior. Shared components are introduced only inside the credential
module; global managed tables and unrelated pages remain unchanged.

## Acceptance Criteria

- Exactly one visible create action appears on each writable tab.
- No generic type-choice step is required from the normal page flow.
- Search, filter, table/card, and pagination occupy one coherent panel.
- Names visually precede IDs across all tabs.
- Filters are collapsed by default and show active state clearly.
- Desktop and mobile layouts remain usable in Chinese and English.
- Deep links, read-only mode, per-tab state, lifecycle actions, and navigation pass
  automated tests.
- Browser QA covers models, services, MCP, filter interaction, empty state, and a
  mobile viewport.
