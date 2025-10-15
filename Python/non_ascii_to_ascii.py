import sys
from unidecode import unidecode

def find_non_ascii_chars(file_path):
    """Find and return a set of non-ASCII characters in the file."""
    non_ascii = set()
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        for char in content:
            if ord(char) > 127:
                non_ascii.add(char)
    return non_ascii

def convert_to_ascii(input_path, output_path):
    """Convert non-ASCII to ASCII and save to output file."""
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Option 1: Transliterate using Unidecode (replaces é -> e, etc.)
    ascii_content = unidecode(content)
    
    # Option 2: Uncomment below to simply remove non-ASCII chars instead
    # ascii_content = ''.join(char for char in content if ord(char) <= 127)
    
    with open(output_path, 'w', encoding='ascii', errors='ignore') as f:
        f.write(ascii_content)
    
    print(f"Conversion complete. Output saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_to_ascii.py <input_file> <output_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    non_ascii_chars = find_non_ascii_chars(input_file)
    if non_ascii_chars:
        print("Found non-ASCII characters:", ', '.join(repr(c) for c in sorted(non_ascii_chars)))
    else:
        print("No non-ASCII characters found.")
    
    convert_to_ascii(input_file, output_file)