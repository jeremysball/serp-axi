import { SerpAxiError } from "./errors.ts";
import { searchSerper, type SearchParams, type SearchResponse } from "./serper.ts";
import { searchBrightData, BRIGHT_DATA_DEFAULT_ZONE } from "./brightdata.ts";
import { searchKagi } from "./kagi.ts";
import { searchSearxng, type SearxngOptions, type SearxngSearchResponse } from "./searxng.ts";

export const PROVIDERS = ["serper", "brightdata", "kagi", "searxng"] as const;
export type Provider = (typeof PROVIDERS)[number];

export type SearchStrategyResult = SearchResponse | SearxngSearchResponse;

export interface SearchStrategyContext {
  params: SearchParams;
  fetchImpl: typeof fetch;
  zone?: string;
  searxng?: SearxngOptions;
}

export interface SearchStrategy {
  run(context: SearchStrategyContext): Promise<SearchStrategyResult>;
}

function requireEnv(name: string, help: string): string {
  const value = process.env[name];
  if (!value) throw new SerpAxiError(`${name} is not set`, "runtime", help);
  return value;
}

export const searchStrategies: Record<Provider, SearchStrategy> = {
  serper: {
    run(context) {
      return searchSerper(requireEnv("SERPER_API_KEY", "export SERPER_API_KEY=<your key> and re-run"), context.params, context.fetchImpl);
    },
  },
  brightdata: {
    run(context) {
      const apiKey = requireEnv(
        "BRIGHTDATA_API_KEY",
        "export BRIGHTDATA_API_KEY=<your key> and re-run",
      );
      const zone = context.zone || process.env.BRIGHTDATA_ZONE || BRIGHT_DATA_DEFAULT_ZONE;
      return searchBrightData(apiKey, context.params, context.fetchImpl, zone);
    },
  },
  kagi: {
    run(context) {
      return searchKagi(
        requireEnv("KAGI_SESSION_TOKEN", "export KAGI_SESSION_TOKEN=<your token> and re-run; get the token from kagi.com/settings?p=user_details"),
        context.params,
        context.fetchImpl,
      );
    },
  },
  searxng: {
    run(context) {
      if (context.searxng === undefined) {
        throw new SerpAxiError("internal error: searxng options were not resolved", "runtime", "report it if it persists");
      }
      return searchSearxng(context.searxng, context.params, context.fetchImpl);
    },
  },
};
