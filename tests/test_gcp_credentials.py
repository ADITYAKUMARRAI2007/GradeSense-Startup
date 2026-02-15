#!/usr/bin/env python3
"""
Quick test to verify GCP Vision API credentials are working.
"""

import os
import sys
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

def test_credentials():
    """Test that GCP credentials are properly loaded."""
    
    # Check .env file (from root or backend)
    env_file = Path("backend/.env")
    if not env_file.exists():
        env_file = Path(".env")
    
    if not env_file.exists():
        print("❌ .env file not found")
        return False
    
    print(f"✅ .env file found at {env_file}")
    
    # Check credentials file
    creds_file = Path("backend/credentials/gcp-vision-key.json")
    if not creds_file.exists():
        print("❌ credentials/gcp-vision-key.json not found")
        return False
    
    print("✅ credentials/gcp-vision-key.json found")
    
    # Validate JSON format
    try:
        with open(creds_file) as f:
            creds = json.load(f)
        
        required_keys = ["type", "project_id", "private_key", "client_email"]
        missing = [k for k in required_keys if k not in creds]
        
        if missing:
            print(f"❌ Missing required keys in JSON: {missing}")
            return False
        
        print(f"✅ Credentials JSON valid")
        print(f"   Project ID: {creds['project_id']}")
        print(f"   Service Account: {creds['client_email']}")
        
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in credentials file: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading credentials: {e}")
        return False
    
    # Try loading the GCP library
    try:
        from google.cloud import vision
        print("✅ google-cloud-vision library installed")
    except ImportError:
        print("⚠️  google-cloud-vision not installed. Run: pip install google-cloud-vision")
        return False
    
    # Set env var and test Vision client initialization
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(creds_file.absolute())
    
    try:
        client = vision.ImageAnnotatorClient()
        print("✅ Vision API client initialized successfully!")
        print("\n🎉 All checks passed! Your GCP Vision credentials are ready to use.")
        return True
    except Exception as e:
        print(f"❌ Failed to initialize Vision API client: {e}")
        return False

if __name__ == "__main__":
    success = test_credentials()
    sys.exit(0 if success else 1)
