"""Thin MCP tools that call the existing authenticated Watching HTTP API."""

from __future__ import annotations

import contextlib
import os
from typing import Any
from urllib.parse import quote

import httpx
from a2wsgi import WSGIMiddleware
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from xiaxia_watch_house import create_app


watching_app = create_app()
mcp = MCPServer("Xiaxia Watching House")


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one existing Action route with the existing bearer credential."""
    port = os.environ.get("PORT", "10000")
    token = os.environ["ACTION_BEARER_TOKEN"]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120.0) as client:
        response = client.request(
            method,
            path,
            params={key: value for key, value in (params or {}).items() if value is not None},
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    return response.json()


def _body(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _path_segment(value: str) -> str:
    return quote(value, safe="")


@mcp.tool()
def list_videos() -> dict[str, Any]:
    """List videos with their current watch state and a result count."""
    return _request("GET", "/api/watch/videos")


@mcp.tool()
def get_video(film_id: str) -> dict[str, Any]:
    """Read one video and its current watch state by film ID."""
    return _request("GET", f"/api/watch/videos/{_path_segment(film_id)}")


@mcp.tool()
def get_watch_state() -> dict[str, Any]:
    """Read the current film, user progress, and Xiaxia viewing state."""
    return _request("GET", "/api/watch/state")


@mcp.tool()
def get_current_context(
    film_id: str,
    before_seconds: float = 120,
    timestamp_seconds: float | None = None,
) -> dict[str, Any]:
    """Read bounded timeline context and subtitle cues for a video timestamp."""
    return _request(
        "GET",
        f"/api/watch/videos/{_path_segment(film_id)}/context",
        params={"before_seconds": before_seconds, "timestamp_seconds": timestamp_seconds},
    )


@mcp.tool()
def get_transcript(
    film_id: str,
    chunk_size_cues: int | None = None,
    chunk_index: int | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    continuation: str | None = None,
    from_checkpoint: bool = False,
) -> dict[str, Any]:
    """Read a bounded transcript chunk, optionally by time range or continuation."""
    return _request(
        "GET",
        f"/api/watch/videos/{_path_segment(film_id)}/transcript",
        params={
            "chunk_size_cues": chunk_size_cues,
            "chunk_index": chunk_index,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "continuation": continuation,
            "from_checkpoint": str(from_checkpoint).lower(),
        },
    )


@mcp.tool()
def list_annotations(film_id: str) -> dict[str, Any]:
    """List annotations attached to a video."""
    return _request("GET", f"/api/watch/videos/{_path_segment(film_id)}/annotations")


@mcp.tool()
def list_thoughts(film_id: str) -> dict[str, Any]:
    """List Xiaxia thoughts recorded for a video."""
    return _request("GET", f"/api/watch/videos/{_path_segment(film_id)}/thoughts")


@mcp.tool()
def create_thought(
    film_id: str,
    start_seconds: float,
    content: str,
    end_seconds: float | None = None,
    cue_id: str | None = None,
) -> dict[str, Any]:
    """Create a Xiaxia thought with a timeline position and optional subtitle cue."""
    return _request(
        "POST",
        f"/api/watch/videos/{_path_segment(film_id)}/thoughts",
        body=_body(
            start_seconds=start_seconds,
            content=content,
            end_seconds=end_seconds,
            cue_id=cue_id,
        ),
    )


@mcp.tool()
def list_fleeting_traces(film_id: str) -> dict[str, Any]:
    """List unexpired fleeting traces for a video."""
    return _request("GET", f"/api/watch/videos/{_path_segment(film_id)}/fleeting-traces")


@mcp.tool()
def create_fleeting_trace(
    film_id: str,
    start_seconds: float,
    content: str,
    end_seconds: float | None = None,
    cue_id: str | None = None,
) -> dict[str, Any]:
    """Create a fleeting trace with a timeline position and optional subtitle cue."""
    return _request(
        "POST",
        f"/api/watch/videos/{_path_segment(film_id)}/fleeting-traces",
        body=_body(
            start_seconds=start_seconds,
            content=content,
            end_seconds=end_seconds,
            cue_id=cue_id,
        ),
    )


@mcp.tool()
def create_reply(
    annotation_id: str,
    content: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    cue_id: str | None = None,
) -> dict[str, Any]:
    """Add a Xiaxia reply to an annotation with optional timeline anchors."""
    return _request(
        "POST",
        f"/api/watch/annotations/{_path_segment(annotation_id)}/reply",
        body=_body(
            content=content,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            cue_id=cue_id,
        ),
    )


@mcp.tool()
def update_xiaxia_progress(
    film_id: str,
    last_timestamp_seconds: float,
    last_subtitle_cue_id: str | None = None,
    chunk_checkpoint: int | None = None,
    completed: bool = False,
) -> dict[str, Any]:
    """Update Xiaxia's viewing position and optional transcript checkpoint."""
    return _request(
        "POST",
        "/api/watch/xiaxia/progress",
        body={
            "film_id": film_id,
            "last_timestamp_seconds": last_timestamp_seconds,
            "last_subtitle_cue_id": last_subtitle_cue_id,
            "chunk_checkpoint": chunk_checkpoint,
            "completed": completed,
        },
    )


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield


host = os.environ.get("RENDER_EXTERNAL_HOSTNAME") or os.environ.get("WATCH_PUBLIC_HOST", "localhost")
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[host, f"{host}:*", "localhost:*", "127.0.0.1:*"],
)
mcp_http_app = mcp.streamable_http_app(transport_security=transport_security)
watching_wsgi_app = WSGIMiddleware(watching_app, workers=4)


async def dispatch_http(scope, receive, send):
    """Send only /mcp to the MCP app and keep existing Flask routes on the WSGI bridge."""
    if scope["path"] == "/mcp":
        await mcp_http_app(scope, receive, send)
    else:
        await watching_wsgi_app(scope, receive, send)


app = Starlette(routes=[Mount("/", app=dispatch_http)], lifespan=lifespan)
