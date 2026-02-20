import pandas as pd

url = "https://www.deleadout.com/post/hier-is-em-dit-zijn-alle-rennersprogramma-s"

tables = pd.read_html(url)

print(f"Aantal tabellen gevonden: {len(tables)}")

df = tables[0]

print(df.head())

# opslaan als Excel
df.to_excel("rennersprogrammas.xlsx", index=False)