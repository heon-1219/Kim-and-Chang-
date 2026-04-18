from weasyprint import HTML

# Create the Markdown content
md_content = """# Domain Connection Guide: GoDaddy to Vultr (Streamlit)

This document summarizes the steps taken to connect a GoDaddy domain to a Streamlit application hosted on a Vultr VPS.

## 1. Server Preparation (Vultr)
- **Service**: Vultr Instance
- **Application**: Streamlit (Python-based)
- **Public IP**: `&lt;server-ip&gt;`
- **Execution Strategy**: Direct binding to Port 80 (HTTP default).

## 2. DNS Configuration (GoDaddy)
To point the domain `kctrading.xyz` to the server, an **A Record** was configured:

| Type | Name (Host) | Value (Points to) | TTL |
| :--- | :--- | :--- | :--- |
| **A** | `@` | `&lt;server-ip&gt;` | 1 Hour |

> **Note**: Ensure the Name is set to `@` to use the root domain. If set to `a`, the address becomes `a.kctrading.xyz`.

## 3. Server-Side Setup (Linux/Streamlit)
To allow traffic and run the app on the standard web port (80), the following steps were performed:

### Firewall Configuration
Allow incoming traffic on Port 80:
```bash
sudo ufw allow 80/tcp
sudo ufw reload