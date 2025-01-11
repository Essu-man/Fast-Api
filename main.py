from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import pandas as pd
import os
import random
import string
import qrcode
import shutil
from datetime import datetime
from typing import Optional
from pathlib import Path

app = FastAPI()

# Setup templates for rendering HTML
templates = Jinja2Templates(directory="templates")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/qr_codes", StaticFiles(directory="qr_codes"), name="qr_codes")

# Paths for uploaded files and QR code images
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "qr_codes"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Use your Render URL (update this after deployment)
BASE_URL = "https://dvplates.onrender.com/"

def get_local_ip():
    try:
        # Get the local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

def generate_code():
    """Generate a formatted random alphanumeric hexadecimal code with hyphens."""
    raw_code = ''.join(random.choices(string.hexdigits.upper(), k=15))
    formatted_code = '-'.join([raw_code[i:i+5] for i in range(0, len(raw_code), 5)])
    return formatted_code

# API health check endpoint
@app.get("/api/health")
async def health_check():
    return {"message": "API is running"}

# Main page endpoint
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Render the main upload page"""
    return templates.TemplateResponse("super.html", {"request": request})

# Scan endpoint
@app.get("/scan/{serial_number}", response_class=HTMLResponse)
async def scan_page(request: Request, serial_number: str):
    """Render the scan result page"""
    try:
        # Debug print
        print(f"Scanning serial number: {serial_number}")

        # Get details
        details = await get_details(serial_number)
        print(f"Found details: {details}")  # Debug print

        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": details,
                "error": None
            }
        )
    except HTTPException as e:
        print(f"Error scanning: {e.detail}")  # Debug print
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": f"QR Code not found: {serial_number}"
            }
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # Debug print
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": "An unexpected error occurred"
            }
        )

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile):
    try:
        if not file.filename.endswith(".csv"):
            return JSONResponse(
                status_code=400,
                content={"error": "Only CSV files are allowed."}
            )

        # Create a unique directory for this upload
        upload_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_dir = Path(OUTPUT_FOLDER) / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Load CSV into a DataFrame
        df = pd.read_csv(file.file)

        if "DV NUMBER" not in df.columns:
            return JSONResponse(
                status_code=400,
                content={"error": "CSV must contain 'DV NUMBER' column"}
            )

        # Generate "In-house serial number" for each row
        df["IN-HOUSE SERIAL NUMBER"] = [generate_code() for _ in range(len(df))]
        df["DATE OF ISSUANCE"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Generate QR codes with full Render URL
        for index, row in df.iterrows():
            try:
                serial_number = str(row["IN-HOUSE SERIAL NUMBER"]).strip()

                # Create full URL for QR code
                qr_data = f"{BASE_URL}/scan/{serial_number}"
                print(f"QR Data URL: {qr_data}")

                # Create and save QR code
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)

                qr_img = qr.make_image(fill_color="black", back_color="white")
                qr_filename = upload_dir / f"qr_{serial_number}.png"
                qr_img.save(str(qr_filename))

            except Exception as row_error:
                print(f"Error processing row: {row_error}")
                continue

        # Update CSV with full URLs for QR codes
        df["QR CODE LINK"] = df["IN-HOUSE SERIAL NUMBER"].apply(
            lambda x: f"{BASE_URL}/qr_codes/{upload_id}/qr_{x}.png"
        )

        # Store the DataFrame
        data_file = upload_dir / "data.pkl"
        df.to_pickle(str(data_file))

        # Save CSV output
        output_file = upload_dir / "Generated_qr.csv"
        df.to_csv(str(output_file), index=False)

        return FileResponse(str(output_file), media_type="text/csv", filename="Generated_qr.csv")

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error processing upload: {str(e)}"}
        )

async def get_details(serial_number: str):
    """Get the details based on the scanned QR code."""
    try:
        # Debug print
        print(f"Looking for details of serial: {serial_number}")

        # List all directories in OUTPUT_FOLDER
        upload_dirs = sorted(Path("qr_codes").glob("*"))
        print(f"Found directories: {[str(d) for d in upload_dirs]}")  # Debug print

        if not upload_dirs:
            raise HTTPException(status_code=404, detail="No data available")

        # Search through all directories
        for dir_path in upload_dirs:
            data_file = dir_path / "data.pkl"
            if data_file.exists():
                try:
                    df = pd.read_pickle(str(data_file))
                    row = df[df["IN-HOUSE SERIAL NUMBER"] == serial_number]

                    if not row.empty:
                        print(f"Found data in {dir_path}")  # Debug print
                        return {
                            "date_of_issuance": row["DATE OF ISSUANCE"].iloc[0],
                            "in_house_serial_number": row["IN-HOUSE SERIAL NUMBER"].iloc[0],
                            "dv_number": row["DV NUMBER"].iloc[0]
                        }
                except Exception as e:
                    print(f"Error reading {data_file}: {e}")
                    continue

        raise HTTPException(status_code=404, detail="Serial number not found")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_details: {str(e)}")  # Debug print
        raise HTTPException(status_code=500, detail=str(e))
