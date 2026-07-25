# Architecture Decision Records

One file per significant, hard-to-reverse decision — not every decision, only the ones where
a future contributor (including you) would reasonably ask "why is it built this way instead
of the obvious alternative." Numbered sequentially, never renumbered or deleted; a reversed
decision gets a new ADR that supersedes the old one, with the old one marked
`Status: Superseded by 000X`.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-multi-tenancy.md) | Tenant-ready schema, solo-first product | Accepted |
| [0002](0002-task-queue.md) | Arq over Celery for background jobs | Accepted |
| [0003](0003-agent-orchestration.md) | Agents communicate through data, never direct calls | Partially superseded by 0006 |
| [0004](0004-llm-provider-abstraction.md) | Claude primary, OpenAI secondary, behind one provider interface | Accepted |
| [0005](0005-first-plugin-reddit.md) | Reddit as the first plugin implemented | Accepted |
| [0006](0006-event-driven-agent-communication.md) | Event-driven agent communication via transactional outbox + Arq dispatch | Accepted — supersedes 0003's mechanism |
| [0007](0007-plugin-discovery-and-interface-segmentation.md) | Manifest-based plugin discovery and segmented capability interfaces | Accepted |
| [0008](0008-plugin-contributed-content-types.md) | Plugin-contributed content types, not a closed database enum | Accepted |
| [0009](0009-plugin-config-schema-dynamic-ui.md) | Plugin-declared config schema, rendered by one generic frontend form | Accepted |
| [0010](0010-envelope-encryption-for-credentials.md) | Envelope encryption for plugin credentials | Accepted |

0006–0010 came out of the Principal Engineer design review in
[`docs/reviews/DESIGN_REVIEW.md`](../reviews/DESIGN_REVIEW.md) — see `ARCHITECTURE.md`
(the canonical Version 2 design these ADRs are now merged into) for how they fit together and
[`docs/architecture/LOCKED_DECISIONS.md`](../architecture/LOCKED_DECISIONS.md) for the full
locked/flexible split going into implementation.
