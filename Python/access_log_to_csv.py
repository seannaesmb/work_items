import re
import csv

# Regex for your given line format
pattern = re.compile(
    r'(?P<IPs>(?:\S+\s+){4})'                  # 4 IP addresses
    r'HTTP/\S+\s+-\s+(?P<Method>\S+)\s+-\s+'   # HTTP version + method
    r'(?P<Path>\S+)\s+'                        # URL path
    r'\[(?P<Timestamp>[^\]]+)\]\s+'            # [23/Oct/2024:12:30:47 -0400]
    r'"(?P<Request>[^"]+)"\s+'                 # "GET /path HTTP/1.1"
    r'(?P<Status>\d{3})\s+'                    # 200
    r'(?P<Bytes>\S+)\s+'                       # 155
    r'"(?P<Referrer>[^"]*)"\s+'                # "referrer"
    r'"(?P<UserAgent>[^"]*)"\s+'               # "user agent"
    r'(?P<RequestID>\S+)\s+'                   # request ID
    r'"(?P<ClientCertSubject>[^"]*)"'          # "C=My, O=Cert..."
)

with open('C:\\Users\\sbrown.ext\\ssl_access_log', 'r', encoding='utf-8') as infile, \
     open('C:\\Users\\sbrown.ext\\tomcat_parsed.csv', 'w', newline='', encoding='utf-8') as outfile:

    writer = csv.writer(outfile)
    writer.writerow([
        'IPs', 'Method', 'Path', 'Timestamp', 'Status', 'Bytes',
        'Referrer', 'UserAgent', 'RequestID', 'ClientCertSubject'
    ])

    for line in infile:
        match = pattern.search(line)
        if match:
            data = match.groupdict()
            writer.writerow([
                data['IPs'].strip(),
                data['Method'],
                data['Path'],
                data['Timestamp'],
                data['Status'],
                data['Bytes'],
                data['Referrer'],
                data['UserAgent'],
                data['RequestID'],
                data['ClientCertSubject']
            ])
