from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_architecture,
    routes_demo,
    routes_evaluations,
    routes_events,
    routes_inventory,
    routes_llm,
    routes_projects,
    routes_research_profiles,
    routes_reports,
    routes_runs,
    routes_source_bundles,
    routes_sources,
    routes_tools,
    routes_workflow,
)
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        # 本机调试时，浏览器经代理/反向代理发出的 Origin 可能丢失端口（如 http://127.0.0.1），
        # 因此除带端口的写法外，也显式放行不带端口的本地来源，避免 SSE 被拦成 Failed to fetch。
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_demo.router)
    app.include_router(routes_evaluations.router)
    app.include_router(routes_workflow.router)
    app.include_router(routes_projects.router)
    app.include_router(routes_research_profiles.router)
    app.include_router(routes_source_bundles.router)
    app.include_router(routes_sources.router)
    app.include_router(routes_inventory.router)
    app.include_router(routes_events.router)
    app.include_router(routes_llm.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_tools.router)
    app.include_router(routes_architecture.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
        }

    return app


app = create_app()
