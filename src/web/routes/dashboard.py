from fastapi import APIRouter, Request

router = APIRouter(tags=["dashboard"])


@router.get("/")
async def dashboard(request: Request):
    bot = request.app.state.bot
    stats = await bot.get_stats()
    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "active": "dashboard", "stats": stats},
    )
