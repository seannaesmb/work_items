import csv
import sys
from unidecode import unidecode
import chardet

# Increase the CSV field size limit
csv.field_size_limit(10**7) 

def detect_encoding(file_path, num_bytes=10000):
    with open(file_path, 'rb') as f:
        raw_data = f.read(num_bytes)
    result = chardet.detect(raw_data)
    return result['encoding'] or 'utf-8'

def convert_csv_to_ascii(input_file, output_file, has_header=True):
    # Detect encoding
    detected_encoding = detect_encoding(input_file)
    print(f"Detected encoding: {detected_encoding}")

    with open(input_file, 'r', encoding=detected_encoding, errors='replace') as infile, \
         open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        for i, row in enumerate(reader):
            ascii_row = [unidecode(cell) if isinstance(cell, str) else cell for cell in row]
            writer.writerow(ascii_row)

    print(f"Converted CSV saved to: {output_file}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert_to_ascii.py input.csv output.csv [--no-header]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    has_header = '--no-header' not in sys.argv
    convert_csv_to_ascii(input_path, output_path, has_header)
