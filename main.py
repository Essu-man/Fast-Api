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
import openpyxl

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

def read_file(file: UploadFile) -> pd.DataFrame:
    """Read either CSV or Excel file into a DataFrame"""
    file_extension = file.filename.lower()

    if file_extension.endswith('.csv'):
        return pd.read_csv(file.file)
    elif file_extension.endswith(('.xlsx', '.xls')):
        return pd.read_excel(file.file)
    else:
        raise ValueError("Unsupported file format. Please upload CSV or Excel file.")

@app.get("/scan/{serial_number}")
async def scan_page(request: Request, serial_number: str):
    """Render the scan result page"""
    try:
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
async def get_super(request: Request):
    """Render the super.html page."""
    return templates.TemplateResponse("super.html", {"request": request})

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile):
    try:
        # Check file extension
        file_extension = file.filename.lower()
        if not file_extension.endswith(('.csv', '.xlsx', '.xls')):
            return JSONResponse(
                status_code=400,
                content={"error": "Only CSV and Excel files are allowed."}
            )

        # Create a unique directory for this upload
        upload_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_dir = Path(OUTPUT_FOLDER) / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Load file into DataFrame
            df = read_file(file)
            print(f"Original columns: {df.columns.tolist()}")

            # Check for required columns
            if "DV NUMBER" not in df.columns or "FORM D" not in df.columns:
                missing_columns = []
                if "DV NUMBER" not in df.columns:
                    missing_columns.append("DV NUMBER")
                if "FORM D" not in df.columns:
                    missing_columns.append("FORM D")
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Missing required columns: {', '.join(missing_columns)}. Found columns: {df.columns.tolist()}"
                    }
                )

            # Clean existing data
            df["DV NUMBER"] = df["DV NUMBER"].astype(str).str.strip()
            df["FORM D"] = df["FORM D"].astype(str).str.strip()

            # Only generate new columns that don't exist
            df["IN-HOUSE SERIAL NUMBER"] = [generate_code() for _ in range(len(df))]
            df["EXPIRY DATE"] = "01/12/2024"

            print(f"Processed data:\n{df.head()}")

            # Use the DILA Generis URL
            base_url = f"{BASE_URL}/scan/"

            # Generate QR codes for each row
            for index, row in df.iterrows():
                try:
                    serial_number = str(row["IN-HOUSE SERIAL NUMBER"]).strip()
                    dv_number = str(row["DV NUMBER"]).strip()
                    form_d = str(row["FORM D"]).strip()

                    print(f"Processing row: DV={dv_number}, Serial={serial_number}, Form D={form_d}")

                    if not serial_number:
                        print("Warning: Empty serial number found")
                        continue

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

                except Exception as row_error:
                    print(f"Error processing row: {row_error}")
                    continue

            # Add QR code links
            df["QR CODE LINK"] = df["IN-HOUSE SERIAL NUMBER"].apply(
                lambda x: f"/qr_codes/{upload_id}/qr_{x}.png"
            )

            # Store the DataFrame
            data_file = upload_dir / "data.pkl"
            df.to_pickle(str(data_file))

            # Save output file
            if file_extension.endswith('.xlsx'):
                output_file = upload_dir / "Generated_qr.xlsx"
                df.to_excel(str(output_file), index=False)
            else:
                output_file = upload_dir / "Generated_qr.csv"
                df.to_csv(str(output_file), index=False)

            print(f"Final columns in output: {df.columns.tolist()}")
            print(f"Sample of final data:\n{df.head()}")

            return FileResponse(
                str(output_file),
                filename=f"Generated_qr{file_extension}",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if file_extension.endswith('.xlsx')
                    else "text/csv"
            )

        except Exception as e:
            print(f"Error processing file: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": f"Error processing file: {str(e)}"}
            )

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/get-details/{serial_number}")
async def get_details(serial_number: str):
    """Get the details based on the scanned QR code."""
    try:
        upload_dirs = sorted(Path(OUTPUT_FOLDER).glob("*"))
        if not upload_dirs:
            raise HTTPException(status_code=400, detail="No uploaded data available.")

        df = None
        for dir in upload_dirs:
            data_file = dir / "data.pkl"
            if data_file.exists():
                try:
                    temp_df = pd.read_pickle(str(data_file))
                    # Debug print
                    print(f"Looking for serial number: {serial_number}")
                    print(f"Columns in DataFrame: {temp_df.columns.tolist()}")
                    print(f"Sample data:\n{temp_df.head()}")

                    if serial_number in temp_df["IN-HOUSE SERIAL NUMBER"].values:
                        df = temp_df
                        break
                except Exception as e:
                    print(f"Error reading {data_file}: {e}")
                    continue

        if df is None:
            raise HTTPException(status_code=404, detail="Serial number not found in any data file.")

        row = df[df["IN-HOUSE SERIAL NUMBER"] == serial_number]

        # Debug print
        print(f"Found row data: {row.to_dict('records')}")

        if row.empty:
            raise HTTPException(status_code=404, detail="Serial number not found.")

        # Convert values to string to avoid nan
        return {
            "dv_number": str(row["DV NUMBER"].iloc[0]) if not pd.isna(row["DV NUMBER"].iloc[0]) else "",
            "in_house_serial_number": str(row["IN-HOUSE SERIAL NUMBER"].iloc[0]),
            "form_d": str(row["FORM D"].iloc[0]) if not pd.isna(row["FORM D"].iloc[0]) else "",
            "expiry_date": str(row["EXPIRY DATE"].iloc[0]) if not pd.isna(row["EXPIRY DATE"].iloc[0]) else "",
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_details: {str(e)}")  # Debug print
        raise HTTPException(status_code=500, detail=f"Error retrieving details: {str(e)}")