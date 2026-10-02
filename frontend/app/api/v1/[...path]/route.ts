import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function backendOrigin(): string {
  // Use BACKEND_URL only — NEXT_PUBLIC_* is inlined at `next build` and ignores Cloud Run runtime env.
  const raw = process.env.BACKEND_URL || "http://localhost:8000";
  return raw.trim().replace(/^["']|["']$/g, "").replace(/\/$/, "");
}

const FORWARD_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "authorization",
  "content-type",
  "if-none-match",
  "if-modified-since",
];

function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  return headers;
}

/** When the backend Cloud Run service requires authentication, call with an ID token. */
async function cloudRunIdToken(audience: string): Promise<string | null> {
  if (!audience.includes(".run.app")) {
    return null;
  }
  try {
    const res = await fetch(
      `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}`,
      { headers: { "Metadata-Flavor": "Google" } },
    );
    if (!res.ok) {
      return null;
    }
    return await res.text();
  } catch {
    return null;
  }
}

async function proxyRequest(request: NextRequest, pathSegments: string[] | undefined): Promise<NextResponse> {
  const origin = backendOrigin();
  const segments = pathSegments ?? [];
  const subpath = segments.join("/");
  const target = `${origin}/api/v1/${subpath}${request.nextUrl.search}`;

  try {
    const headers = buildForwardHeaders(request);
    const idToken = await cloudRunIdToken(origin);
    if (idToken) {
      headers.set("Authorization", `Bearer ${idToken}`);
    }

    const init: RequestInit = {
      method: request.method,
      headers,
      redirect: "manual",
      cache: "no-store",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = await request.arrayBuffer();
    }

    const upstream = await fetch(target, init);
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("transfer-encoding");
    responseHeaders.delete("content-length");

    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown proxy error";
    console.error("API proxy failed:", target, message);
    const missingBackend =
      origin === "http://localhost:8000" || !process.env.BACKEND_URL?.trim();
    return NextResponse.json(
      {
        detail: missingBackend
          ? "BACKEND_URL is not set on this Cloud Run revision (proxy defaulted to localhost). Add BACKEND_URL=https://data-governance-ai-....run.app and deploy."
          : `API proxy could not reach backend (${message}).`,
        resolvedBackend: origin,
        target,
      },
      { status: 502 },
    );
  }
}

type RouteContext = { params: { path: string[] } };

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context.params.path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context.params.path);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context.params.path);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context.params.path);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context.params.path);
}
