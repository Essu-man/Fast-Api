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
import socket
from pyngrok import ngrok

app = FastAPI()

# Use your Render URL
BASE_URL = "https://your-app-name.onrender.com"  # Replace with your actual Render URL

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

def get_public_url():
    try:
        # Start ngrok
        public_url = ngrok.connect(8000)
        print(f"Public URL: {public_url}")
        return public_url.public_url
    except Exception as e:
        print(f"Error setting up ngrok: {e}")
        return None

@app.get("/scan/{serial_number}")
async def scan_page(request: Request, serial_number: str):
    """
    Render the scan result page
    """
    try:
        # Get the details using existing logic
        details = await get_details(serial_number)
        return templates.TemplateResponse(
            "scan.html",
            {"request": request, "details": details}
        )
    except HTTPException as e:
        return templates.TemplateResponse(
            "scan.html",
            {"request": request, "error": e.detail}
        )

@app.get("/", response_class=HTMLResponse)
async def get_super():
    """Render the super.html page."""
    return templates.TemplateResponse("super.html", {"request": {}})

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile):
    """
    Upload CSV, generate a new field with alphanumeric hexadecimal codes,
    generate QR codes, and return the updated CSV.
    """
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

        # Get public URL instead of local IP
        public_url = get_public_url()
        if not public_url:
            return JSONResponse(
                status_code=500,
                content={"error": "Could not generate public URL"}
            )

        # Use BASE_URL for QR codes
        base_url = f"{BASE_URL}/scan/"
        print(f"QR Code base URL: {base_url}")

        # Generate QR codes with public URL
        for index, row in df.iterrows():
            try:
                serial_number = str(row["IN-HOUSE SERIAL NUMBER"]).strip()
                qr_data = base_url + serial_number

                # Create QR code
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)

                # Save QR code
                qr_img = qr.make_image(fill_color="black", back_color="white")
                qr_filename = f"{OUTPUT_FOLDER}/qr_{serial_number}.png"
                qr_img.save(qr_filename)

            except Exception as row_error:
                print(f"Error processing row: {row_error}")
                continue

        # Save the updated CSV with QR codes links
        df["QR CODE LINK"] = df["IN-HOUSE SERIAL NUMBER"].apply(lambda x: f"/qr_codes/qr_{x}.png")

        # Store the DataFrame in a file - Let's make this more robust
        data_file = upload_dir / "data.pkl"
        df.to_pickle(str(data_file))  # Convert Path to string and ensure directory exists
        print(f"Data saved to: {data_file}")  # Debug print

        output_file = "Generated_file_with_qr.csv"
        df.to_csv(output_file, index=False)

        return FileResponse(output_file, media_type="text/csv", filename=output_file)

    except Exception as e:
        print(f"Upload error: {str(e)}")  # Debug print
        return {"error": str(e)}

@app.get("/scan-qr/", response_class=HTMLResponse)
async def scan_qr_interface(request: Request):
    """Render the QR scanning interface."""
    return templates.TemplateResponse("scan.html", {"request": request})

@app.get("/get-details/")
async def get_details(serial_number: str):
    """
    Get the details based on the scanned QR code.
    """
    try:
        # Look for the data file in all upload directories
        upload_dirs = sorted(Path(OUTPUT_FOLDER).glob("*"))
        if not upload_dirs:
            raise HTTPException(status_code=400, detail="No uploaded data available.")

        # Search through all directories for the data
        df = None
        for dir in upload_dirs:
            data_file = dir / "data.pkl"
            if data_file.exists():
                try:
                    temp_df = pd.read_pickle(str(data_file))
                    if serial_number in temp_df["IN-HOUSE SERIAL NUMBER"].values:
                        df = temp_df
                        break
                except Exception as e:
                    print(f"Error reading {data_file}: {e}")
                    continue

        if df is None:
            raise HTTPException(status_code=404, detail="Data file not found or serial number not found in any data file.")

        row = df[df["IN-HOUSE SERIAL NUMBER"] == serial_number]

        if row.empty:
            raise HTTPException(status_code=404, detail="Serial number not found.")

        return {
            "date_of_issuance": row["DATE OF ISSUANCE"].values[0],
            "in_house_serial_number": row["IN-HOUSE SERIAL NUMBER"].values[0],
            "dv_number": row["DV NUMBER"].values[0],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving details: {str(e)}")
