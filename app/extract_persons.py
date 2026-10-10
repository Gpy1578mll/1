from app.llm import extract_kind

async def extract(text):
    return await extract_kind(text, "persons")
