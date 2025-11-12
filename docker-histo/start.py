#!/usr/bin/env python3
import os
import shutil
import http.server
import socketserver

# Copier le template vers index.html
shutil.copy('/app/index_template.html', '/app/index.html')

# Lire le fichier
with open('/app/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer SERVERS si défini (format: Name:Port:ApiKey,Name2:Port2:ApiKey2)
servers_config = os.environ.get('SERVERS_CONFIG', '')
if servers_config:
    servers = []
    for item in servers_config.split(','):
        parts = item.split(':', 2)  # Split en 3 parties maximum pour supporter l'API key
        if len(parts) == 3:
            # Format avec API Key
            name, port, api_key = parts
            servers.append(f"{{name:'{name.strip()}',port:{port.strip()},apiKey:'{api_key.strip()}'}}")
        elif len(parts) == 2:
            # Format sans API Key (rétrocompatibilité)
            name, port = parts
            servers.append(f"{{name:'{name.strip()}',port:{port.strip()},apiKey:''}}")
    
    servers_line = f"const DEFAULT_SERVERS = [{','.join(servers)}]; // DOCKER_SERVERS_REPLACE"
    content = content.replace(
        "const DEFAULT_SERVERS = [{ name: 'MT5', port: 8000, apiKey: '' }]; // DOCKER_SERVERS_REPLACE",
        servers_line
    )
    print(f"Servers configured: {servers_config}")

# Remplacer MAGIC si défini
magic_config = os.environ.get('MAGIC_CONFIG', '')
if magic_config:
    magics = []
    for item in magic_config.split(','):
        if ':' in item:
            value, name = item.split(':', 1)
            magics.append(f"{{value:{value.strip()},name:'{name.strip()}'}}")
    
    magic_line = f"const DEFAULT_MAGIC = [{','.join(magics)}]; // DOCKER_MAGIC_REPLACE"
    content = content.replace(
        "const DEFAULT_MAGIC = [{ value: 0, name: 'Manuel' }]; // DOCKER_MAGIC_REPLACE",
        magic_line
    )
    print(f"Magic numbers configured: {magic_config}")

# Écrire le fichier modifié
with open('/app/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

# Servir les fichiers
os.chdir('/app')
print("Dashboard server running: http://0.0.0.0:8089")
print("=" * 50)
print("Configuration format:")
print("SERVERS_CONFIG: Name:Port:ApiKey,Name2:Port2:ApiKey2")
print("MAGIC_CONFIG: Value:Name,Value2:Name2")
print("=" * 50)

Handler = http.server.SimpleHTTPRequestHandler
with socketserver.ThreadingTCPServer(("", 8089), Handler) as httpd:
    httpd.serve_forever()
