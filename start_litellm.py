import sys
import os

sys.path.insert(0, '/Users/ducorn/DC/scripts')

import litellm
from ducorn_classifier import custom_router_pre_call_hook
litellm.callbacks = [custom_router_pre_call_hook]
print("[DuCorn] Classifier registered:", custom_router_pre_call_hook.__name__)

from litellm.proxy.proxy_server import app, initialize
import uvicorn
import asyncio

async def main():
    await initialize(config="/Users/ducorn/DC/litellm_config.yaml")
    config = uvicorn.Config(app, host="0.0.0.0", port=4000)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
