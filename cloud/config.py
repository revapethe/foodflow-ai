import os
from dotenv import load_dotenv
load_dotenv()
def required(key):
 value=os.getenv(key)
 if not value: raise ValueError(f"Missing {key}; configure .env from .env.example")
 return value
