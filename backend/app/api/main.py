from fastapi import APIRouter

from app.api.routes import develop, items, login, private, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(develop.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)

if settings.DEVELOP_ACCEPTANCE_MODE:
    from app.api.routes import testing_agent

    api_router.include_router(testing_agent.router)
