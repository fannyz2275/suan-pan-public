export default async function globalTeardown() {
  // Re-seed to tear down eval rows. Seed.apply() is idempotent (upsert),
  // so a second apply doesn't duplicate data — this just leaves the fixture
  // in a known state for the next run. A full truncate of eval users is
  // outside scope for Phase 1 since we don't want to accidentally wipe
  // the real DB; that belongs to a dedicated teardown fixture.
  // For now, we just log completion.
  console.log('[globalTeardown] Spec A run complete.');
}
