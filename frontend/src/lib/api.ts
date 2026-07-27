import createClient from "openapi-fetch";
import type { paths } from "@/lib/api-types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010";

export const api = createClient<paths>({ baseUrl: API_BASE_URL });

export type ApiError = {
  code: string;
  message: string;
  details: unknown;
};

/** Every ClaimFlow error response is {error: {code, message, details}} — see src/claimflow/schemas/errors.py */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const body = (error as { error: ApiError }).error;
    return body?.message ?? "Request failed";
  }
  return "Could not reach the ClaimFlow API";
}
