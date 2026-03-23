# passenger_wsgi.py - For Namecheap deployment
import sys
import os

# Add the application directory to the path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(APP_DIR)

# Import the Flask application
from app import app as application

# For debugging (optional)
if __name__ == '__main__':
    application.run()