# AGENTS.md

## Project Overview

This project is a small web application for managing a weekend competition/gymkhana between a group of friends.

The competition consists of:

- 10 participants.
- 2 teams of 5 participants.
- Multiple challenges played over approximately 3 days.
- Individual challenges.
- Team challenges.
- Hybrid challenges that may contribute to both individual and team scoring.
- An overall individual leaderboard.
- A team leaderboard.
- Statistics and charts showing competition progress.
- Two final individual winners.

The application is intended for private use during a single weekend.

It is not a commercial product, SaaS platform, or multi-tenant application.

Keep the project intentionally simple.

Priority order:

1. Reliability of competition data.
2. Good mobile experience.
3. Simplicity.
4. Fast development.
5. Easy administration.
6. Maintainability.
7. Minimal infrastructure.

Avoid overengineering.

---

## Language

The user-facing application must be in Spanish.

This includes:

- Navigation.
- Buttons.
- Labels.
- Forms.
- Validation messages.
- Empty states.
- Error messages.
- Statistics.
- Leaderboards.
- Challenge information.
- Admin UI.

Code, identifiers, comments, documentation, database field names, and technical terminology should generally remain in English unless the existing codebase establishes another convention.

---

## Users

There are two conceptual access levels.

### Participants

Participants access the application from their mobile browsers.

They primarily have read-only access.

They may view information such as:

- Individual leaderboard.
- Team leaderboard.
- Participants.
- Teams.
- Challenges.
- Results.
- Scores.
- Statistics.
- Charts.
- Competition progress.

Participants should not require individual accounts unless explicitly requested by a future task.

### Administrator

There is a single administrator.

The administrator manages the competition through a protected admin area.

The admin may need to manage:

- Participants.
- Teams.
- Challenges.
- Matches.
- Results.
- Scores.
- Bonuses.
- Penalties.
- Challenge status.
- Manual corrections.

Do not introduce complex role or permission systems unless explicitly requested.

The intended permission model is:

- Public or participant-facing read access.
- Protected administrator write access.

---

## Product Principles

The application is designed for a very small number of users.

Do not optimize for hypothetical large-scale usage.

Prefer simple solutions over highly abstract or enterprise-oriented architectures.

Avoid introducing infrastructure such as:

- Microservices.
- Message queues.
- Distributed event systems.
- Kubernetes.
- Redis.
- Multiple databases.
- CQRS.
- Complex RBAC.
- Multi-tenant architecture.
- Enterprise identity systems.

A simple monolithic or integrated full-stack architecture is preferred when compatible with the existing stack.

---

## Core Domain

The main domain concepts are described below.

Exact implementation details should follow the existing codebase.

### Participant

Represents one competitor.

Typical information may include:

- ID.
- Name.
- Nickname.
- Avatar.
- Team.
- Derived statistics.

Avoid storing duplicated derived values when they can be safely calculated from canonical competition data.

### Team

Represents one of the two teams.

Each team contains five participants.

A team may have:

- ID.
- Name.
- Visual identity.
- Members.
- Derived score.
- Derived statistics.

### Challenge

Represents one competition activity.

A challenge may be:

- Individual.
- Team-based.
- Hybrid.

Possible challenge metadata may include:

- Name.
- Description.
- Type.
- Status.
- Order.
- Day or phase.
- Scoring configuration.

Do not assume every challenge uses the same scoring system.

Challenge-specific rules will normally be provided in task prompts.

### Match

Some challenges may contain direct matchups.

Examples include:

- Participant vs participant.
- Team vs team.
- Tournament rounds.

A match may track:

- Challenge.
- Participants or teams.
- Round.
- Score.
- Winner.
- Status.

### Result

Represents the outcome of a challenge or match.

A result may reference:

- Participant.
- Team.
- Challenge.
- Match.
- Position.
- Raw result.
- Score awarded.
- Win/loss status.
- Notes.

### Score Event

If the architecture supports it, score changes may be represented as explicit events.

Examples:

- Challenge points.
- Bonus points.
- Penalties.
- Manual corrections.

An event-based score model is useful when it improves traceability and prevents inconsistent duplicated totals.

Do not introduce it if the existing architecture uses a simpler adequate approach.

---

## Scoring

Scoring is a core part of the application.

Different challenges may use different scoring rules.

Do not hardcode challenge-specific scoring logic inside generic UI components.

Prefer keeping scoring logic:

- Centralized.
- Testable.
- Independent from presentation code.
- Easy to modify.
- Consistent across leaderboards and statistics.

The individual leaderboard and team leaderboard must derive from authoritative competition data.

