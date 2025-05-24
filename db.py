from pymongo import MongoClient
import os
mongo_client = MongoClient(os.environ.get("MONGO_URI"))
db = mongo_client["news_db"]