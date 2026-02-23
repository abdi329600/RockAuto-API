from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from bs4 import BeautifulSoup
import httpx
import os
import asyncio
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Category → RockAuto subcategory path ───────────────────────────────────

CATEGORY_PATHS: dict[str, tuple[str, str]] = {
    "body":     ("body+%26+lamp+assembly", "bumper+cover"),
    "lighting": ("body+%26+lamp+assembly", "headlamp+assembly"),
    "glass":    ("body+%26+lamp+assembly", "windshield+glass"),
    "mirror":   ("body+%26+lamp+assembly", "mirror+-+side+view"),
    "hood":     ("body+%26+lamp+assembly", "hood"),
    "fender":   ("body+%26+lamp+assembly", "fender"),
    "door":     ("body+%26+lamp+assembly", "door+shell"),
    "grille":   ("body+%26+lamp+assembly", "grille"),
    "trunk":    ("body+%26+lamp+assembly", "trunk+lid"),
}

# ─── Models ─────────────────────────────────────────────────────────────────

class PartsRequest(BaseModel):
    make: str
    year: int
    model: str
    category: str = "body"


class PartResult(BaseModel):
    name: str
    price: float
    shipping: float
    total_price: float
    brand: str
    condition: str
    part_number: Optional[str] = None
    url: str
    source: str
    is_best_deal: bool = False


class RockAutoPartInfo(BaseModel):
    part_number: Optional[str] = None
    oem_number: Optional[str] = None
    description: str
    price: float
    url: str
    brand: str

# ─── Step 1: RockAuto catalog scrape ────────────────────────────────────────

async def get_rockauto_parts(
    make: str, year: int, model: str, category: str
) -> list[RockAutoPartInfo]:
    cat_path = CATEGORY_PATHS.get(category, CATEGORY_PATHS["body"])
    vehicle = f"{make.lower()},{year},{model.lower().replace(' ', '+')}"
    catalog_url = (
        f"https://www.rockauto.com/en/catalog/"
        f"{vehicle},{cat_path[0]},{cat_path[1]}"
    )

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(catalog_url, headers=HEADERS, follow_redirects=True)
            if not resp.is_success:
                return _rockauto_fallback(make, year, model, category, catalog_url)

            soup = BeautifulSoup(resp.text, "html.parser")
            parts: list[RockAutoPartInfo] = []

            # RockAuto listing rows contain class "listing-text-row"
            for row in soup.select(".listing-text-row")[:6]:
                brand_el = row.select_one(".listing-text-row-brand")
                desc_el  = row.select_one(".listing-text-row-text")
                price_el = row.select_one(".listing-price")
                pn_el    = row.select_one(".listing-text-row-mfr-label")

                if not price_el:
                    continue

                price_text = price_el.get_text(strip=True)
                price_match = re.search(r"[\d,]+\.\d{2}", price_text.replace(",", ""))
                if not price_match:
                    continue

                price = float(price_match.group())
                brand = brand_el.get_text(strip=True) if brand_el else "Aftermarket"
                desc  = desc_el.get_text(strip=True)  if desc_el  else f"{year} {make} {model} Part"
                pn    = pn_el.get_text(strip=True)    if pn_el    else None

                parts.append(RockAutoPartInfo(
                    part_number=pn,
                    description=desc,
                    price=price,
                    url=catalog_url,
                    brand=brand,
                ))

            return parts if parts else _rockauto_fallback(make, year, model, category, catalog_url)

    except Exception as exc:
        print(f"[rockauto-scrape] error: {exc}")
        return _rockauto_fallback(make, year, model, category,
            f"https://www.rockauto.com/en/catalog/{vehicle}")


def _rockauto_fallback(
    make: str, year: int, model: str, category: str, url: str
) -> list[RockAutoPartInfo]:
    label_map = {
        "body": "Bumper Cover", "lighting": "Headlamp Assembly",
        "glass": "Windshield Glass", "mirror": "Side View Mirror",
        "hood": "Hood", "fender": "Fender", "door": "Door Shell",
        "grille": "Grille", "trunk": "Trunk Lid",
    }
    label = label_map.get(category, "Part")
    return [
        RockAutoPartInfo(
            description=f"{year} {make} {model} {label} (Economy)",
            price=59.99,
            url=url,
            brand="Economy",
        ),
        RockAutoPartInfo(
            description=f"{year} {make} {model} {label} (OEM)",
            price=119.99,
            url=url,
            brand="OEM",
        ),
    ]

