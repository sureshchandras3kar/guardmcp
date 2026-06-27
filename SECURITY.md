# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in GuardMCP, please report it
**privately**. Email `security@example.com` (note: maintainer should replace
this placeholder with a real, monitored address before publishing).

Please **do not open a public GitHub issue** for security vulnerabilities, as
this may expose other users to risk before a fix is available.

When reporting, include enough detail to reproduce the issue (affected version,
policy configuration, request payload, and observed vs. expected behavior).

What to expect:

- **Acknowledgement** within **48 hours** of your report.
- A **90-day disclosure window**: we aim to ship a fix and coordinate public
  disclosure within 90 days of acknowledgement. We will keep you updated on
  progress and will credit you (if you wish) once a fix is released.

## Supported Versions

| Version | Supported          | Notes        |
| ------- | ------------------ | ------------ |
| 0.1.x   | :white_check_mark: | Alpha        |

## Security Model

GuardMCP is a **policy enforcement layer** that sits between an AI/MCP client
and a MongoDB deployment. Every request is evaluated against an agent policy
before it reaches the database, and responses are masked on the way back. Its
security guarantees depend **entirely on correct policy configuration**: the
layer can only enforce what the policy expresses. A permissive policy provides
little protection — for example, leaving `collections.allow` empty means *all*
collections are reachable, and omitting `mask_fields` means no values are
redacted. Treat policy authoring as a security-critical task and review it
accordingly.

## Known Limitations

GuardMCP is **alpha** software. The following limitations are known and should
be understood before relying on it in any sensitive context:

- **Aggregation field masking is enforced by denial.** Any aggregation pipeline
  that references a masked field path (e.g. `$email`) is **denied** outright.
  This prevents pipelines from renaming or aliasing a masked field to bypass
  masking, but it also means some *legitimate* aggregations that touch a masked
  field are blocked.
- **`$match` on masked fields enables oracle attacks.** Filtering on a masked
  field (e.g. `{ssn: "123-45-6789"}`) is permitted, and observing the resulting
  document/result counts can leak whether a guessed value exists. Mask-and-filter
  is **not** fully prevented — masking hides values in output, not in predicates.
- **`explain` output is not masked.** Query plans returned by `explain` may
  reveal field names and the literal filter values embedded in the plan. If this
  matters, restrict the `explain` action via policy.
- **ObjectId coercion is heuristic.** Any 24-character lowercase hex string in a
  filter is coerced to an `ObjectId`. Collections that legitimately store
  24-hex strings as plain strings may see unexpected empty results.
- **Audit log integrity is opt-in.** The HMAC hash chain that protects the audit
  log against tampering is only enabled when `GUARDMCP_AUDIT_HMAC_SECRET` is set.
  Without it, audit entries are not integrity-protected.
- **Rate limiting is in-memory and per-process.** Limits are tracked within a
  single GuardMCP process and do **not** coordinate across multiple instances.
  A horizontally scaled deployment can exceed intended global limits.
- **Load/concurrency behavior is untested.** Behavior under high request volume
  or heavy concurrency has not been formally tested or benchmarked.

## Hardening Checklist

For any production or sensitive deployment:

- [ ] Set `GUARDMCP_APPROVAL_API_TOKEN` to protect the approval API.
- [ ] Set `GUARDMCP_AUDIT_HMAC_SECRET` to enable audit log integrity (HMAC chain).
- [ ] Use an explicit `collections.allow` list — **never leave it empty** (empty
      means all collections are allowed).
- [ ] Enable `approval.high` and `approval.critical` so high-risk operations
      require human approval.
- [ ] Restrict the `explain` and `aggregate` actions for untrusted agents
      (explain output is unmasked; aggregation can reach masked fields).
- [ ] Run GuardMCP behind network isolation (it is not a public-facing service).
