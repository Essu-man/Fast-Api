import pandas as pd

# Load Excel file (replace 'DV 1Y TO 9999Y- Done.xlsx' with the actual filename)
df = pd.read_excel("DV 1Y TO 9999Y- Done.xlsx")

# Ensure column names are properly formatted (remove leading/trailing spaces)
df.columns = df.columns.str.strip()

# Save DataFrame as a pickle file
df.to_pickle("data.pkl")

print("✅ data.pkl has been created successfully.")