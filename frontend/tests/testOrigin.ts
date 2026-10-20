/** Isolate copied-project QA without touching the existing preview server. */
const configuredOrigin = new URL(
  process.env.VSF_TEST_BASE_URL ?? "http://127.0.0.1:6174",
);
if (
  configuredOrigin.protocol !== "http:" ||
  !["127.0.0.1", "localhost"].includes(configuredOrigin.hostname) ||
  configuredOrigin.username ||
  configuredOrigin.password ||
  configuredOrigin.pathname !== "/" ||
  configuredOrigin.search ||
  configuredOrigin.hash
) {
  throw new Error("VSF_TEST_BASE_URL must be a credential-free local HTTP origin");
}
export const testOrigin = configuredOrigin.origin;
