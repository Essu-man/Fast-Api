import pandas as pd

# Load the newly created data.pkl
try:
    df = pd.read_pickle("data3.pkl")
    print(df.head())  # Show the first few rows to check if it's structured correctly
    print(df.columns)  # Check column names
except Exception as e:
    print(f"❌ Error loading data.pkl: {e}")