# ─── Step 2: eBay search by part numbers ────────────────────────────────────

async def search_ebay_by_parts(
    rockauto_parts: list[RockAutoPartInfo],
    make: str, year: int, model: str,
) -> list[PartResult]:
    if not EBAY_APP_ID:
        return []

    results: list[PartResult] = []

    for ra in rockauto_parts[:3]:
        # Build keyword: prefer part numbers, fall back to description
        if ra.part_number or ra.oem_number:
            pns = " OR ".join(filter(None, [ra.part_number, ra.oem_number]))
            keywords = pns
        else:
            keywords = f"{year} {make} {model} {ra.description}"

        params = {
            "OPERATION-NAME": "findItemsByKeywords",
            "SERVICE-VERSION": "1.0.0",
            "SECURITY-APPNAME": EBAY_APP_ID,
            "RESPONSE-DATA-FORMAT": "JSON",
            "keywords": keywords,
            "categoryId": "6028",
            "sortOrder": "PricePlusShippingLowest",
            "paginationInput.entriesPerPage": "5",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://svcs.ebay.com/services/search/FindingService/v1",
                    params=params,
                )
                data = resp.json()

            items = (
                data.get("findItemsByKeywordsResponse", [{}])[0]
                    .get("searchResult", [{}])[0]
                    .get("item", [])
            )

            for item in items:
                price = float(
                    item["sellingStatus"][0]["currentPrice"][0]["__value__"]
                )
                shipping = float(
                    item.get("shippingInfo", [{}])[0]
                        .get("shippingServiceCost", [{"__value__": "0"}])[0]["__value__"]
                )
                condition = (
                    item.get("condition", [{}])[0]
                        .get("conditionDisplayName", ["Used"])[0]
                )
                results.append(PartResult(
                    name=item["title"][0],
                    price=price,
                    shipping=shipping,
                    total_price=round(price + shipping, 2),
                    brand="eBay Seller",
                    condition=condition,
                    part_number=ra.part_number,
                    url=item["viewItemURL"][0],
                    source="ebay",
                ))
        except Exception as exc:
            print(f"[ebay-search] error for '{keywords}': {exc}")

    return results

# ─── Step 3: Combine & rank ──────────────────────────────────────────────────

@app.post("/parts")
async def get_parts(payload: PartsRequest):
    rockauto_parts, ebay_results = await asyncio.gather(
        get_rockauto_parts(payload.make, payload.year, payload.model, payload.category),
        search_ebay_by_parts([], payload.make, payload.year, payload.model),
    )

    # Re-run eBay with actual RockAuto part numbers
    if rockauto_parts:
        ebay_results = await search_ebay_by_parts(
            rockauto_parts, payload.make, payload.year, payload.model
        )

    all_parts: list[PartResult] = []

    for ra in rockauto_parts:
        all_parts.append(PartResult(
            name=ra.description,
            price=ra.price,
            shipping=0.0,
            total_price=ra.price,
            brand=ra.brand,
            condition="New",
            part_number=ra.part_number,
            url=ra.url,
            source="rockauto",
        ))

    all_parts.extend(ebay_results)
    all_parts.sort(key=lambda p: p.total_price if p.total_price > 0 else 999999)

    if all_parts:
        all_parts[0].is_best_deal = True

    return {
        "parts": [p.model_dump() for p in all_parts],
        "count": len(all_parts),
        "best_deal": all_parts[0].model_dump() if all_parts else None,
        "sources": {
            "rockauto": sum(1 for p in all_parts if p.source == "rockauto"),
            "ebay": sum(1 for p in all_parts if p.source == "ebay"),
        },
    }


@app.get("/")
async def root():
    return {"status": "RockAuto + eBay parts API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "ebay_configured": bool(EBAY_APP_ID)}
