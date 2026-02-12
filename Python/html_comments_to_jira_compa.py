from bs4 import BeautifulSoup
import html
import re
import pandas as pd

def convert_tables(soup):
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue

            is_header = any(c.name == "th" for c in cells)
            sep = "||" if is_header else "|"

            row = sep
            for cell in cells:
                text = cell.get_text(" ", strip=True)
                row += f" {text} {sep}"
            rows.append(row)

        jira_table = "\n".join(rows)
        table.replace_with(f"\n{jira_table}\n")


def html_to_jira(html_text):
    if pd.isna(html_text):
        return ""

    html_text = html.unescape(str(html_text))
    soup = BeautifulSoup(html_text, "html.parser")


    # --- TABLES ---
    convert_tables(soup)


    # Links
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        a.replace_with(f"[{text}|{href}]")

    # Bold / Italic
    for tag in soup.find_all(["strong", "b"]):
        tag.replace_with(f"*{tag.get_text()}*")

    for tag in soup.find_all(["em", "i"]):
        tag.replace_with(f"_{tag.get_text()}_")

    # Inline code
    for code in soup.find_all("code"):
        code.replace_with(f"{{{{{code.get_text()}}}}}")

    # Code blocks
    for pre in soup.find_all("pre"):
        pre.replace_with(f"\n{{code}}\n{pre.get_text()}\n{{code}}\n")

    # Unordered lists
    for ul in soup.find_all("ul"):
        items = []
        for li in ul.find_all("li", recursive=False):
            items.append(f"* {li.get_text(strip=True)}")
        ul.replace_with("\n" + "\n".join(items) + "\n")

    # Ordered lists
    for ol in soup.find_all("ol"):
        items = []
        for li in ol.find_all("li", recursive=False):
            items.append(f"# {li.get_text(strip=True)}")
        ol.replace_with("\n" + "\n".join(items) + "\n")

    # Paragraphs / line breaks
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

df = pd.read_csv("C:\\projects\\sbrown\\Python\\db_file_exports\\output_csv\\journals_202602052106.csv")

# Replace the same column in-place
df["notes"] = df["notes"].apply(html_to_jira)

df.to_csv("C:\\projects\\sbrown\\Python\\db_file_exports\\output_csv\\journals_202602052106_jira_comp.csv", index=False)