Avoid maintaining multiple independent sources of truth for totals.

Future prompts will define specific scoring rules for individual challenges.

Do not invent missing competition rules.

---

## Leaderboards

The application must support two main rankings.

### Individual Leaderboard

Ranks all 10 participants according to the competition scoring rules.

This is one of the primary views of the application.

### Team Leaderboard

Compares the two teams according to the competition rules.

Keep leaderboard calculation separate from presentation whenever practical.

---

## Statistics and Charts

The application should provide useful visual feedback about the competition.

Possible statistics include:

- Total points.
- Wins.
- Losses.
- Challenges won.
- Points per challenge.
- Contribution to team score.
- Distance from the leader.
- Ranking evolution.

Possible charts include:

- Individual score evolution.
- Team score evolution.
- Points by challenge.
- Participant comparison.
- Team comparison.

Only implement statistics explicitly requested by the current task or already present in the codebase.

Charts must remain readable on mobile devices.

Avoid adding heavy charting dependencies if the existing stack already provides an adequate solution.

---

## Mobile-First UX

The primary client is a smartphone browser.

Design and implementation should therefore be mobile-first.

Prioritize:

- Fast access to leaderboards.
- Clear hierarchy.
- Large touch targets.
- Responsive layouts.
- Readable typography.
- Charts that work on narrow screens.
- Minimal horizontal scrolling.
- Fast page loads.
- Simple navigation.

Desktop support is useful but secondary.

The visual style may be informal and playful, while the implementation should remain clean and maintainable.

---

## Public Application

The participant-facing application is primarily read-only.

Public views should make it easy to quickly inspect:

- Current leaderboard.
- Team standings.
- Latest results.
- Challenges.
- Participant statistics.
- Competition progress.

Do not expose administrative controls in public interfaces.

Do not rely solely on hiding UI elements for authorization.

Write operations must also be protected server-side.

---

## Admin Area

The application should contain a dedicated administration area.

Prefer a simple protected route such as `/admin` or the equivalent convention used by the framework.

The admin UI should prioritize speed of use during the event.

Prefer:

- Simple forms.
- Fast result entry.
- Clear correction workflows.
- Obvious challenge status controls.
- Confirmation for destructive operations.

Avoid unnecessary dashboards or enterprise-style interfaces.

The administrator should not need direct database access during normal use.

---

## Authentication

Authentication exists mainly to prevent participants from modifying competition data.

Keep authentication simple.

Do not introduce unnecessary systems such as:

- OAuth providers.
- Organizations.
- Multiple user roles.
- Advanced identity management.

Administrator credentials and secrets must never be exposed to client-side code.

Use environment variables or the platform's secret management mechanism.

Authorization must be enforced on the server for every write operation.

---

## Persistence

Competition data must be persistent.

Do not use process memory, browser storage, or temporary files as the authoritative data store.

Competition state must survive:

- Application restarts.
- Access from multiple devices.
- Normal deployments.

Use the existing database and persistence patterns in the repository.

The database should be the authoritative source for competition state.

Be particularly careful with:

- Results.
- Scores.
- Bonuses.
- Penalties.
- Manual corrections.

Avoid workflows that can accidentally apply the same scoring change twice.

---

## Data Integrity

Although the application is small, competition results matter during the event.

Prefer:

- Server-side validation.
- Stable IDs.
- Atomic updates where appropriate.
- Database transactions when multiple dependent writes must succeed together.
- Clear constraints.
- Safe correction workflows.

Avoid destructive operations when a reversible update is practical.

Do not add complex audit infrastructure unless explicitly requested.

---

## Architecture

Follow the architecture already present in the repository.

Prefer a simple flow such as:

`Browser -> Application -> Server/Data Layer -> Database`

Keep responsibilities reasonably separated between:

- Presentation.
- Domain logic.
- Data access.
- Authentication.
- Persistence.

Do not create additional architectural layers without a concrete benefit.

---

## State Management

Prefer server-backed state for persistent competition data.

Client-side state should primarily represent temporary UI state.

Do not maintain authoritative competition totals exclusively on the client.

When derived data can be calculated reliably from persisted data, prefer deriving it instead of manually synchronizing multiple copies.

---

## API and Mutations

Follow the framework's existing pattern for server communication.

All write operations must:

- Validate input.
- Require administrator authorization.
- Persist changes before reporting success.
- Return clear errors.
- Avoid exposing secrets or internal credentials.

Keep mutation logic outside purely presentational components.

---

## Error Handling

Errors shown to users must be understandable and written in Spanish.

