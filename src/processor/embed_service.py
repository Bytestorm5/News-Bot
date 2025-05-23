import openai
from ..config import settings

openai.api_key = settings.OPENAI_KEY

async def embed_text(text: str) -> list:
    """
    Generate an embedding vector for the given text using OpenAI.
    """
    response = await openai.Embedding.acreate(
        input=[text],
        model="text-embedding-ada-002"
    )
    # Return the embedding vector
    return response.data[0].embedding