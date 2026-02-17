import asyncio

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

from src import db
from src.config import Config
from src.api_client import ApiClient

router = APIRouter(tags=["api"])


# --- Bot control ---

@router.post("/api/bot/start")
async def bot_start(request: Request):
    bot = request.app.state.bot
    result = await bot.start()
    stats = await bot.get_stats()
    return request.app.state.templates.TemplateResponse(
        "partials/bot_status.html", {"request": request, "stats": stats}
    )


@router.post("/api/bot/stop")
async def bot_stop(request: Request):
    bot = request.app.state.bot
    await bot.stop()
    stats = await bot.get_stats()
    return request.app.state.templates.TemplateResponse(
        "partials/bot_status.html", {"request": request, "stats": stats}
    )


@router.get("/api/bot/status")
async def bot_status(request: Request):
    bot = request.app.state.bot
    stats = await bot.get_stats()
    return JSONResponse(stats)


# --- Traders ---

@router.get("/api/traders")
async def list_traders():
    traders = await db.get_traders()
    return JSONResponse([dict(t) for t in traders])


@router.post("/api/traders")
async def add_trader(request: Request, address: str = Form(""), label: str = Form("")):
    address = address.strip()
    if address:
        await db.add_trader(address, label=label.strip(), source="manual")
    traders = await db.get_traders()
    return request.app.state.templates.TemplateResponse(
        "partials/_trader_list.html", {"request": request, "traders": traders}
    )


@router.delete("/api/traders/{address}")
async def delete_trader(request: Request, address: str):
    await db.remove_trader(address)
    traders = await db.get_traders()
    return request.app.state.templates.TemplateResponse(
        "partials/_trader_list.html", {"request": request, "traders": traders}
    )


@router.post("/api/traders/{address}/toggle")
async def toggle_trader(request: Request, address: str):
    await db.toggle_trader(address)
    traders = await db.get_traders()
    return request.app.state.templates.TemplateResponse(
        "partials/_trader_list.html", {"request": request, "traders": traders}
    )


@router.post("/api/traders/refresh")
async def refresh_traders(request: Request):
    config = await Config.from_db()
    if config.api_key:
        client = ApiClient(config)
        try:
            fetched = await asyncio.to_thread(client.fetch_traders)
            for t in fetched:
                addr = t.get("address", "")
                label = t.get("name", t.get("label", ""))
                if addr:
                    await db.add_trader(addr, label=label, source="api")
        finally:
            client.close()

    traders = await db.get_traders()
    return request.app.state.templates.TemplateResponse(
        "partials/_trader_list.html", {"request": request, "traders": traders}
    )


# --- Settings API ---

@router.get("/api/settings")
async def get_settings():
    config = await Config.from_db()
    return JSONResponse({
        "api_key": config.api_key[:8] + "..." if len(config.api_key) > 8 else config.api_key,
        "paper_trading": config.paper_trading,
        "max_position_usd": config.max_position_usd,
        "max_concurrent_positions": config.max_concurrent_positions,
        "daily_loss_limit_usd": config.daily_loss_limit_usd,
        "poll_interval": config.poll_interval,
        "max_traders": config.max_traders,
        "rpc_url": config.rpc_url,
    })


# --- HTMX partials ---

@router.get("/htmx/positions")
async def htmx_positions(request: Request):
    positions = await db.get_positions()
    return request.app.state.templates.TemplateResponse(
        "partials/positions.html", {"request": request, "positions": positions}
    )


@router.get("/htmx/activity")
async def htmx_activity(request: Request):
    activity = await db.get_activity(limit=50)
    return request.app.state.templates.TemplateResponse(
        "partials/activity.html", {"request": request, "activity": activity}
    )


@router.get("/htmx/bot-status")
async def htmx_bot_status(request: Request):
    bot = request.app.state.bot
    stats = await bot.get_stats()
    return request.app.state.templates.TemplateResponse(
        "partials/bot_status.html", {"request": request, "stats": stats}
    )
