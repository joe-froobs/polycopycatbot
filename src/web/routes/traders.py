from fastapi import APIRouter, Request

from src import db

router = APIRouter(tags=["traders"])


@router.get("/traders")
async def traders_page(request: Request):
    traders = await db.get_traders()
    api_key = await db.get_setting("api_key")
    return request.app.state.templates.TemplateResponse(
        "traders.html",
        {
            "request": request,
            "active": "traders",
            "traders": traders,
            "has_api_key": bool(api_key),
        },
    )