Technical logs may remain in English.

Do not expose:

- Stack traces.
- Secrets.
- Database connection strings.
- Internal tokens.
- Sensitive environment values.

Admin operations should fail clearly rather than silently.

---

## Environment Variables

Keep secrets and deployment-specific values outside source code.

Typical environment configuration may include:

- Database connection.
- Admin authentication secrets.
- Application URL.
- External service credentials.

Never commit real production credentials.

Document environment variable names when necessary, but never include real secret values in documentation.

---

## Deployment

The application is intended to be publicly accessible through a normal HTTPS URL during the event.

Expected traffic is extremely small.

Optimize deployment for:

- Simplicity.
- Reliability.
- Low cost.
- Easy environment configuration.
- Persistent database support.
- Fast redeployment.

Do not introduce infrastructure intended for large-scale traffic unless explicitly required.

---

## Development Workflow

Before changing code:

1. Inspect the relevant existing implementation.
2. Identify current project conventions.
3. Understand the affected data flow.
4. Check whether similar functionality already exists.
5. Reuse existing abstractions where appropriate.

After changing code, run the relevant checks available in the repository.

These may include:

- Formatting.
- Linting.
- Type checking.
- Unit tests.
- Integration tests.
- Production build.

Do not invent commands. Use the scripts defined by the project.

---

## Coding Guidelines

Follow existing repository conventions.

General rules:

- Prefer simple, readable code.
- Keep functions focused.
- Avoid unnecessary abstractions.
- Avoid premature optimization.
- Reuse existing components and utilities.
- Prefer explicit behavior over clever code.
- Keep domain logic out of purely visual components.
- Avoid unrelated refactors.
- Avoid adding dependencies unless necessary.
- Preserve existing public interfaces unless the task requires changing them.
- Keep changes scoped to the requested task.

When multiple valid implementations exist, prefer the simplest one consistent with the existing architecture.

---

## UI Guidelines

All visible application copy must be in Spanish.

Prefer reusable UI components when repetition is meaningful.

Keep the interface practical for real-time use during the competition.

For participant-facing pages, prioritize viewing information.

For admin-facing pages, prioritize entering and correcting information quickly.

Do not sacrifice usability for decorative complexity.

---

## Testing

Important domain logic should be testable independently of UI components.

Prioritize tests around logic such as:

- Score calculation.
- Ranking calculation.
- Team aggregation.
- Result updates.
- Bonus and penalty handling.
- Authorization for mutations.

Follow the test framework and conventions already present in the repository.

Do not introduce a new testing framework without a strong reason.

---

## Security

This is a small private application, but normal web security practices still apply.

At minimum:

- Protect all write operations.
- Validate untrusted input.
- Keep secrets server-side.
- Do not trust client-provided authorization state.
- Do not expose database credentials.
- Avoid unsafe dynamic code execution.
- Use the security mechanisms provided by the chosen framework and platform.

Do not build complex security infrastructure beyond the needs of the project.

---

## Performance

Expected usage is small.

Prefer correctness and simplicity over aggressive optimization.

Avoid obvious inefficiencies such as unnecessary repeated database queries or excessive client-side payloads, but do not introduce caching infrastructure without a concrete need.

---

## Agent Guidelines

When working on this repository:

- Read relevant code before making changes.
- Follow existing patterns.
- Treat this file as global project context, not as a feature specification.
- Follow the current user prompt for feature-specific requirements.
- Do not invent missing product requirements.
- Do not invent challenge rules.
- Do not assume all challenges share the same scoring system.
- Keep scoring logic centralized when practical.
- Keep persistent competition state server-backed.
- Protect every write operation.
- Preserve mobile usability.
- Keep all user-facing text in Spanish.
- Keep technical code and naming in English unless existing conventions differ.
- Prefer existing abstractions over parallel implementations.
- Avoid unrelated refactors.
- Avoid unnecessary dependencies.
- Avoid infrastructure for hypothetical future scale.
- Keep changes small and focused.
- Update database migrations when persistent models change.
- Verify leaderboard and statistics behavior when modifying scoring logic.
- Run relevant project checks after changes.
- Never expose secrets.
- Never commit credentials.
- Do not modify unrelated files unless required for the task.

## Scope of Future Prompts

This file intentionally does not define detailed rules for specific challenges.

Future prompts may specify things such as:

- Challenge formats.
- Scoring formulas.
- Tournament structures.
- Bonuses.
- Penalties.
- Admin workflows.
- Statistics.
- Charts.
- UI changes.

Those instructions should be implemented within the architectural and product constraints described here.