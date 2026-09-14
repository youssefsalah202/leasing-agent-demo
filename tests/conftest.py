from dotenv import load_dotenv

# So `pytest` picks up ANTHROPIC_API_KEY (etc.) from .env the same way the
# app does, without requiring it to be exported in the shell first.
load_dotenv()
