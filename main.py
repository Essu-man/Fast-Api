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
from dotenv import load_dotenv
from pathlib import Path
import logging
import uuid
from openpyxl import load_workbook
import traceback

### configuration setting for logging to file 
logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s', filename="logs/app.log")
logger = logging.getLogger()
logger.setLevel(logging.NOTSET)

console = logging.StreamHandler()
console.setLevel(logging.NOTSET)
logging.getLogger("").addHandler(console)

app = FastAPI()

### initialize loading of environmental variable from .env
load_dotenv()

# Production URL
BASE_URL = os.getenv('BASE_URL')

print(f"app base url : {BASE_URL}")

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

def generate_code():
    """Generate a formatted random alphanumeric hexadecimal code with hyphens."""
    raw_code = ''.join(random.choices(string.hexdigits.upper(), k=15))
    formatted_code = '-'.join([raw_code[i:i+5] for i in range(0, len(raw_code), 5)])
    return formatted_code

def read_file(file: UploadFile) -> pd.DataFrame:
    """Read either CSV or Excel file into a DataFrame"""
    file_extension = file.filename.lower()

    try:
        if file_extension.endswith('.csv'):
            df = pd.read_csv(file.file)
        elif file_extension.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file.file)
        else:
            raise ValueError("Unsupported file format. Please upload CSV or Excel file.")

        # Clean column names
        df.columns = df.columns.str.strip()

        # Format Form D numbers: handle NaN values and add leading zero
        if "FORM D" in df.columns:
            df["FORM D"] = df["FORM D"].apply(
                lambda x: f"0{int(float(x))}" if pd.notna(x) else ""
            )

        print("=== DataFrame Debug Info ===")
        print(f"Columns: {df.columns.tolist()}")
        print("\nFirst few rows after formatting:")
        print(df.head())

        return df

    except Exception as e:
        print(f"Error reading file: {str(e)}")
        raise

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
            print(f"Columns after cleaning: {df.columns.tolist()}")

            # Clean column names
            df.columns = df.columns.str.strip()

            # Check for required columns
            required_columns = {"DV NUMBER", "FORM D"}
            current_columns = {col.strip().upper() for col in df.columns}

            missing_columns = []
            for col in required_columns:
                if col not in current_columns:
                    missing_columns.append(col)

            if missing_columns:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Missing required columns: {', '.join(missing_columns)}. Found columns: {df.columns.tolist()}"
                    }
                )

            # Generate "In-house serial number" for each row
            df["IN-HOUSE SERIAL NUMBER"] = [generate_code() for _ in range(len(df))]
            df["EXPIRY DATE"] = "31/12/2025"

            # Use HTTPS production URL for direct links
            base_url = f"{BASE_URL}/"  # Direct root URL
            print(f"Using production URL: {base_url}")

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

                    # Create QR code with direct link
                    qr_data = base_url + serial_number
                    print(f"QR Data URL: {qr_data}")

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

            # Add direct links (not QR code image links)
            df["DIRECT LINK"] = df["IN-HOUSE SERIAL NUMBER"].apply(
                lambda x: f"{BASE_URL}/{x}"
            )

            # Store the DataFrame
            data_file = upload_dir / "data.pkl"
            df.to_pickle(str(data_file))

            # Save output file
            if file_extension.endswith('.xlsx'):
                output_file = upload_dir / "Generated_qr.xlsx"
                df.to_excel(str(output_file), index=False, engine='openpyxl')
                media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                output_file = upload_dir / "Generated_qr.csv"
                df.to_csv(str(output_file), index=False)
                media_type = "text/csv"

            print(f"Saving output file to: {output_file}")

            return FileResponse(
                path=str(output_file),
                filename=output_file.name,
                media_type=media_type
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
                    if serial_number in temp_df["IN-HOUSE SERIAL NUMBER"].values:
                        df = temp_df
                        break
                except Exception as e:
                    print(f"Error reading {data_file}: {e}")
                    continue
        
        print(f"is df object prenset or none : {df is None}")
        
        row = None
        
        if df is None:
            
            print(f"defaulting to getting details form generated qr csv/xlsx")
            
            generated_file = dir / "Generated_qr.csv"
            
            print(f"is generated_qr.csv file exist : {generated_file.exists()}")
            
            if generated_file.exists():
                try:
                    df = pd.read_csv(str(generated_file))
                    if serial_number not in df["IN-HOUSE SERIAL NUMBER"].values:
                        raise HTTPException(status_code=404, detail="Serial number not found .")
                except Exception as e:
                    print(f"Error reading {generated_file}: {e}")
                    raise HTTPException(status_code=500, detail=f"Error retrieving details: {str(e)}")
            
            print(f"is df object present : {(df != None)}")
            
            if df is not None:
                row = df[df["IN-HOUSE SERIAL NUMBER"] == serial_number]
                
                logger.info(f"get details with in-house serial number : {serial_number} : if rows empty : {row.empty}")
                
                print(f"get details with in-house serial number : {serial_number} : if rows empty : {row.empty}")

            if row.empty:
                raise HTTPException(status_code=404, detail="Serial number not found.")
            else:
                row_keys = row.keys
                print(f"list of keys found in rows : {row_keys}")

        return {
            "dv_number": str(row["DV NUMBER"].iloc[0]) if not pd.isna(row["DV NUMBER"].iloc[0]) else "",
            "in_house_serial_number": str(row["IN-HOUSE SERIAL NUMBER"].iloc[0]),
            "form_d": str(row["FORM D"].iloc[0]) if not pd.isna(row["FORM D"].iloc[0]) else "",
            "expiry_date": str(row["EXPIRY DATE"].iloc[0]) if not pd.isna(row["EXPIRY DATE"].iloc[0]) else "",
            "factory_serial_number": str(row["SERIAL NUMBER"].iloc[0]) if not pd.isna(row["SERIAL NUMBER"].iloc[0]) else ""
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_details: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error retrieving details: {str(e)}")

@app.get("/details/{serial_number}")
async def show_details(request: Request, serial_number: str):
    """Show details page directly."""
    try:
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
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": e.detail
            }
        )

@app.get("/{serial_number}")
async def direct_details(request: Request, serial_number: str):
    """Show details directly when accessing via serial number URL."""
    try:
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
        return templates.TemplateResponse(
            "scan.html",
            {
                "request": request,
                "details": None,
                "error": e.detail
            }
        )