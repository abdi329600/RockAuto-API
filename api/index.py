from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI()

# Allow your Next.js app to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: ["https://your-app.vercel.app"]
    allow_methods=["*"],
    allow_headers=["*"],
)


class PartsRequest(BaseModel):
    make: str
    year: int
    model: str
    category: str = "body"


# Simplified RockAuto client (we'll use their public catalog URLs)
class SimpleRockAutoClient:
    def __init__(self):
        self.base_url = "https://www.rockauto.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

    async def search_parts(self, make: str, year: int, model: str, category: str):
        # RockAuto's catalog URL format
        url = f"{self.base_url}/en/catalog/{make.lower()},{year},{model.lower().replace(' ', '+')}"

        async with httpx.AsyncClient() as client:
            try:
                await client.get(url, headers=self.headers, follow_redirects=True)

                # Parse the response (simplified - just return mock data for now)
                # You'll improve this with the full RockAuto API client later
                return {
                    "parts": [
                        {
                            "name": f"{make} {model} {category} Part",
                            "price": 89.99,
                            "brand": "Generic",
                            "part_number": "12345",
                            "availability": "In Stock",
                            "source": "rockauto",
                        }
                    ]
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"status": "RockAuto API is running"}


@app.post("/parts")
async def get_parts(payload: PartsRequest):
    """
    Get parts for a specific vehicle and category
    """
    client = SimpleRockAutoClient()
    result = await client.search_parts(
        payload.make,
        payload.year,
        payload.model,
        payload.category,
    )
    return result


@app.get("/health")
async def health():
    return {"status": "healthy"}
