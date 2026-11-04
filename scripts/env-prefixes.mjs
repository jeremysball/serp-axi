// The shell-setting families the CLI reads. Both the hostile-env gate and the
// test helper that clears the shell import this list, so the two cannot drift:
// a provider that adds a prefix is poisoned and cleared in the same edit.
export const PREFIXES = ["SERP_AXI_", "SERPER_", "BRIGHTDATA_", "KAGI_"];
