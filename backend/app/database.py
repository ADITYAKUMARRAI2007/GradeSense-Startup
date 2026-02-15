"""
Database connections - MongoDB async (Motor) + sync (PyMongo for GridFS).
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from gridfs import GridFS

mongo_url = os.environ['MONGO_URL']
db_name = os.environ['DB_NAME']

# Async client (used by all app queries)
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# Sync client (used by GridFS - Motor doesn't have async GridFS)
sync_client = MongoClient(mongo_url)
sync_db = sync_client[db_name]
fs = GridFS(sync_db)
