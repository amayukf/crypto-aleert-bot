import asyncio
import aiohttp
import logging

class CryptoAPI:
    BASE_URL = "https://api.dexscreener.com/latest/dex/search"

    @classmethod
    async def search_coin(cls, query: str):
        url = f"{cls.BASE_URL}?q={query}"
        try:
            # Create a fresh session each call to avoid event loop issues on cloud platforms
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        pairs = data.get("pairs", [])
                        if not pairs:
                            return None
                        return pairs[0]
                    else:
                        logging.error(f"DexScreener API error: {response.status}")
                        return None
        except asyncio.TimeoutError:
            logging.error(f"DexScreener API timeout for query: {query}")
            return None
        except Exception as e:
            logging.error(f"Failed to fetch data from DexScreener: {e}")
            return None

    @classmethod
    def format_coin_info(cls, pair_data: dict):
        if not pair_data:
            return "Coin not found."

        base_token = pair_data.get("baseToken", {})
        name = base_token.get("name", "Unknown")
        symbol = base_token.get("symbol", "Unknown")
        price_usd = pair_data.get("priceUsd", "N/A")
        change_24h = pair_data.get("priceChange", {}).get("h24", 0)
        dex_id = pair_data.get("dexId", "N/A")

        try:
            volume_raw = pair_data.get("volume", {}).get("h24", 0)
            volume_24h = float(volume_raw) if volume_raw else 0
            vol_str = f"${volume_24h:,.0f}"
        except (ValueError, TypeError):
            vol_str = "N/A"

        try:
            change_val = float(change_24h) if change_24h else 0
        except (ValueError, TypeError):
            change_val = 0

        emoji = "📈" if change_val >= 0 else "📉"

        return (
            f"<b>{name} ({symbol})</b>\n"
            f"DEX: {dex_id.capitalize()}\n\n"
            f"💰 Price: <code>${price_usd}</code>\n"
            f"{emoji} 24h: <code>{change_24h}%</code>\n"
            f"📊 Vol: <code>{vol_str}</code>\n\n"
            f"<a href='{pair_data.get('url', '')}'>View on DexScreener</a>"
        )

    @classmethod
    async def get_trending_coins(cls):
        url_boosts = "https://api.dexscreener.com/token-boosts/latest/v1"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.get(url_boosts) as response:
                    if response.status == 200:
                        boosts = await response.json()
                        if not isinstance(boosts, list):
                            return []
                        
                        unique_tokens = []
                        seen_addresses = set()
                        for b in boosts:
                            address = b.get("tokenAddress")
                            if address and address not in seen_addresses:
                                seen_addresses.add(address)
                                unique_tokens.append(b)
                                if len(unique_tokens) >= 5:
                                    break
                                    
                        tasks = []
                        for t in unique_tokens:
                            addr = t.get("tokenAddress")
                            chain = t.get("chainId", "solana")
                            tasks.append(cls.fetch_token_pairs(session, chain, addr))
                            
                        results = await asyncio.gather(*tasks)
                        return [r for r in results if r]
                    else:
                        logging.error(f"DexScreener boosts API error: {response.status}")
                        return []
        except Exception as e:
            logging.error(f"Failed to fetch trending coins: {e}")
            return []

    @classmethod
    async def fetch_token_pairs(cls, session: aiohttp.ClientSession, chain_id: str, token_address: str):
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        for p in pairs:
                            if p.get("chainId") == chain_id:
                                return p
                        return pairs[0]
                return None
        except Exception as e:
            logging.error(f"Error fetching token pair {token_address}: {e}")
            return None

