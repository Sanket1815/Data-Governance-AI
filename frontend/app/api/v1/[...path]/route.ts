import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function backendOrigin(): string {
  const raw =
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
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

async function proxyRequest(request: NextRequest, pathSegments: string[] | undefined): Promise<NextResponse> {
  const segments = pathSegments ?? [];
  const subpath = segments.join("/");
  const target = `${backendOrigin()}/api/v1/${subpath}${request.nextUrl.search}`;

  try {
    const init: RequestInit = {
      method: request.method,
      headers: buildForwardHeaders(request),
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
    return NextResponse.json(
      {
        detail: `API proxy could not reach backend (${message}). Check BACKEND_URL on the frontend Cloud Run service.`,
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
