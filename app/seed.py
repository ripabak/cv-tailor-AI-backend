import os
import re
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Template
from .database import async_session


async def seed_templates():
    async with async_session() as db:
        result = await db.execute(select(func.count(Template.id)))
        count = result.scalar()
        if count > 0:
            return

        template_path = os.path.join(os.path.dirname(__file__), "resume-template.html")
        if not os.path.exists(template_path):
            print(f"Template file not found: {template_path}")
            return

        with open(template_path) as f:
            html = f.read()

        template = Template(
            title="Classic Resume",
            html_code=html,
            creator_id=None,
            is_published=True,
        )
        db.add(template)
        await db.commit()
        print("Seeded default template: Classic Resume")
