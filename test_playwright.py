import asyncio
from playwright.async_api import async_playwright

URL = "https://www.plussark.no"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Loading:", URL)
        response = await page.goto(
            URL, 
            wait_until="domcontentloaded", 
            timeout=30000
        )
        print("HTTP:", response.status if response else "NO RESPONSE")
        await page.wait_for_timeout(3000)
        print("Title:", await page.title())
        text = await page.locator("body").inner_text()
        print("Rendered text length:", len(text))
        print("\n--- FIRST 2000 CHARACTERS ---\n")
        print(text[:2000])
        await browser.close()

asyncio.run(main())
