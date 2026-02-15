#!/usr/bin/env python3
"""
Test script to verify multi-file upload behavior
"""
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')

async def test_multifile():
    # Get a valid auth token (you'll need to replace with actual teacher credentials)
    api_url = os.getenv("REACT_APP_BACKEND_URL", "http://localhost:8001/api")
    
    # First, let's just check if we can hit the API
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{api_url}/health")
            print(f"Health check: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_multifile())
