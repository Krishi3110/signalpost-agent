import asyncio
from api_gov import fetch_brreg_basic_info, fetch_brreg_roles

async def test():
    for orgnr in ["989061593", "995849364"]:
        profile = await fetch_brreg_basic_info(orgnr)
        if profile:
            profile = await fetch_brreg_roles(profile)
            print(f"\n{orgnr}")
            print(profile.model_dump_json(indent=2))
        else:
            print(f"Failed to fetch {orgnr}")

asyncio.run(test())
