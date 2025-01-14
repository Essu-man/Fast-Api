from main import app
from uvicorn.workers import UvicornWorker

# For Gunicorn
class CustomWorker(UvicornWorker):
    CONFIG_KWARGS = {"loop": "auto", "http": "auto"}

# For direct running
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
