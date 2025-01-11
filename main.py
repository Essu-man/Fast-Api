from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import pandas as pd
import os
from pathlib import Path

app = FastAPI()

# Setup templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/qr_codes", StaticFiles(directory="qr_codes"), name="qr_codes")

# Your Render URL (make sure it's correct)
BASE_URL = "https://dvplates.onrender.com"  # No trailing slash

# Ensure directories exist
OUTPUT_FOLDER = "qr_codes"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("super.html", {"request": request})

@app.get("/scan/{serial_number}")  # Remove extra slash
async def scan_page(request: Request, serial_number: str):
    """Render the scan result page"""
    try:
        print(f"Accessing scan page for serial: {serial_number}")  # Debug log
        details = await get_details(serial_number)
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": details,
                "error": None
            }
        )
    except HTTPException as e:
        print(f"HTTP Exception: {e.detail}")  # Debug log
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": str(e.detail)
            }
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # Debug log
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": "An unexpected error occurred"
            }
        )

async def get_details(serial_number: str):
    """Get the details based on the scanned QR code."""
    try:
        print(f"Searching for serial number: {serial_number}")  # Debug log

        # List all pickle files recursively
        all_pickle_files = list(Path(OUTPUT_FOLDER).rglob("*.pkl"))
        print(f"Found pickle files: {[str(f) for f in all_pickle_files]}")  # Debug log

        if not all_pickle_files:
            raise HTTPException(status_code=404, detail="No data files found")

        # Search through all pickle files
        for pickle_file in all_pickle_files:
            try:
                df = pd.read_pickle(str(pickle_file))
                row = df[df["IN-HOUSE SERIAL NUMBER"] == serial_number]

                if not row.empty:
                    print(f"Found matching data in {pickle_file}")  # Debug log
                    return {
                        "date_of_issuance": row["DATE OF ISSUANCE"].iloc[0],
                        "in_house_serial_number": row["IN-HOUSE SERIAL NUMBER"].iloc[0],
                        "dv_number": row["DV NUMBER"].iloc[0]
                    }
            except Exception as e:
                print(f"Error reading {pickle_file}: {e}")  # Debug log
                continue

        raise HTTPException(
            status_code=404,
            detail=f"No data found for serial number: {serial_number}"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_details: {str(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile):
    try:
        # Create unique directory for this upload
        upload_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_dir = Path(OUTPUT_FOLDER) / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Process CSV
        df = pd.read_csv(file.file)

        # Use Vercel URL for QR codes
        base_url = f"{BASE_URL}/scan/"
        print(f"QR Code base URL: {base_url}")

        # Generate QR codes
        for index, row in df.iterrows():
            serial_number = str(row["IN-HOUSE SERIAL NUMBER"]).strip()
            qr_data = base_url + serial_number

            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)

            # Save QR code
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_filename = upload_dir / f"qr_{serial_number}.png"
            qr_img.save(str(qr_filename))

        # Save data
        data_file = upload_dir / "data.pkl"
        df.to_pickle(str(data_file))

        # Save CSV
        output_file = upload_dir / "Generated_qr.csv"
        df.to_csv(str(output_file), index=False)

        return FileResponse(str(output_file), filename="Generated_qr.csv")

    except Exception as e:
        print(f"Upload error: {str(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=str(e))
