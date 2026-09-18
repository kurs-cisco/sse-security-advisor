# Project instructions

## FedRAMP FIPS assessment

Use `.agents/skills/fedramp-fips-assessor/SKILL.md` for FIPS 140-2 to FIPS
140-3 transition assessments, CMVP evidence review, FIPS/FedRAMP POA&M
creation or deduplication, and service-group coverage assessments based on
`SSE_CBOMS` or `cbom-catalog`.

The skill produces machine-generated **candidate** findings only. A candidate
is not an authorized assessor conclusion, an authorization decision, or proof
that a module is FIPS validated.

## Data and verification

- Treat source corpora as read-only evidence. Use the checksum-gated ingester;
  never rewrite source documents during normalization.
- Scope catalog identity by `(source_collection, service_group)` and preserve
  exact source/document SHA-256 values.
- Use `--authoritative-snapshot` only for a complete collection snapshot; a
  partial download must not mark unobserved paths historical.
- The Next.js console is the primary UI. FastAPI `/ui/` is a legacy rollback
  surface and must not be documented as the normal entry point.
- For release or handoff changes, run the API tests, console lint/typecheck/build,
  representative API checks, and browser flows in
  `cbom-catalog/docs/RELEASE_CHECKLIST.md`.
- Never commit database dumps, `.env` files, credentials, OIDC secrets, or raw
  externally shared assessment packages.

See `.agents/README.md` and
`cbom-catalog/docs/INGESTION_AND_ASSESSMENT.md` for the durable knowledge map.
