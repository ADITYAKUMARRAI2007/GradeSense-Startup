#!/usr/bin/env python3
"""Quick test of GCP Vision credentials and API."""

import os
import json
from pathlib import Path

# Check env
env_file = Path('.env')
print(f'Env file exists: {env_file.exists()}')

# Check credentials
creds_file = Path('credentials/gcp-vision-key.json')
print(f'Credentials file exists: {creds_file.exists()}')

# Load and validate
if creds_file.exists():
    with open(creds_file) as f:
        creds = json.load(f)
    print(f'Project ID: {creds.get("project_id")}')
    print(f'Service Account: {creds.get("client_email")}')
    print('✅ JSON structure valid')

# Test Vision API
try:
    from google.cloud import vision
    print('✅ google-cloud-vision imported')
    
    # Set credentials
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(creds_file.absolute())
    client = vision.ImageAnnotatorClient()
    print('✅ Vision API client initialized!')
    print('🎉 All systems ready for OCR annotation & labeling!')
except Exception as e:
    print(f'❌ Error: {e}')
