# ADR-0003: MirrorRepository as `typing.Protocol` (not ABC)

**Status**: Accepted  
**Date**: 2026-11-14  
**Phase**: A

## Context

`sync.consume_event` must write to a mirror of Organization/Group/Membership data. The
concrete implementation (Django ORM models) lives in Phase B's optional `amt-auth[django]`
extra. The core library must define the contract without importing Django.

## Options considered

| Option | Trade-off |
|---|---|
| Abstract Base Class (`abc.ABC`) | Requires explicit `class DjangoRepo(MirrorRepository)` inheritance — couples Django models to the core |
| `typing.Protocol` | Structural subtyping — any class with the right methods satisfies the protocol without inheriting from it |

## Decision

Define `MirrorRepository` as a `typing.Protocol` with `runtime_checkable=True`.

## Consequences

- **Zero coupling**: Django models in Phase B satisfy the protocol by simply implementing
  the required methods. No `import amt_auth` in model definitions.
- **Testability in Phase A**: tests supply a `MagicMock(spec=MirrorRepository)` without
  any Django installed.
- **Static analysis**: mypy/pyright will verify that Phase B's concrete repo class
  structurally satisfies `MirrorRepository` at type-check time.
- **Runtime checks**: `isinstance(repo, MirrorRepository)` works at runtime for
  defensive assertions if needed (requires `@runtime_checkable`).
- Protocols do not enforce method signatures at runtime — only static type checkers catch
  mismatches. Adequate for a library consumed by known, in-house backends.
