import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

# Import the app
from app import app as application