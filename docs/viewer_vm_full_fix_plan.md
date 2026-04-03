# Viewer VM Deployment Full Fix Plan

## Context

The current panel app initializes the Neuroglancer widget with no source and later mutates `viewer.url`.

On local development this may appear to work because loopback addresses resolve to the same machine as the browser. In VM deployments, browser and app run on different machines, so loopback assumptions can produce broken iframe loads.

## Immediate Mitigation (Applied Now)

- Initialize viewer with a known public Neuroglancer URL at startup.
- Seed the latest URL display with that same URL.

This avoids starting in an empty/local mode and provides a stable, externally reachable default for VM users.

## Target Architecture (Future Full Fix)

Move from a single long-lived viewer instance to a replaceable viewer lifecycle.

### 1. Introduce Viewer Container + Factory

- Add a container component that holds exactly one active Neuroglancer widget.
- Add a factory/helper such as `set_viewer(url: str)` that:
  - creates `Neuroglancer(source=url)`
  - registers watchers on the new widget
  - swaps the container content atomically
  - updates global/current viewer references used by callbacks

### 2. Replace URL Mutation with Widget Replacement

For app-initiated loads (state load, row link click, open latest, auto-load), create/replace the widget instead of setting `.url` on a widget that was created empty.

### 3. Preserve Existing Sync Semantics

- Keep current debounce behavior for user-driven URL changes.
- Keep programmatic-load guard behavior to avoid feedback loops.
- Keep pointer expansion behavior; only switch where final URL application happens.

### 4. Add URL Safety Validation

Before loading into viewer:

- detect loopback hosts (`127.0.0.1`, `localhost`, `::1`)
- if app is accessed remotely, warn and reject loopback viewer sources
- surface clear user-visible status explaining why URL was not loaded

### 5. Improve Observability

Add structured debug logs for:

- requested viewer URL host
- canonical/expanded URL host after pointer expansion
- whether load path was user-driven or programmatic
- whether widget was replaced or URL-updated

### 6. Regression and Deployment Test Plan

Functional checks:

- local: startup, open latest, row View actions, auto-load on mutation
- VM/remote browser: public URL load in iframe, no loopback fallback
- pointer URLs: expand and load correctly
- settings sync: default and loaded settings still mirrored in UI controls

Non-functional checks:

- no duplicate watcher registration after repeated loads
- no memory growth from orphaned viewer instances
- stable behavior under rapid user navigation (debounced)

## Rollout Plan

### Phase A (Done)

- Apply startup demo URL mitigation.

### Phase B

- Implement viewer container/factory and route all programmatic loads through replacement path.

### Phase C

- Add loopback safety checks and improved status messaging.

### Phase D

- Add tests and deployment checklist updates.

## Risks and Mitigations

- Risk: Duplicate callbacks after viewer replacement.
  - Mitigation: Register watchers only on the active instance and avoid retaining references to old widgets.
- Risk: Behavior drift in state-sync path.
  - Mitigation: Keep debounce/programmatic logic unchanged in Phase B, only changing URL application mechanism.
- Risk: Unexpected UX change in auto-load flow.
  - Mitigation: Preserve current settings and status text semantics during migration.

## Success Criteria

- VM users consistently see externally reachable Neuroglancer content in iframe.
- No implicit loopback dependency in initial viewer load path.
- Existing chat/state/query workflows continue to work without regression.
