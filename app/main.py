from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import init_db
from .seed import seed_templates
from .routers import auth, templates, cv, public, agent_protocol


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    await seed_templates()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(cv.router)
app.include_router(public.router)
app.include_router(agent_protocol.router)
